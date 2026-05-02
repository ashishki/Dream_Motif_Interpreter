from __future__ import annotations

from pathlib import Path

from scripts.eval import load_evaluation_dataset, load_evaluation_history

DOCS_PATH = Path(__file__).resolve().parents[2] / "docs" / "retrieval_eval.md"


def test_eval_dataset_covers_all_query_types() -> None:
    queries = load_evaluation_dataset(DOCS_PATH)

    assert len(queries) >= 10

    type_counts: dict[str, int] = {}
    for query in queries:
        type_counts[query.query_type] = type_counts.get(query.query_type, 0) + 1

    assert type_counts["simple"] >= 1
    assert type_counts["multi-doc"] >= 1
    assert type_counts["multi-hop"] >= 1
    assert type_counts["no-answer"] >= 1


def test_eval_history_has_valid_first_entry() -> None:
    rows = load_evaluation_history(DOCS_PATH)
    completed_rows = [
        row
        for row in rows
        if row["Date"]
        and row["Task"]
        and row["Corpus Version"]
        and row["Eval Source"]
        and row["hit@3"] not in {"", "—", "N/A", "SKIPPED"}
        and row["MRR"] not in {"", "—", "N/A", "SKIPPED"}
    ]

    assert completed_rows


def test_phase18_user_search_regression_dataset_is_documented() -> None:
    text = DOCS_PATH.read_text(encoding="utf-8")

    assert "## Phase 18 User Search Regression Dataset" in text
    for query in [
        "молитва",
        "где упоминается молитва",
        "где фигурирует молитва",
        "религиозные сюжеты",
        "церковь",
        "рождественское песнопение",
    ]:
        assert query in text

    assert "Christmas hymn/prayer dream: expected relevant" in text
    assert "Church/icon/prayer dreams: expected relevant" in text
    assert "A result is correct only when it exposes an archive-backed evidence fragment" in text
    assert "must be counted as false positives" in text


def test_phase18_eval_run_documents_unit_regression_and_live_limit() -> None:
    text = DOCS_PATH.read_text(encoding="utf-8")

    assert "## Phase 18 Evaluation Run" in text
    assert "Phase 18 unit regression suite" in text
    assert "124 passed" in text
    assert "Synthetic retrieval eval | hit@3=1.00; MRR=1.00; no-answer accuracy=1.00" in text
    assert "read-only real archive eval" in text
    assert "6/6 Phase 18 prayer/religion queries returned archive-backed evidence" in text
    assert (
        "Live hybrid embedding recall on user archive | Attempted, blocked by provider auth" in text
    )
    assert "dream_motif_eval" in text
    assert (
        "False-positive count for fabricated/non-evidence fragments | 0 in unit regression" in text
    )
    assert "real indexed archive" in text

    rows = load_evaluation_history(DOCS_PATH)
    phase18_rows = [row for row in rows if row["Task"] == "WS-18.6"]
    assert phase18_rows
    assert phase18_rows[-1]["Date"] == "2026-05-02"
    assert any(
        "scripts/eval.py against §Evaluation Dataset" in row["Eval Source"] for row in phase18_rows
    )
    assert any(
        "scripts/eval_phase18_real.py --limit 5" in row["Eval Source"] for row in phase18_rows
    )
