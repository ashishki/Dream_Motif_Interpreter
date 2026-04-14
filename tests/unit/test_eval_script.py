from __future__ import annotations

from pathlib import Path

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
