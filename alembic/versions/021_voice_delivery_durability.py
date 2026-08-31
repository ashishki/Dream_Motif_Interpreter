"""make voice ingress idempotent and voice reply delivery durable

Revision ID: 021_voice_delivery_durability
Revises: 020_allow_reject_graph_privacy_controls
Create Date: 2026-08-30 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021_voice_delivery_durability"
down_revision: Union[str, None] = "020_allow_reject_graph_privacy_controls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Keep the merge as separate statements so the survivor is updated before any
# duplicate row is removed.  The temporary table also freezes the survivor and
# donor choices: updating the survivor cannot change which id the DELETE keeps.
_CREATE_DUPLICATE_MERGE_TABLE_SQL = """
CREATE TEMPORARY TABLE voice_media_events_021_merge
ON COMMIT DROP
AS
WITH candidates AS (
    SELECT
        event.*,
        status IN ('delivered', 'done') AS is_terminal,
        COALESCE(
            NULLIF(BTRIM(lease_owner), '') IS NOT NULL
                AND lease_expires_at > CURRENT_TIMESTAMP,
            FALSE
        ) AS has_live_lease,
        NULLIF(BTRIM(reply_text), '') IS NOT NULL AS has_reply,
        NULLIF(BTRIM(transcript_text), '') IS NOT NULL AS has_transcript,
        NULLIF(BTRIM(local_path), '') IS NOT NULL AS has_local_path
    FROM voice_media_events AS event
), grouped AS (
    SELECT
        chat_id,
        telegram_message_id,
        (
            ARRAY_AGG(
                id
                ORDER BY
                    is_terminal DESC,
                    has_live_lease DESC,
                    CASE WHEN has_live_lease THEN lease_expires_at END DESC NULLS LAST,
                    has_reply DESC,
                    reply_chunks_delivered DESC,
                    delivery_attempt_count DESC,
                    has_transcript DESC,
                    has_local_path DESC,
                    transcription_attempt_count DESC,
                    updated_at DESC,
                    id DESC
            )
        )[1] AS survivor_id,
        BOOL_OR(is_terminal) AS has_terminal,
        (
            ARRAY_AGG(
                status
                ORDER BY
                    is_terminal DESC,
                    has_reply DESC,
                    reply_chunks_delivered DESC,
                    has_transcript DESC,
                    has_local_path DESC,
                    updated_at DESC,
                    id DESC
            )
        )[1] AS durable_status,
        (
            ARRAY_AGG(transcript_text ORDER BY updated_at DESC, id DESC)
                FILTER (WHERE has_transcript)
        )[1] AS transcript_text,
        (
            ARRAY_AGG(local_path ORDER BY updated_at DESC, id DESC)
                FILTER (WHERE has_local_path)
        )[1] AS local_path,
        (
            ARRAY_AGG(
                reply_text
                ORDER BY
                    reply_chunks_delivered DESC,
                    delivery_attempt_count DESC,
                    updated_at DESC,
                    id DESC
            ) FILTER (WHERE has_reply)
        )[1] AS reply_text,
        (
            ARRAY_AGG(
                reply_chunks_delivered
                ORDER BY
                    reply_chunks_delivered DESC,
                    delivery_attempt_count DESC,
                    updated_at DESC,
                    id DESC
            ) FILTER (WHERE has_reply)
        )[1] AS reply_chunks_delivered,
        MAX(transcription_attempt_count) AS transcription_attempt_count,
        MAX(delivery_attempt_count) AS delivery_attempt_count,
        BOOL_OR(NOT is_terminal AND next_attempt_at IS NULL) AS has_due_now,
        MIN(next_attempt_at) FILTER (WHERE next_attempt_at IS NOT NULL) AS next_attempt_at,
        (
            ARRAY_AGG(
                lease_owner
                ORDER BY lease_expires_at DESC, updated_at DESC, id DESC
            ) FILTER (WHERE has_live_lease)
        )[1] AS lease_owner,
        (
            ARRAY_AGG(
                lease_expires_at
                ORDER BY lease_expires_at DESC, updated_at DESC, id DESC
            ) FILTER (WHERE has_live_lease)
        )[1] AS lease_expires_at
    FROM candidates
    GROUP BY chat_id, telegram_message_id
    HAVING COUNT(*) > 1
)
SELECT *
FROM grouped
"""

_UPDATE_DUPLICATE_SURVIVORS_SQL = """
UPDATE voice_media_events AS survivor
SET
    transcript_text = CASE
        WHEN NULLIF(BTRIM(survivor.transcript_text), '') IS NOT NULL
            THEN survivor.transcript_text
        ELSE merged.transcript_text
    END,
    local_path = CASE
        WHEN NULLIF(BTRIM(survivor.local_path), '') IS NOT NULL
            THEN survivor.local_path
        ELSE COALESCE(merged.local_path, '')
    END,
    status = CASE
        WHEN merged.has_terminal THEN merged.durable_status
        WHEN merged.reply_text IS NOT NULL THEN 'reply_pending'
        ELSE merged.durable_status
    END,
    reply_text = CASE
        WHEN merged.has_terminal THEN NULL
        ELSE merged.reply_text
    END,
    reply_chunks_delivered = CASE
        WHEN merged.has_terminal OR merged.reply_text IS NULL THEN 0
        ELSE merged.reply_chunks_delivered
    END,
    transcription_attempt_count = merged.transcription_attempt_count,
    delivery_attempt_count = merged.delivery_attempt_count,
    next_attempt_at = CASE
        WHEN merged.has_terminal THEN NULL
        -- NULL is the worker's "due now" value, not missing data.  A future
        -- retry from another duplicate must not postpone immediately-due work.
        WHEN merged.has_due_now THEN NULL
        ELSE merged.next_attempt_at
    END,
    lease_owner = CASE
        WHEN merged.has_terminal THEN NULL
        ELSE merged.lease_owner
    END,
    lease_expires_at = CASE
        WHEN merged.has_terminal THEN NULL
        ELSE merged.lease_expires_at
    END
