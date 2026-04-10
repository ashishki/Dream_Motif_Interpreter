#!/usr/bin/env bash
# PreToolUse hook: guard_files.sh
# Blocks runtime writes to immutable playbook files.
#
# Triggered by Claude Code before Write, Edit, or MultiEdit tool execution.
#
# Configuration:
#   PLAYBOOK_PROTECTED_FILES  colon-separated list of protected paths (relative to
#                             project root). Override to customise for your project.
#                             Default covers the three immutable files.
#
# Exit codes:
#   0  Allow the write to proceed
#   2  Block the write; stderr message is fed back to Claude as the reason

set -euo pipefail

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null || echo "")

# Nothing to check if no file_path
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Protected paths (relative to project root).
# Extend via PLAYBOOK_PROTECTED_FILES env var (colon-separated).
DEFAULT_PROTECTED="docs/IMPLEMENTATION_CONTRACT.md:prompts/ORCHESTRATOR.md:docs/audit/AUDIT_INDEX.md"
PROTECTED="${PLAYBOOK_PROTECTED_FILES:-$DEFAULT_PROTECTED}"

IFS=':' read -ra PATHS <<< "$PROTECTED"
for PROTECTED_PATH in "${PATHS[@]}"; do
  # Match exact path or absolute path ending with /protected_path
  if [[ "$FILE_PATH" == "$PROTECTED_PATH" ]] || [[ "$FILE_PATH" == *"/${PROTECTED_PATH}" ]]; then
    echo "BLOCKED: '${PROTECTED_PATH}' is immutable at runtime." >&2
    echo "To modify this file, file an ADR in docs/adr/ first (see IMPLEMENTATION_CONTRACT.md §Forbidden Actions)." >&2
    echo "(Override: set PLAYBOOK_PROTECTED_FILES env var with colon-separated paths.)" >&2
    exit 2
  fi
done

exit 0
