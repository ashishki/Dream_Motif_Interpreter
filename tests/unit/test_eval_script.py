from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

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
    content = eval_script._append_evaluation_history(
        content,
        metrics=metrics,
        task_id="T12",
        run_date="2026-04-13",
    )
    content = eval_script._append_evaluation_history(
        content,
        metrics=metrics,
        task_id="T15",
        run_date="2026-05-02",
    )
    docs_path.write_text(content, encoding="utf-8")

    history = eval_script.load_evaluation_history(docs_path)

    assert [row["Task"] for row in history] == ["T12", "T15"]
    assert [row["Date"] for row in history] == ["2026-04-13", "2026-05-02"]


def test_main_passes_no_write_markdown_flag_to_run_evaluation() -> None:
    args = argparse.Namespace(task_id="CI", no_write_markdown=True, confirm_reset=True)

    with (
        patch("scripts.eval.argparse.ArgumentParser.parse_args", return_value=args),
        patch("scripts.eval.run_evaluation", new=AsyncMock()) as mock_run,
    ):
        eval_script.main()

    mock_run.assert_awaited_once_with(
        task_id="CI",
        write_markdown=False,
        confirm_reset=True,
    )


def test_eval_database_url_never_falls_back_to_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/production",
    )

    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL is required"):
        eval_script._validated_eval_database_url(confirm_reset=True)


def test_eval_database_url_rejects_non_eval_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/dream_motif",
    )

    with pytest.raises(RuntimeError, match="database name must end"):
        eval_script._validated_eval_database_url(confirm_reset=True)


def test_eval_database_url_requires_explicit_reset_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/dream_motif_eval",
    )

    with pytest.raises(RuntimeError, match="pass --confirm-reset"):
        eval_script._validated_eval_database_url(confirm_reset=False)


def test_eval_database_url_rejects_non_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/dream_motif_eval",
    )
    monkeypatch.setenv("ENV", "production")

    with pytest.raises(RuntimeError, match="unless ENV is"):
        eval_script._validated_eval_database_url(confirm_reset=True)


@pytest.mark.parametrize("database_name", ["dream_motif_test", "dream-motif-eval"])
def test_eval_database_url_accepts_explicit_test_or_eval_database(
    monkeypatch: pytest.MonkeyPatch,
    database_name: str,
) -> None:
    database_url = f"postgresql+asyncpg://user:pass@localhost:5432/{database_name}"
    monkeypatch.setenv("TEST_DATABASE_URL", database_url)

    assert eval_script._validated_eval_database_url(confirm_reset=True) == database_url
