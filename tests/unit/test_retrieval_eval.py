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
