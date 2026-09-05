-- field_ai.audio_jobs
--
-- One row per uploaded .wav. The UUID is the same as the filename:
--   /audio/<id>.wav
--
-- worker.py:    queued → processing → done|failed
-- enhance.py:   summary_status pending → processing → done|failed

CREATE TABLE IF NOT EXISTS audio_jobs (
    id                     UUID PRIMARY KEY,
    original_name          TEXT NOT NULL,
    path                   TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'queued'
                             CHECK (status IN ('queued', 'processing', 'done', 'failed')),
    transcript             TEXT,
    error                  TEXT,
    summary                TEXT,
    summary_status         TEXT NOT NULL DEFAULT 'pending'
                             CHECK (summary_status IN ('pending', 'processing', 'done', 'failed')),
    summary_error          TEXT,
    summary_model          TEXT,
    summary_prompt_tokens  INTEGER,
    summary_output_tokens  INTEGER,
    summary_total_tokens   INTEGER,
    agent_status           TEXT NOT NULL DEFAULT 'pending'
                             CHECK (agent_status IN ('pending', 'claimed', 'done', 'failed')),
    agent_note             TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audio_jobs_queued_idx
    ON audio_jobs (created_at)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS audio_jobs_summary_pending_idx
    ON audio_jobs (created_at)
    WHERE summary_status = 'pending' AND status = 'done';

CREATE INDEX IF NOT EXISTS audio_jobs_agent_pending_idx
    ON audio_jobs (created_at)
    WHERE agent_status = 'pending' AND summary_status = 'done';
