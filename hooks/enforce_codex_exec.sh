#!/usr/bin/env bash
# PreToolUse hook: enforce_codex_exec.sh
# Blocks direct Claude Write/Edit/MultiEdit operations on application code paths.
# Code changes must go through `codex exec` via Bash so the implementation agent
# remains the only writer of application code.
#
# Configuration:
#   PLAYBOOK_CODE_PATH_PREFIXES  colon-separated relative path prefixes treated as
#                                application code. Default: app/:src/:lib/:tests/
#   PLAYBOOK_CODEX_ENFORCEMENT   set to "off" to disable this guard

set -euo pipefail

if [ "${PLAYBOOK_CODEX_ENFORCEMENT:-on}" = "off" ]; then
  exit 0
fi

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null || echo "")

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

PREFIXES="${PLAYBOOK_CODE_PATH_PREFIXES:-app/:src/:lib/:tests/}"
IFS=':' read -ra PATHS <<< "$PREFIXES"

for PREFIX in "${PATHS[@]}"; do
  if [ -z "$PREFIX" ]; then
    continue
  fi

  if [[ "$FILE_PATH" == "$PREFIX"* ]] || [[ "$FILE_PATH" == *"/${PREFIX}"* ]]; then
    echo "BLOCKED: direct Claude edits to application code are disabled for '${FILE_PATH}'." >&2
    echo "Use Bash -> codex exec, pass the prompt file, and wait for IMPLEMENTATION_RESULT." >&2
    echo "This repository reserves application code writing for Codex, not Claude subagents." >&2
    exit 2
  fi
done

exit 0
