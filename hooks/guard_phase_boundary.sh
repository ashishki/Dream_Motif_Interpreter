#!/usr/bin/env bash
# PreToolUse hook: guard_phase_boundary.sh
# Blocks phase-boundary updates in CODEX_PROMPT.md unless the completed phase
# already has a review/archive entry in docs/audit/AUDIT_INDEX.md.
#
# Configuration:
#   PLAYBOOK_CODEX_PROMPT_PATH  relative path to CODEX_PROMPT.md
#   PLAYBOOK_AUDIT_INDEX_PATH   relative path to AUDIT_INDEX.md
#   PLAYBOOK_TASKS_PATH         relative path to tasks.md

set -euo pipefail

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null || echo "")

CODEX_PROMPT_PATH="${PLAYBOOK_CODEX_PROMPT_PATH:-docs/CODEX_PROMPT.md}"
AUDIT_INDEX_PATH="${PLAYBOOK_AUDIT_INDEX_PATH:-docs/audit/AUDIT_INDEX.md}"
TASKS_PATH="${PLAYBOOK_TASKS_PATH:-docs/tasks.md}"

if [ "$FILE_PATH" != "$CODEX_PROMPT_PATH" ] && [[ "$FILE_PATH" != *"/${CODEX_PROMPT_PATH}" ]]; then
  exit 0
fi

if [ ! -f "$CODEX_PROMPT_PATH" ] || [ ! -f "$TASKS_PATH" ] || [ ! -f "$AUDIT_INDEX_PATH" ]; then
  exit 0
fi

python3 - "$INPUT" "$CODEX_PROMPT_PATH" "$TASKS_PATH" "$AUDIT_INDEX_PATH" <<'PY'
import json
import re
import sys
from pathlib import Path

raw_input, codex_prompt_path, tasks_path, audit_index_path = sys.argv[1:]

payload = json.loads(raw_input)
tool_name = payload.get("tool_name", "")
tool_input = payload.get("tool_input", {})

current_text = Path(codex_prompt_path).read_text()
tasks_text = Path(tasks_path).read_text()
audit_text = Path(audit_index_path).read_text()


def extract_phase(text: str):
    patterns = [
        r"^- \*\*Phase:\*\* (\d+)\s*$",
        r"^Phase:\s*(\d+)\s*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return int(match.group(1))
    return None


def extract_next_task(text: str):
    patterns = [
        r"^\*\*(T\d+):",
        r"^(T\d+):",
    ]
    in_next_task = False
    for line in text.splitlines():
        if line.strip() == "## Next Task":
            in_next_task = True
            continue
        if in_next_task and line.startswith("## "):
            break
        if not in_next_task:
            continue
        stripped = line.strip()
        for pattern in patterns:
            match = re.match(pattern, stripped)
            if match:
                return match.group(1)
    return None


def parse_task_phases(text: str):
    task_phases = {}
    current_task = None
    for line in text.splitlines():
        task_match = re.match(r"^##\s+(T\d+):", line.strip())
        if task_match:
            current_task = task_match.group(1)
            continue
        phase_match = re.match(r"^Phase:\s*(\d+)\s*$", line.strip())
        if current_task and phase_match:
            task_phases[current_task] = int(phase_match.group(1))
    return task_phases


def apply_edit_like_claude(text: str, payload: dict):
    name = payload.get("tool_name", "")
    t_input = payload.get("tool_input", {})
    if name == "Write":
        return t_input.get("content", text)
    if name == "Edit":
        old = t_input.get("old_string", "")
        new = t_input.get("new_string", "")
        if old and old in text:
            return text.replace(old, new, 1)
        return text
    if name == "MultiEdit":
        edits = t_input.get("edits", [])
        updated = text
        for edit in edits:
            old = edit.get("old_string", "")
            new = edit.get("new_string", "")
            if old and old in updated:
                updated = updated.replace(old, new, 1)
        return updated
    return text


projected_text = apply_edit_like_claude(current_text, payload)
current_phase = extract_phase(current_text)
projected_phase = extract_phase(projected_text)
task_phases = parse_task_phases(tasks_text)
current_task = extract_next_task(current_text)
projected_task = extract_next_task(projected_text)
current_task_phase = task_phases.get(current_task)
projected_task_phase = task_phases.get(projected_task)

phase_boundary = False
completed_phase = None

if current_phase is not None and projected_phase is not None and projected_phase > current_phase:
    phase_boundary = True
    completed_phase = current_phase
elif (
    current_task_phase is not None
    and projected_task_phase is not None
    and projected_task_phase > current_task_phase
):
    phase_boundary = True
    completed_phase = current_task_phase

if not phase_boundary or completed_phase is None:
    sys.exit(0)

phase_marker = f"| Phase {completed_phase} |"
phase_review_marker = f"PHASE{completed_phase}_REVIEW"
phase_review_marker_alt = f"PHASE_{completed_phase}_REVIEW"

has_archive = (
    phase_marker in audit_text
    and (
        phase_review_marker in audit_text
        or phase_review_marker_alt in audit_text
    )
)

if has_archive:
    sys.exit(0)

print(
    "BLOCKED: phase boundary update in docs/CODEX_PROMPT.md requires archived deep review for "
    f"Phase {completed_phase}.",
    file=sys.stderr,
)
print(
    f"Missing evidence in {audit_index_path}: expected an archive row for Phase {completed_phase} "
    "before advancing the phase or next-task phase.",
    file=sys.stderr,
)
print(
    "Run deep review, archive REVIEW_REPORT, update AUDIT_INDEX, then advance CODEX_PROMPT.",
    file=sys.stderr,
)
sys.exit(2)
PY
