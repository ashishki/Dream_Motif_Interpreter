from __future__ import annotations

from app.services.motif_grounder import MotifGrounder

_DREAM_TEXT = (
    "I stood at the edge of a crumbling staircase. "
    "A locked door waited at the top, and my feet kept sinking into the floor."
)


def _make_fragment(text: str, start: int, end: int) -> dict:
    return {"text": text, "start_offset": start, "end_offset": end}


def _fragment_from_source(dream_text: str, substring: str) -> dict:
    start = dream_text.index(substring)
    end = start + len(substring)
    return _make_fragment(substring, start, end)


class TestMotifGrounderVerifiedFragments:
    def test_single_valid_fragment_returns_verified_true(self) -> None:
        grounder = MotifGrounder()
        fragment = _fragment_from_source(_DREAM_TEXT, "crumbling staircase")

        results = grounder.ground(_DREAM_TEXT, [fragment])

        assert len(results) == 1
        assert results[0]["verified"] is True

    def test_multiple_valid_fragments_all_verified(self) -> None:
        grounder = MotifGrounder()
        fragments = [
            _fragment_from_source(_DREAM_TEXT, "crumbling staircase"),
            _fragment_from_source(_DREAM_TEXT, "locked door"),
            _fragment_from_source(_DREAM_TEXT, "feet kept sinking"),
        ]

        results = grounder.ground(_DREAM_TEXT, fragments)

        assert len(results) == 3
        assert all(r["verified"] is True for r in results)

    def test_text_mismatch_returns_verified_false(self) -> None:
        grounder = MotifGrounder()
        correct_start = _DREAM_TEXT.index("crumbling staircase")
        fragment = _make_fragment(
            "collapsing staircase",
            correct_start,
            correct_start + len("crumbling staircase"),
        )

        results = grounder.ground(_DREAM_TEXT, [fragment])

        assert results[0]["verified"] is False

    def test_offset_beyond_text_length_returns_verified_false(self) -> None:
        grounder = MotifGrounder()
        beyond = len(_DREAM_TEXT) + 10
        fragment = _make_fragment("anything", beyond, beyond + 8)

        results = grounder.ground(_DREAM_TEXT, [fragment])

        assert results[0]["verified"] is False

    def test_negative_start_offset_returns_verified_false(self) -> None:
        grounder = MotifGrounder()
        fragment = _make_fragment("crumbling staircase", -5, 14)

        results = grounder.ground(_DREAM_TEXT, [fragment])

        assert results[0]["verified"] is False

    def test_end_before_start_returns_verified_false(self) -> None:
        grounder = MotifGrounder()
        start = _DREAM_TEXT.index("crumbling staircase")
        fragment = _make_fragment("crumbling staircase", start + 5, start)

        results = grounder.ground(_DREAM_TEXT, [fragment])

        assert results[0]["verified"] is False

    def test_mixed_fragments_verified_flags_differ(self) -> None:
        grounder = MotifGrounder()
        valid = _fragment_from_source(_DREAM_TEXT, "locked door")
        invalid_start = _DREAM_TEXT.index("locked door")
        invalid = _make_fragment(
            "open door",
            invalid_start,
            invalid_start + len("locked door"),
        )

        results = grounder.ground(_DREAM_TEXT, [valid, invalid])

        assert results[0]["verified"] is True
        assert results[1]["verified"] is False

    def test_empty_fragment_list_returns_empty_list(self) -> None:
        grounder = MotifGrounder()
        results = grounder.ground(_DREAM_TEXT, [])
        assert results == []

    def test_output_contains_required_keys(self) -> None:
        grounder = MotifGrounder()
        fragment = _fragment_from_source(_DREAM_TEXT, "crumbling staircase")

        results = grounder.ground(_DREAM_TEXT, [fragment])

        assert set(results[0].keys()) == {"text", "start_offset", "end_offset", "verified"}

    def test_source_text_preserved_in_output(self) -> None:
        grounder = MotifGrounder()
        substring = "crumbling staircase"
        fragment = _fragment_from_source(_DREAM_TEXT, substring)

        results = grounder.ground(_DREAM_TEXT, [fragment])

        assert results[0]["text"] == substring
        assert results[0]["start_offset"] == fragment["start_offset"]
        assert results[0]["end_offset"] == fragment["end_offset"]

    def test_zero_length_slice_with_empty_text_verified_true(self) -> None:
        grounder = MotifGrounder()
        fragment = _make_fragment("", 0, 0)

        results = grounder.ground(_DREAM_TEXT, [fragment])

        assert results[0]["verified"] is True

    def test_full_dream_text_as_single_fragment(self) -> None:
        grounder = MotifGrounder()
        fragment = _make_fragment(_DREAM_TEXT, 0, len(_DREAM_TEXT))

        results = grounder.ground(_DREAM_TEXT, [fragment])

        assert results[0]["verified"] is True


class TestMotifGrounderIndependence:
    def test_does_not_import_from_llm_grounder(self) -> None:
        """MotifGrounder must not import from app.llm.grounder (AC-4 independence check)."""
        import importlib
        import sys

        module_name = "app.services.motif_grounder"
        if module_name in sys.modules:
            mod = sys.modules[module_name]
        else:
            mod = importlib.import_module(module_name)

        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as fh:
            source = fh.read()

        assert "app.llm.grounder" not in source, (
            "MotifGrounder must not import from app.llm.grounder"
        )

    def test_no_llm_calls_required(self) -> None:
        """MotifGrounder.ground() must be callable without any LLM client (AC-5)."""
        grounder = MotifGrounder()
        fragment = _fragment_from_source(_DREAM_TEXT, "locked door")
        results = grounder.ground(_DREAM_TEXT, [fragment])
        assert results[0]["verified"] is True
