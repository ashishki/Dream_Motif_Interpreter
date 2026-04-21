from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts import eval as eval_script


def test_eval_history_appends(tmp_path: Path) -> None:
    metrics = eval_script.EvaluationMetrics(
        hit_at_3=1.0,
        hit_at_5=1.0,
        mrr=1.0,
        citation_precision=0.75,
        no_answer_accuracy=1.0,
        median_retrieval_latency_ms=12,
        p95_retrieval_latency_ms=18,
    )
    docs_path = tmp_path / "retrieval_eval.md"
    docs_path.write_text(
        (
            "# Eval\n\n"
            "## Evaluation History\n\n"
            "| Date | Task | Corpus Version | Eval Source | hit@3 | MRR | No-answer acc. | Faithfulness | Completeness | Note |\n"
            "|------|------|----------------|-------------|-------|-----|----------------|--------------|--------------|------|\n"
        ),
        encoding="utf-8",
    )

    content = docs_path.read_text(encoding="utf-8")
    content = eval_script._append_evaluation_history(content, metrics=metrics, task_id="T12")
    content = eval_script._append_evaluation_history(content, metrics=metrics, task_id="T15")
    docs_path.write_text(content, encoding="utf-8")

    history = eval_script.load_evaluation_history(docs_path)

    assert [row["Task"] for row in history] == ["T12", "T15"]


def test_main_passes_no_write_markdown_flag_to_run_evaluation() -> None:
    args = argparse.Namespace(task_id="CI", no_write_markdown=True)

    with (
        patch("scripts.eval.argparse.ArgumentParser.parse_args", return_value=args),
        patch("scripts.eval.run_evaluation", new=AsyncMock()) as mock_run,
    ):
        eval_script.main()

    mock_run.assert_awaited_once_with(task_id="CI", write_markdown=False)
