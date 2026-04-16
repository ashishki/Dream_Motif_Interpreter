from __future__ import annotations

from typing import Any


class MotifGrounder:
    """Verify imagery fragments against source dream text character offsets.

    This is a pure deterministic verification step — no LLM calls are made.
    Each fragment's ``text`` is compared to the substring of ``dream_text``
    delimited by ``start_offset`` and ``end_offset``.  Fragments that match
    are returned with ``verified=True``; those that do not are returned with
    ``verified=False``.
    """

    def ground(
        self,
        dream_text: str,
        fragments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Verify a list of imagery fragments against *dream_text*.

        Args:
            dream_text: The original source dream text.
            fragments: A list of fragment dicts, each containing:
                ``text`` (str), ``start_offset`` (int), ``end_offset`` (int).

        Returns:
            A new list where every element is a copy of the input fragment
            dict extended with a ``verified`` key (bool).
        """
        return [self._verify_fragment(dream_text, fragment) for fragment in fragments]

    def _verify_fragment(
        self,
        dream_text: str,
        fragment: dict[str, Any],
    ) -> dict[str, Any]:
        text = str(fragment["text"])
        start_offset = int(fragment["start_offset"])
        end_offset = int(fragment["end_offset"])

        verified = self._check_offsets(
            dream_text=dream_text,
            text=text,
            start_offset=start_offset,
            end_offset=end_offset,
        )
        return {
            "text": text,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "verified": verified,
        }

    def _check_offsets(
        self,
        *,
        dream_text: str,
        text: str,
        start_offset: int,
        end_offset: int,
    ) -> bool:
        if start_offset < 0 or end_offset < start_offset or end_offset > len(dream_text):
            return False

        return text == dream_text[start_offset:end_offset]
