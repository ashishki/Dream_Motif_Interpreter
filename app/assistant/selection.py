"""Read-only conversation selection commands and evidence-bound display identity.

A selection is operational state, not an archive mutation. Never derive an
ordinal from a candidate count, and never treat a date shared by several dreams
as an unambiguous identity. This module makes no provider or database calls.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SelectionCommand:
    action: Literal["show", "open", "remove", "keep"]
    indices: tuple[int, ...] = ()


_ORDINALS = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четверт": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
}


def parse_selection_command(text: str) -> SelectionCommand | None:
    value = re.sub(r"\s+", " ", text.casefold().replace("ё", "е")).strip(" .!?\n")
    value = re.sub(r"^(?:а |тогда |пожалуйста,? )", "", value)
    if value in {"покажи подборку", "покажи оставшиеся", "что сейчас в подборке", "продолжим"}:
        return SelectionCommand("show")
    patterns = (
        ("remove", r"(?:убери|исключи) (.+?)(?: из (?:этой )?подборки)?"),
        ("remove", r"(.+?) не подходит"),
        ("keep", r"оставь (?:только )?(.+?)(?: в подборке)?"),
        ("open", r"(?:покажи|открой|прочитай) (.+?)(?: (?:целиком|полностью|полный текст))?"),
    )
    for action, pattern in patterns:
        match = re.fullmatch(pattern, value)
        if not match:
            continue
        target = re.sub(r"\b(?:сон|сна|сны|снов|номер|номера)\b", "", match.group(1)).strip()
        parts = re.split(r"\s*(?:,|\bи\b)\s*", target)
        indices = []
        for part in parts:
            part = part.strip()
            if re.fullmatch(r"[1-9]\d{0,2}", part):
                indices.append(int(part))
                continue
            number = next(
                (n for stem, n in _ORDINALS.items() if re.fullmatch(stem + r"[а-я]*", part)), None
            )
            if number is None:
                break
            indices.append(number)
        else:
            if indices and (action != "open" or len(indices) == 1):
                return SelectionCommand(action, tuple(dict.fromkeys(indices)))
    return None


def is_selection_analysis(text: str) -> bool:
    value = text.casefold().replace("ё", "е")
    return bool(
        re.search(
            r"(?:что (?:у них |в них |у этих снов )?общего|сравни (?:их|эти|оставш|подбор)|"
            r"что (?:там|в них|в этих снах) повторяется)",
            value,
        )
    )


def display_date(value: str | None) -> str:
    value = str(value or "")
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        return f"{match[3]}.{match[2]}.{match[1][-2:]}"
    return value if value and value != "unknown" else "Без даты"


def selection_text(refs: list[Any], *, heading: str = "В текущей подборке:") -> str:
    if not refs:
        return "Подборка пуста. Назовите образ или тему — найду записи в архиве."
    lines = [heading, ""]
    for index, ref in enumerate(refs, start=1):
        lines.append(
            f"{index}. {display_date(getattr(ref, 'date', None))} — {getattr(ref, 'title', '') or 'без названия'}"
        )
    lines.append(
        "\nМожно открыть сон по номеру, сравнить подборку или убрать неподходящий результат."
    )
    return "\n".join(lines)


def visible_references(text: str, refs: list[Any]) -> list[Any]:
    """Return identifiable references in *display order*, never candidate order.

    Named entries require their title. Repeated titles also require a unique
    date. Unnamed entries require a unique date. Ambiguity yields no mapping.
    New deterministic responses should supply their explicit references instead.
    """
    if not isinstance(refs, list):
        return []
    normalized = _normalize(text)
    candidates = []
    identities = set()
    for ref in refs:
        try:
            identity = str(uuid.UUID(str(getattr(ref, "dream_id", ""))))
        except (ValueError, TypeError):
            continue
        if identity not in identities:
            identities.add(identity)
            candidates.append(ref)
    hits = []
    lines = normalized.splitlines() or [normalized]
    for ref in candidates:
        identity = str(getattr(ref, "dream_id", ""))
        title = _normalize(str(getattr(ref, "title", "") or ""))
        date = display_date(getattr(ref, "date", None))
        named = title not in {"", "без названия"}
        twins = [
            other
            for other in candidates
            if _normalize(str(getattr(other, "title", "") or "")) == title
        ]
        position = None
        if identity in normalized:
            position = normalized.index(identity)
        elif named and len(twins) == 1:
            positions = _unambiguous_title_positions(normalized, title, candidates)
            if positions:
                position = positions[0]
        else:
            same_day = [
                other
                for other in (twins if named else candidates)
                if display_date(getattr(other, "date", None)) == date
            ]
            if date != "Без даты" and len(same_day) == 1:
                variants = {date, str(getattr(ref, "date", ""))}
                offset = 0
                for line in lines:
                    if (not named or title in line) and any(v and v in line for v in variants):
                        position = offset + (line.index(title) if named else 0)
                        break
                    offset += len(line) + 1
        if position is not None:
            hits.append((position, ref))
    return [ref for _, ref in sorted(hits, key=lambda pair: pair[0])]


def _normalize(value: str) -> str:
    return "\n".join(re.sub(r"[ \t]+", " ", line.casefold()).strip() for line in value.splitlines())


def _unambiguous_title_positions(text: str, title: str, refs: list[Any]) -> list[int]:
    """A short title inside a longer candidate title is not an extra source."""
    positions = []
    for match in re.finditer(r"(?<!\w)" + re.escape(title) + r"(?!\w)", text):
        enclosed = False
        for other in refs:
            longer = _normalize(str(getattr(other, "title", "") or ""))
            if len(longer) <= len(title) or title not in longer:
                continue
            for span in re.finditer(re.escape(longer), text):
                if span.start() <= match.start() and span.end() >= match.end():
                    enclosed = True
        if not enclosed:
            positions.append(match.start())
    return positions


def numbered_references_are_consistent(text: str, refs: list[Any]) -> bool:
    """Whether displayed numeric labels exactly match the proposed selection."""
    matched = []
    for line in text.splitlines():
        number = re.match(r"^\s*(\d+)[.)]\s+", line)
        if not number:
            continue
        visible = visible_references(line, refs)
        if visible:
            if len(visible) != 1:
                return False
            matched.append((int(number[1]), str(visible[0].dream_id)))
    return matched == [(i, str(ref.dream_id)) for i, ref in enumerate(refs, start=1)]
