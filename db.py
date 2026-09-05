"""
Step 3 of 5 — Postgres.

The HTTP layer does not speak SQL. It calls these helpers.

One UUID is shared by:
  - the file  /audio/<id>.wav
  - the row   audio_jobs.id

The server only inserts `queued`. The worker (worker.py) is what moves
status forward after the Mac Studio returns text.

Next: main.py (HTTP) then worker.py (the batch drain).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from config import DATABASE_URL

_LA = ZoneInfo("America/Los_Angeles")

JOB_SELECT = """
    id, original_name, path, status, transcript, error,
    summary, summary_status, summary_error, summary_model,
    summary_prompt_tokens, summary_output_tokens, summary_total_tokens,
    agent_status, agent_note,
    created_at, updated_at
"""


def connect() -> psycopg.Connection:
    """Open a connection. Caller must close it (use `with connect() as conn`)."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set — copy .env.example to .env")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def insert_job(audio_id: str, original_name: str, path: str) -> dict:
    """
    Record a wav we just saved. Status starts at queued so a reconnect
    burst from the field device just piles up rows; the worker drains them.
    """
    with connect() as conn:
        row = conn.execute(
            f"""
            INSERT INTO audio_jobs (id, original_name, path, status)
            VALUES (%s, %s, %s, 'queued')
            RETURNING {JOB_SELECT}
            """,
            (audio_id, original_name, path),
        ).fetchone()
        conn.commit()
    row["id"] = str(row["id"])
    return row


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_LA)
    return dt


