from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.eval import EVAL_DATE, EVAL_SOURCE, run_evaluation
from app.retrieval.query import InsufficientEvidence

DOCS_PATH = Path(__file__).resolve().parents[2] / "docs" / "retrieval_eval.md"
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "seed_dreams.json"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required")
@pytest.mark.asyncio
async def test_eval_script_writes_baseline_metrics() -> None:
    original = DOCS_PATH.read_text(encoding="utf-8")
    try:
        metrics, _ = await run_evaluation(
            docs_path=DOCS_PATH,
            fixture_path=FIXTURE_PATH,
            write_markdown=True,
        )
        updated = DOCS_PATH.read_text(encoding="utf-8")
    finally:
        DOCS_PATH.write_text(original, encoding="utf-8")

    assert metrics.hit_at_3 >= 0.70
    assert "| hit@3 |" in updated
    assert f"| hit@3 | {metrics.hit_at_3:.2f} |" in updated
    assert f"| MRR | {metrics.mrr:.2f} |" in updated
    assert f"| No-answer accuracy | {metrics.no_answer_accuracy:.2f} |" in updated
    assert EVAL_DATE in updated
    assert EVAL_SOURCE in updated


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required")
@pytest.mark.asyncio
async def test_no_answer_queries_return_insufficient_evidence() -> None:
    metrics, outcomes = await run_evaluation(
        docs_path=DOCS_PATH,
        fixture_path=FIXTURE_PATH,
        write_markdown=False,
    )

    no_answer_outcomes = [
        outcome for outcome in outcomes if outcome.query.query_type == "no-answer"
    ]

    assert metrics.no_answer_accuracy == 1.0
    assert no_answer_outcomes
    assert all(isinstance(outcome.result, InsufficientEvidence) for outcome in no_answer_outcomes)