FROM voice_media_events_021_merge AS merged
WHERE survivor.id = merged.survivor_id
"""

_DELETE_MERGED_DUPLICATES_SQL = """
DELETE FROM voice_media_events AS duplicate
USING voice_media_events_021_merge AS merged
WHERE duplicate.chat_id = merged.chat_id
  AND duplicate.telegram_message_id = merged.telegram_message_id
  AND duplicate.id <> merged.survivor_id
"""

_DROP_DUPLICATE_MERGE_TABLE_SQL = "DROP TABLE voice_media_events_021_merge"

_UPGRADE_LOCK_SQL = "LOCK TABLE voice_media_events IN SHARE ROW EXCLUSIVE MODE"
_DOWNGRADE_LOCK_SQL = "LOCK TABLE voice_media_events IN SHARE ROW EXCLUSIVE MODE"

_DOWNGRADE_DURABILITY_GUARD_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM voice_media_events
        WHERE status NOT IN ('delivered', 'done', 'failed')
           OR reply_text IS NOT NULL
           OR reply_chunks_delivered <> 0
           OR next_attempt_at IS NOT NULL
           OR lease_owner IS NOT NULL
           OR lease_expires_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot downgrade 021_voice_delivery_durability while durable voice work is unfinished';
    END IF;
END
$$
"""


def upgrade() -> None:
    # Serialize the schema extension and duplicate snapshot with legacy voice
    # writers.  The lock is transaction-scoped, so a writer released after the
    # migration observes the uniqueness/outbox contract atomically.
    op.execute(_UPGRADE_LOCK_SQL)
    op.add_column("voice_media_events", sa.Column("reply_text", sa.Text(), nullable=True))
    op.add_column(
        "voice_media_events",
        sa.Column(
            "transcription_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "voice_media_events",
        sa.Column(
            "reply_chunks_delivered",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "voice_media_events",
        sa.Column(
            "delivery_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "voice_media_events",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "voice_media_events",
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "voice_media_events",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Older handlers allowed duplicate Telegram deliveries. Merge complementary
    # durable state into one deterministic survivor before deleting anything.
    # Reply text/cursor and lease owner/expiry are deliberately selected as
    # pairs; mixing values from different attempts would make recovery unsafe.
    op.execute(_CREATE_DUPLICATE_MERGE_TABLE_SQL)
    op.execute(_UPDATE_DUPLICATE_SURVIVORS_SQL)
    op.execute(_DELETE_MERGED_DUPLICATES_SQL)
    op.execute(_DROP_DUPLICATE_MERGE_TABLE_SQL)
    op.create_unique_constraint(
        "uq_voice_media_events_chat_message",
        "voice_media_events",
        ["chat_id", "telegram_message_id"],
    )
    op.create_index(
        "ix_voice_media_events_recovery",
        "voice_media_events",
        ["status", "next_attempt_at", "lease_expires_at"],
    )


def downgrade() -> None:
    # The legacy schema has no reply outbox, retry clock, or lease fencing.
    # Refuse to erase any unfinished work. The new ``delivered`` terminal state
    # maps to the legacy ``done`` spelling; historical ``done`` rows are left as
    # legacy state and are not upgraded into stronger delivery evidence here.
    # The transaction-scoped lock closes the guard/DDL race with active workers.
    op.execute(_DOWNGRADE_LOCK_SQL)
    op.execute(_DOWNGRADE_DURABILITY_GUARD_SQL)
    op.execute("UPDATE voice_media_events SET status = 'done' WHERE status = 'delivered'")
    op.drop_index("ix_voice_media_events_recovery", table_name="voice_media_events")
    op.drop_constraint(
        "uq_voice_media_events_chat_message",
        "voice_media_events",
        type_="unique",
    )
    op.drop_column("voice_media_events", "lease_expires_at")
    op.drop_column("voice_media_events", "lease_owner")
    op.drop_column("voice_media_events", "next_attempt_at")
    op.drop_column("voice_media_events", "delivery_attempt_count")
    op.drop_column("voice_media_events", "reply_chunks_delivered")
    op.drop_column("voice_media_events", "transcription_attempt_count")
    op.drop_column("voice_media_events", "reply_text")
