from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import eval_public_fixture
from scripts.eval_public_fixture import (
    DEFAULT_CASES_PATH,
    DEFAULT_CORPUS_PATH,
    EVALUATOR_PATH,
    Citation,
    build_report,
    citation_is_exact,
    find_privacy_markers,
    load_cases,
    load_documents,
    make_citation,
    render_report,
    sha256_file,
    write_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = (
    REPO_ROOT
    / "reports"
    / "evidence"
    / "portfolio-audit-2026-07-13"
    / "dream_motif_public_retrieval_v1.json"
)
README_PATH = REPO_ROOT / "README.md"


def test_public_fixture_has_only_bounded_synthetic_records() -> None:
    documents = load_documents()
    cases = load_cases(source_ids={document.source_id for document in documents})

    assert len(documents) == 6
    assert len(cases) == 8
    assert all(document.provenance == "handcrafted-synthetic" for document in documents)
    assert all(
        not find_privacy_markers(f"{document.title}\n{document.text}") for document in documents
    )
    assert {case.kind for case in cases} == {"answerable", "no-answer"}


def test_public_fixture_report_is_content_addressed_and_reproducible() -> None:
    tracked = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    regenerated = build_report(run_date=tracked["run_date"])

    assert tracked == regenerated
    assert render_report(regenerated) == REPORT_PATH.read_text(encoding="utf-8")
    assert regenerated["inputs"]["corpus"]["sha256"] == sha256_file(DEFAULT_CORPUS_PATH)
    assert regenerated["inputs"]["cases"]["sha256"] == sha256_file(DEFAULT_CASES_PATH)
    assert regenerated["inputs"]["evaluator"]["sha256"] == sha256_file(EVALUATOR_PATH)
    assert regenerated["passed"] is True
    assert all(regenerated["gates"].values())


def test_public_fixture_report_can_be_written_as_operator_artifact(tmp_path: Path) -> None:
    output_path = tmp_path / "nested" / "public_eval.json"
    report = build_report(run_date="2026-09-01")

    write_report(report, output_path)

    assert output_path.read_text(encoding="utf-8") == render_report(report)


def test_public_fixture_cli_writes_report_to_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "public_eval.json"

    assert eval_public_fixture.main(["--run-date", "2026-09-01", "--output", str(output_path)]) == 0

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written == build_report(run_date="2026-09-01")
    assert "WROTE:" in capsys.readouterr().out


def test_public_fixture_cli_rejects_stale_report(tmp_path: Path) -> None:
    stale_report = build_report(run_date="2026-09-01")
    stale_report["metrics"]["hit_at_1"] = 0.0
    stale_path = tmp_path / "stale.json"
    stale_path.write_text(render_report(stale_report), encoding="utf-8")

    with pytest.raises(SystemExit, match="public fixture evaluation report is stale"):
        eval_public_fixture.main(["--check", str(stale_path)])


def test_public_fixture_citations_are_exact_source_slices() -> None:
    documents = load_documents()
    document = documents[0]
    citation = make_citation("paper moth", document)

    assert citation_is_exact(citation, document)
    assert citation.quote == document.text[citation.start_char : citation.end_char]
    assert not citation_is_exact(replace(citation, quote="invented text"), document)
    assert not citation_is_exact(
        Citation(
            source_id="synthetic-999",
            quote=citation.quote,
            start_char=citation.start_char,
            end_char=citation.end_char,
        ),
        document,
    )


def test_public_fixture_no_answer_cases_abstain() -> None:
    report = build_report(run_date="2026-07-13")
    no_answer_traces = [trace for trace in report["traces"] if trace["kind"] == "no-answer"]

    assert no_answer_traces
    assert all(trace["retrieved"] == [] for trace in no_answer_traces)
    assert all(trace["citations"] == [] for trace in no_answer_traces)
    assert report["metrics"]["no_answer_accuracy"] == 1.0


def test_privacy_marker_scan_rejects_common_private_shapes() -> None:
    for unsafe in [
        "owner@example.test",
        "https://private.example.test/item",
        "+1 555 123 4567",
        "2026-07-13",
        "/home/operator/archive.json",
        "My personal journal entry",
    ]:
        assert find_privacy_markers(unsafe), unsafe


def test_readme_keeps_public_evidence_claims_bounded() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert "case-study prototype, не product release" in readme
    assert "не предназначена для психологической или клинической диагностики" in readme
    assert "это не результат" in readme
    assert "live hybrid retrieval" in readme
    assert "Phases 1–26 complete" not in readme
    assert "реальной пользовательской сессии" not in readme
