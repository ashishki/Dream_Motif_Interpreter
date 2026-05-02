from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from uuid import uuid4

from app.retrieval.query import EvidenceBlock, FragmentMatch, InsufficientEvidence
from scripts import eval_phase18_real


def test_real_eval_script_has_no_schema_reset_or_migration_calls() -> None:
    source_path = Path(__file__).resolve().parents[2] / "scripts/eval_phase18_real.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    forbidden_names = {"command", "_reset_public_schema", "RagIngestionService"}
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"upgrade", "execute"}


def test_summarize_result_handles_insufficient_evidence() -> None:
    result = eval_phase18_real._summarize_result(
        query="молитва",
        result=InsufficientEvidence(reason="No evidence met retrieval threshold"),
        limit=5,
    )

    assert result == eval_phase18_real.RealEvalResult(
        query="молитва",
        status="insufficient_evidence",
        result_count=0,
        evidence_count=0,
        top_titles=(),
    )


def test_summarize_result_counts_evidence_from_fragments() -> None:
    dream_id = uuid4()

    result = eval_phase18_real._summarize_result(
        query="церковь",
        result=[
            EvidenceBlock(
                dream_id=dream_id,
                date=date(2026, 5, 2),
                title="Сон о храме",
                chunk_text="Я вошел в храм.",
                relevance_score=0.8,
                matched_fragments=[
                    FragmentMatch(text="храм", match_type="semantic", char_offset=9)
                ],
            )
        ],
        limit=5,
    )

    assert result == eval_phase18_real.RealEvalResult(
        query="церковь",
        status="ok",
        result_count=1,
        evidence_count=1,
        top_titles=("Сон о храме",),
    )


def test_auto_mode_uses_fts_for_placeholder_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-set-real-key")

    assert eval_phase18_real._resolve_eval_mode("auto") == "fts"
    assert eval_phase18_real._resolve_eval_mode("live") == "live"


def test_matching_fragments_prefers_query_terms() -> None:
    assert eval_phase18_real._matching_fragments("Мы вошли в церковь вечером", "церковь храм") == [
        "церковь"
    ]


def test_fts_probe_terms_splits_long_probes() -> None:
    assert eval_phase18_real._fts_probe_terms(["религиозные сюжеты церковь храм церковь"]) == (
        "церковь",
        "храм",
    )
