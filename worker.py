"""
Step 5 of 5 — the batch job.

The HTTP server only stores files and inserts `queued` rows.
This process walks those rows and sends each wav to the Mac Studio.

    python worker.py

Leave it running. When the field device reconnects and dumps a batch
of POSTs, this drain picks them up oldest-first.

Read order:
  1. config.py  — paths, DATABASE_URL, TRANSCRIBE_URL
  2. audio.py   — how a wav is saved
  3. studio.py  — the HTTP call to the Mac Studio
  4. db.py      — claim / mark_done / mark_failed
  5. this file
"""

import time

from db import claim_queued, mark_done, mark_failed
from studio import transcribe_wav

# How long to wait when the queue is empty. Short enough that a reconnect
# burst starts moving quickly, long enough that we do not hammer Postgres.
IDLE_SECONDS = 2


def process_one() -> bool:
    """
    Claim one queued job and transcribe it.
    Returns True if there was work, False if the queue was empty.
    """
    job = claim_queued()
    if job is None:
        return False

    audio_id = job["id"]
    print(f"processing {audio_id}  {job['original_name']}")
    try:
        text = transcribe_wav(job["path"])
    except Exception as exc:
        mark_failed(audio_id, str(exc))
        print(f"failed     {audio_id}  {exc}")
        return True

    mark_done(audio_id, text)
    preview = text if len(text) < 80 else text[:77] + "..."
    print(f"done       {audio_id}  {preview!r}")
    return True


def main() -> None:
    print("worker watching audio_jobs (status=queued)")
    while True:
        if not process_one():
            time.sleep(IDLE_SECONDS)


if __name__ == "__main__":
    main()
