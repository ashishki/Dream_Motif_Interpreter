#!/usr/bin/env bash
# Stop hook: save_checkpoint.sh
# Writes a lightweight Orchestrator state snapshot when the Claude Code session ends.
#
# Always exits 0 — must never block session stop.
#
# Configuration:
#   PLAYBOOK_CHECKPOINT_FILE   path for the checkpoint (default: /tmp/orchestrator_checkpoint.md)
#   PLAYBOOK_CODEX_PROMPT      path to CODEX_PROMPT.md (default: docs/CODEX_PROMPT.md)

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
CHECKPOINT_FILE="${PLAYBOOK_CHECKPOINT_FILE:-/tmp/orchestrator_checkpoint.md}"
CODEX_PROMPT="${PLAYBOOK_CODEX_PROMPT:-docs/CODEX_PROMPT.md}"

ACTIVE_TASK="unknown"
FIX_COUNT=0

if [ -f "$CODEX_PROMPT" ]; then
  # First in-progress task [~], or last completed ✅
  ACTIVE_TASK=$(grep -m1 '\[~\]' "$CODEX_PROMPT" 2>/dev/null || \
                grep '✅' "$CODEX_PROMPT" 2>/dev/null | tail -1 || \
                echo "none found")
  FIX_COUNT=$(grep -c 'FIX-[0-9]' "$CODEX_PROMPT" 2>/dev/null || echo "0")
fi

cat > "$CHECKPOINT_FILE" <<EOF
# Orchestrator Checkpoint
Timestamp:       $TIMESTAMP
Source file:     $CODEX_PROMPT
Active task:     $ACTIVE_TASK
Fix Queue items: $FIX_COUNT
Session ended:   normal Stop event

Resume: re-paste prompts/ORCHESTRATOR.md as system prompt.
        Orchestrator re-reads $CODEX_PROMPT automatically.
        No manual state restoration needed.
EOF

# Optional: send a brief checkpoint notification when session ends.
# Activated only when NOTIFICATION_TOKEN and NOTIFICATION_TARGET are set
# AND SILENT is not 1 (set SILENT=1 for automated / cron-driven sessions).
if [ "${SILENT:-0}" != "1" ] \
   && [ -n "${NOTIFICATION_TOKEN:-}" ] \
   && [ -n "${NOTIFICATION_TARGET:-}" ]; then
  NOTIFY_TEXT="Session ended ${TIMESTAMP}. Active: ${ACTIVE_TASK}. Fix Queue: ${FIX_COUNT}. Resume: paste ORCHESTRATOR.md."
  curl -s -X POST "https://api.telegram.org/bot${NOTIFICATION_TOKEN}/sendMessage" \
    -d chat_id="${NOTIFICATION_TARGET}" \
    --data-urlencode "text=${NOTIFY_TEXT}" > /dev/null 2>&1 || true
fi

exit 0