def list_jobs(
    *,
    agent_status: str | None = None,
    summary_status: str | None = None,
    oldest_first: bool = False,
    limit: int | None = None,
    q: str | None = None,
    created_on: date | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> list[dict]:
    """Inbox: newest first. Aria FIFO: oldest_first + agent_status=pending."""
    clauses = ["TRUE"]
    params: list[object] = []
    if agent_status:
        clauses.append("agent_status = %s")
        params.append(agent_status)
    if summary_status:
        clauses.append("summary_status = %s")
        params.append(summary_status)
    if created_on is not None:
        start = datetime.combine(created_on, time.min, tzinfo=_LA)
        clauses.append("created_at >= %s AND created_at < %s")
        params.extend([start, start + timedelta(days=1)])
    else:
        if created_after is not None:
            clauses.append("created_at >= %s")
            params.append(_aware(created_after))
        if created_before is not None:
            clauses.append("created_at < %s")
            params.append(_aware(created_before))
    if q:
        clauses.append(
            "(summary ILIKE %s OR original_name ILIKE %s OR transcript ILIKE %s)"
        )
        like = f"%{q}%"
        params.extend([like, like, like])
    order = "ASC" if oldest_first else "DESC"
    sql = f"""
        SELECT {JOB_SELECT}
        FROM audio_jobs
        WHERE {" AND ".join(clauses)}
        ORDER BY created_at {order}
    """
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    for row in rows:
        row["id"] = str(row["id"])
    return rows


def get_job(audio_id: str) -> dict | None:
    """Look up one job. None means we never accepted that id."""
    try:
        UUID(audio_id)
    except ValueError:
        return None
    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT {JOB_SELECT}
            FROM audio_jobs
            WHERE id = %s
            """,
            (audio_id,),
        ).fetchone()
    if row is None:
        return None
    row["id"] = str(row["id"])
    return row


def delete_job(audio_id: str) -> dict | None:
    """Remove one row. None means that id was never stored."""
    try:
        UUID(audio_id)
    except ValueError:
        return None
    with connect() as conn:
        row = conn.execute(
            f"""
            DELETE FROM audio_jobs
            WHERE id = %s
            RETURNING {JOB_SELECT}
            """,
            (audio_id,),
        ).fetchone()
        conn.commit()
    if row is None:
        return None
    row["id"] = str(row["id"])
    return row


def claim_queued() -> dict | None:
    """
    Atomically take the oldest queued job.

    `FOR UPDATE SKIP LOCKED` means: if another worker already grabbed
    this row, skip it and try the next one. Two workers will not
    transcribe the same wav.
    """
    with connect() as conn:
        row = conn.execute(
            """
            WITH next_job AS (
                SELECT id
                FROM audio_jobs
                WHERE status = 'queued'
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE audio_jobs AS j
            SET status = 'processing', updated_at = now()
            FROM next_job
            WHERE j.id = next_job.id
            RETURNING j.id, j.original_name, j.path, j.status
            """
        ).fetchone()
        conn.commit()
    if row is None:
        return None
    row["id"] = str(row["id"])
    return row


def mark_done(audio_id: str, transcript: str) -> None:
    """Whisper succeeded. Enhancer will pick this up (summary_status=pending)."""
    with connect() as conn:
        conn.execute(
            """
            UPDATE audio_jobs
            SET status = 'done',
                transcript = %s,
                error = NULL,
                summary_status = 'pending',
                summary_error = NULL,
                updated_at = now()
            WHERE id = %s
            """,
            (transcript, audio_id),
        )
        conn.commit()


def claim_pending_enhance() -> dict | None:
    """
    Oldest done transcript that still needs a note.
    Failed wavs are skipped — there is no transcript to summarize.
    """
    with connect() as conn:
        row = conn.execute(
            """
            WITH next_job AS (
                SELECT id
                FROM audio_jobs
                WHERE status = 'done'
                  AND summary_status = 'pending'
                  AND transcript IS NOT NULL
                  AND transcript <> ''
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE audio_jobs AS j
            SET summary_status = 'processing', updated_at = now()
            FROM next_job
            WHERE j.id = next_job.id
            RETURNING j.id, j.original_name, j.transcript
            """
        ).fetchone()
        conn.commit()
    if row is None:
        return None
    row["id"] = str(row["id"])
    return row


def mark_enhanced(
    audio_id: str,
    summary: str,
    *,
    model: str | None,
    prompt_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE audio_jobs
            SET summary = %s,
                summary_status = 'done',
                summary_error = NULL,
                summary_model = %s,
                summary_prompt_tokens = %s,
                summary_output_tokens = %s,
                summary_total_tokens = %s,
                agent_status = 'pending',
                updated_at = now()
            WHERE id = %s
            """,
            (summary, model, prompt_tokens, output_tokens, total_tokens, audio_id),
        )
        conn.commit()


def mark_enhance_failed(audio_id: str, error: str) -> None:
    """Note failed. The wav row stays status=done and the transcript stays."""
    with connect() as conn:
        conn.execute(
            """
            UPDATE audio_jobs
            SET summary_status = 'failed',
                summary_error = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (error, audio_id),
        )
        conn.commit()


_AGENT_STATUSES = frozenset({"pending", "claimed", "done", "failed"})


def mark_agent(audio_id: str, status: str, note: str | None = None) -> dict | None:
    """Aria claims / finishes a summarized note. Does not touch the wav row."""
    if status not in _AGENT_STATUSES:
        raise ValueError(f"Invalid agent_status: {status}")
    with connect() as conn:
        row = conn.execute(
            f"""
            UPDATE audio_jobs
            SET agent_status = %s,
                agent_note = COALESCE(%s, agent_note),
                updated_at = now()
            WHERE id = %s
            RETURNING {JOB_SELECT}
            """,
            (status, note, audio_id),
        ).fetchone()
        conn.commit()
    if row is None:
        return None
    row["id"] = str(row["id"])
    return row


def mark_failed(audio_id: str, error: str) -> None:
    """Studio unreachable, bad response, missing file — keep the id, record why."""
    with connect() as conn:
        conn.execute(
            """
            UPDATE audio_jobs
            SET status = 'failed',
                error = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (error, audio_id),
        )
        conn.commit()
