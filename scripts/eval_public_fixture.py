from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
DEFAULT_CORPUS_PATH = PROJECT_ROOT / "evals" / "privacy_safe_retrieval_v1" / "corpus.jsonl"
DEFAULT_CASES_PATH = PROJECT_ROOT / "evals" / "privacy_safe_retrieval_v1" / "cases.jsonl"
EVALUATOR_VERSION = "public-retrieval-citation-v1"
MIN_TOKEN_OVERLAP = 2
MIN_QUERY_COVERAGE = 0.75
RESULT_LIMIT = 3

_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")
_SOURCE_ID_RE = re.compile(r"synthetic-[0-9]{3}")
_CASE_ID_RE = re.compile(r"[RN][0-9]{2}")
_PRIVACY_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "url": re.compile(r"(?:https?://|www\.)", re.IGNORECASE),
    "phone": re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)"),
    "iso-date": re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    "uuid": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    ),
    "local-path": re.compile(r"(?:/home/|[A-Z]:\\)", re.IGNORECASE),
    "social-handle": re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,}"),
    "first-person": re.compile(r"\b(?:i|me|my|mine|we|our|ours)\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class PublicDocument:
    source_id: str
    title: str
    text: str
    provenance: str


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    query: str
    kind: str
    expected_source_ids: tuple[str, ...]


@dataclass(frozen=True)
class RankedDocument:
    source_id: str
    score: int
    query_coverage: float


@dataclass(frozen=True)
class Citation:
    source_id: str
    quote: str
    start_char: int
    end_char: int


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def find_privacy_markers(text: str) -> list[str]:
    return sorted(name for name, pattern in _PRIVACY_PATTERNS.items() if pattern.search(text))


def load_documents(path: Path = DEFAULT_CORPUS_PATH) -> list[PublicDocument]:
    records = _load_jsonl(path)
    expected_keys = {"source_id", "title", "text", "provenance"}
    documents: list[PublicDocument] = []
    seen_ids: set[str] = set()

    for line_number, record in enumerate(records, start=1):
        if set(record) != expected_keys:
            raise ValueError(f"{path}:{line_number}: unexpected corpus schema")
        document = PublicDocument(**record)
        if not _SOURCE_ID_RE.fullmatch(document.source_id):
            raise ValueError(f"{path}:{line_number}: invalid synthetic source_id")
        if document.source_id in seen_ids:
            raise ValueError(f"{path}:{line_number}: duplicate source_id")
        if document.provenance != "handcrafted-synthetic":
            raise ValueError(f"{path}:{line_number}: non-synthetic provenance")
        if not document.title.strip() or not document.text.strip():
            raise ValueError(f"{path}:{line_number}: blank title or text")
        markers = find_privacy_markers(f"{document.title}\n{document.text}")
        if markers:
            raise ValueError(f"{path}:{line_number}: privacy markers: {', '.join(markers)}")
        seen_ids.add(document.source_id)
        documents.append(document)

    if not documents:
        raise ValueError(f"{path}: corpus must not be empty")
    return documents


def load_cases(
    path: Path = DEFAULT_CASES_PATH,
    *,
    source_ids: Iterable[str] | None = None,
) -> list[EvalCase]:
    records = _load_jsonl(path)
    expected_keys = {"case_id", "query", "kind", "expected_source_ids"}
    known_source_ids = set(source_ids or ())
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()

    for line_number, record in enumerate(records, start=1):
        if set(record) != expected_keys:
            raise ValueError(f"{path}:{line_number}: unexpected case schema")
        expected = record["expected_source_ids"]
        if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
            raise ValueError(f"{path}:{line_number}: expected_source_ids must be a string list")
        case = EvalCase(
            case_id=record["case_id"],
            query=record["query"],
            kind=record["kind"],
            expected_source_ids=tuple(expected),
        )
        if not _CASE_ID_RE.fullmatch(case.case_id) or case.case_id in seen_ids:
            raise ValueError(f"{path}:{line_number}: invalid or duplicate case_id")
        if case.kind not in {"answerable", "no-answer"}:
            raise ValueError(f"{path}:{line_number}: invalid kind")
        if not case.query.strip():
            raise ValueError(f"{path}:{line_number}: blank query")
        if case.kind == "answerable" and not case.expected_source_ids:
            raise ValueError(f"{path}:{line_number}: answerable case needs expected sources")
        if case.kind == "no-answer" and case.expected_source_ids:
            raise ValueError(f"{path}:{line_number}: no-answer case cannot expect sources")
        if known_source_ids and not set(case.expected_source_ids).issubset(known_source_ids):
            raise ValueError(f"{path}:{line_number}: expected source is absent from corpus")
        seen_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise ValueError(f"{path}: cases must not be empty")
    return cases


def rank_documents(
    query: str,
    documents: list[PublicDocument],
    *,
    min_token_overlap: int = MIN_TOKEN_OVERLAP,
    min_query_coverage: float = MIN_QUERY_COVERAGE,
    limit: int = RESULT_LIMIT,
) -> list[RankedDocument]:
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []
    ranked: list[RankedDocument] = []
    for document in documents:
        document_tokens = set(_tokenize(f"{document.title} {document.text}"))
        score = len(query_tokens & document_tokens)
        query_coverage = round(score / len(query_tokens), 6)
        if score >= min_token_overlap and query_coverage >= min_query_coverage:
            ranked.append(
                RankedDocument(
                    source_id=document.source_id,
                    score=score,
                    query_coverage=query_coverage,
                )
            )
    return sorted(ranked, key=lambda item: (-item.score, item.source_id))[:limit]


def make_citation(query: str, document: PublicDocument) -> Citation:
    query_tokens = set(_tokenize(query))
    candidates: list[tuple[int, int, str, int]] = []
    for sentence in re.finditer(r"[^.!?]+(?:[.!?]+|$)", document.text):
        raw_quote = sentence.group(0)
        leading_space = len(raw_quote) - len(raw_quote.lstrip())
        quote = raw_quote.strip()
        if not quote:
            continue
        start_char = sentence.start() + leading_space
        support = len(query_tokens & set(_tokenize(quote)))
        candidates.append((support, -start_char, quote, start_char))
    if not candidates:
        raise ValueError(f"{document.source_id}: document has no citable text")
    _, _, quote, start_char = max(candidates)
    return Citation(
        source_id=document.source_id,
        quote=quote,
        start_char=start_char,
        end_char=start_char + len(quote),
    )


def citation_is_exact(citation: Citation, document: PublicDocument) -> bool:
    if citation.source_id != document.source_id:
        return False
    if citation.start_char < 0 or citation.end_char <= citation.start_char:
        return False
    return document.text[citation.start_char : citation.end_char] == citation.quote


def build_report(
    *,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    cases_path: Path = DEFAULT_CASES_PATH,
    run_date: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", run_date):
        raise ValueError("run_date must use YYYY-MM-DD")

    documents = load_documents(corpus_path)
    document_by_id = {document.source_id: document for document in documents}
    cases = load_cases(cases_path, source_ids=document_by_id)

    answerable_count = 0
    no_answer_count = 0
    hit_at_1_count = 0
    hit_at_3_count = 0
    reciprocal_rank_total = 0.0
    expected_sources_found = 0
    expected_sources_total = 0
    correct_citation_sources = 0
    citation_count = 0
    exact_citation_count = 0
    supported_citation_count = 0
    correct_no_answer_count = 0
    traces: list[dict[str, Any]] = []

    for case in cases:
        ranked = rank_documents(case.query, documents)
        expected = set(case.expected_source_ids)
        retrieved_ids = [item.source_id for item in ranked]
        citations = [make_citation(case.query, document_by_id[item.source_id]) for item in ranked]

        if case.kind == "answerable":
            answerable_count += 1
            if retrieved_ids and retrieved_ids[0] in expected:
                hit_at_1_count += 1
            if expected.intersection(retrieved_ids[:3]):
                hit_at_3_count += 1
            for index, source_id in enumerate(retrieved_ids, start=1):
                if source_id in expected:
                    reciprocal_rank_total += 1.0 / index
                    break
            expected_sources_found += len(expected.intersection(retrieved_ids))
            expected_sources_total += len(expected)
        else:
            no_answer_count += 1
            if not retrieved_ids:
                correct_no_answer_count += 1

        for citation in citations:
            citation_count += 1
            document = document_by_id[citation.source_id]
            if citation.source_id in expected:
                correct_citation_sources += 1
            if citation_is_exact(citation, document):
                exact_citation_count += 1
            if set(_tokenize(case.query)).intersection(_tokenize(citation.quote)):
                supported_citation_count += 1

        traces.append(
            {
                "case_id": case.case_id,
                "kind": case.kind,
                "query": case.query,
                "expected_source_ids": list(case.expected_source_ids),
                "retrieved": [asdict(item) for item in ranked],
                "citations": [asdict(citation) for citation in citations],
            }
        )

    metrics = {
        "hit_at_1": _ratio(hit_at_1_count, answerable_count),
        "hit_at_3": _ratio(hit_at_3_count, answerable_count),
        "mrr": _ratio(reciprocal_rank_total, answerable_count),
        "expected_source_recall": _ratio(expected_sources_found, expected_sources_total),
        "citation_source_precision": _ratio(correct_citation_sources, citation_count),
        "citation_exactness": _ratio(exact_citation_count, citation_count),
        "citation_query_support": _ratio(supported_citation_count, citation_count),
        "no_answer_accuracy": _ratio(correct_no_answer_count, no_answer_count),
    }
    gates = {name: value == 1.0 for name, value in metrics.items()}

    return {
        "schema_version": 1,
        "evaluator_version": EVALUATOR_VERSION,
        "run_date": run_date,
        "scope": (
            "Deterministic lexical replay on public handcrafted synthetic data; does not validate "
            "live hybrid embeddings, private-corpus behavior, model output, clinical validity, "
            "external use, or production operation."
        ),
        "inputs": {
            "evaluator": _file_descriptor(EVALUATOR_PATH),
            "corpus": _input_descriptor(corpus_path, count=len(documents)),
            "cases": _input_descriptor(cases_path, count=len(cases)),
        },
        "configuration": {
            "min_token_overlap": MIN_TOKEN_OVERLAP,
            "min_query_coverage": MIN_QUERY_COVERAGE,
            "result_limit": RESULT_LIMIT,
            "tie_breaker": "source_id ascending",
        },
        "counts": {
            "answerable_cases": answerable_count,
            "no_answer_cases": no_answer_count,
            "citations": citation_count,
        },
        "metrics": metrics,
        "gates": gates,
        "passed": all(gates.values()),
        "traces": traces,
    }


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output_path.parent,
            delete=False,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_file.write(render_report(report))
            temp_path = Path(temp_file.name)
        temp_path.replace(output_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _input_descriptor(path: Path, *, count: int) -> dict[str, Any]:
    return {**_file_descriptor(path), "records": count}


def _file_descriptor(path: Path) -> dict[str, str]:
    try:
        display_path = path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        display_path = path.name
    return {"path": display_path, "sha256": sha256_file(path)}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{line_number}: record must be an object")
        records.append(record)
    return records


def _tokenize(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(value)]


def _ratio(numerator: float, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--run-date", help="Evidence date in YYYY-MM-DD format")
    parser.add_argument("--check", type=Path, help="Compare with an existing tracked report")
    parser.add_argument("--output", type=Path, help="Write the rendered report to this path")
    args = parser.parse_args(argv)

    if args.check:
        if args.output:
            parser.error("--output cannot be combined with --check")
        expected = json.loads(args.check.read_text(encoding="utf-8"))
        run_date = expected.get("run_date")
        if not isinstance(run_date, str):
            parser.error("checked report must contain a string run_date")
        actual = build_report(corpus_path=args.corpus, cases_path=args.cases, run_date=run_date)
        if actual != expected:
            raise SystemExit(
                "public fixture evaluation report is stale; regenerate it after reviewing drift"
            )
        print(
            f"PASS: {len(actual['traces'])} cases, content={actual['inputs']['corpus']['sha256']}"
        )
        return 0

    if not args.run_date:
        parser.error("--run-date is required when not using --check")
    report = build_report(corpus_path=args.corpus, cases_path=args.cases, run_date=args.run_date)
    if args.output:
        write_report(report, args.output)
        print(
            f"WROTE: {args.output}, cases={len(report['traces'])}, "
            f"content={report['inputs']['corpus']['sha256']}"
        )
    else:
        print(render_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
