"""
Step 4 of 5 — the HTTP door. (Worker is step 5.)

FastAPI turns this file into a REST server. A client POSTs a multipart
form field named `file`; we save it and insert a `queued` row. We do
not wait for the Mac Studio — that is worker.py.

Read order if you want to see how this was built:
  1. config.py  — limits, folders, env
  2. audio.py   — header check + disk write
  3. db.py      — Postgres insert / lookup
  4. this file  — routes
  5. worker.py  — queued → processing → done

Run (from the project root):

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python main.py          # ingest
    python worker.py        # transcribe (separate process)

The process listens on every interface (0.0.0.0) on port 8080 so that
when this app later runs in its own container, the host can publish
8080 and Tailscale-on-the-host can reach it.

    curl -F "file=@recording.wav" http://127.0.0.1:8080/audio

Interactive docs: http://127.0.0.1:8080/docs
"""

import subprocess
from datetime import date, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from audio import RejectedWav, accept_upload, audio_path, describe_job, remove_recording
from config import HOST, PORT
from db import list_jobs, mark_agent

INBOX_HTML = Path(__file__).with_name("inbox.html")

# `app` is what uvicorn loads: `uvicorn main:app`
app = FastAPI(
    title="Field-AI",
    description="Accept .wav uploads, queue them, transcribe on the Mac Studio.",
)


@app.get("/", response_class=HTMLResponse)
async def inbox() -> str:
    """Human view of every recording + transcript."""
    return INBOX_HTML.read_text(encoding="utf-8")


@app.get("/health")
async def health() -> dict:
    """Cheap liveness check. If this fails, the process is down."""
    return {"ok": True}


class AgentUpdate(BaseModel):
    status: str = Field(pattern="^(pending|claimed|done|failed)$")
    note: str | None = None


@app.get("/audio")
async def list_audio(
    agent_status: str | None = None,
    summary_status: str | None = None,
    oldest_first: bool = False,
    limit: int | None = Query(default=None, ge=1, le=200),
    q: str | None = None,
    created_on: date | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> list[dict]:
    """
    Inbox: no filters, newest first.
    Aria FIFO: ?agent_status=pending&summary_status=done&oldest_first=true
    Day filter: ?created_on=YYYY-MM-DD (America/Los_Angeles)
    """
    if agent_status == "pending" and summary_status is None:
        summary_status = "done"
        oldest_first = True
    return list_jobs(
        agent_status=agent_status,
        summary_status=summary_status,
        oldest_first=oldest_first,
        limit=limit,
        q=q,
        created_on=created_on,
        created_after=created_after,
        created_before=created_before,
    )


@app.post("/audio")
async def upload_audio(file: UploadFile = File(...)) -> dict:
    """
    Accept one .wav as multipart/form-data.

    Saves the file, inserts status=queued, returns immediately.
    The field device can dump a batch of these when it comes back online.
    """
    try:
        return await accept_upload(file)
    except RejectedWav as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    finally:
        await file.close()


@app.get("/audio/{audio_id}/wav")
async def get_wav(audio_id: str) -> FileResponse:
    """Play or download the stored file. Name in the URL is a UUID, not the original."""
    try:
        path = audio_path(audio_id)
    except RejectedWav as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.post("/audio/{audio_id}/agent")
async def update_agent(audio_id: str, body: AgentUpdate) -> dict:
    """Aria marks a summarized note claimed / done / failed."""
    try:
        row = mark_agent(audio_id, body.status, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    return row


@app.get("/audio/{audio_id}")
async def get_audio(audio_id: str) -> dict:
    """Look up status + transcript. Same id the POST returned."""
    try:
        return describe_job(audio_id)
    except RejectedWav as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@app.delete("/audio/{audio_id}")
async def delete_audio(audio_id: str) -> dict:
    """Remove one recording: Postgres row and wav file."""
    try:
        row = remove_recording(audio_id)
    except RejectedWav as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return {"ok": True, "deleted": row["id"], "original_name": row.get("original_name")}


def _tailscale_ipv4() -> str | None:
    """
    Ask the Tailscale CLI for this machine's 100.x address.

    This Cursor docker usually has no CLI — Tailscale lives on the host.
    Binding 0.0.0.0 is still what makes a published port reachable.
    """
    try:
        out = subprocess.check_output(
            ["tailscale", "ip", "-4"],
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    ip = out.strip().splitlines()[0] if out.strip() else ""
    return ip or None


def announce_urls() -> None:
    """Print every useful URL so you do not have to guess after startup."""
    print(f"Listening on {HOST}:{PORT}")
    print(f"  inbox:         http://127.0.0.1:{PORT}/")
    print(f"  this machine:  http://127.0.0.1:{PORT}/audio")
    print(f"  docs:          http://127.0.0.1:{PORT}/docs")
    ts_ip = _tailscale_ipv4()
    if ts_ip:
        print(f"  Tailscale:     http://{ts_ip}:{PORT}/")
    else:
        print(
            "  Tailscale:     host publishes this port; use the host's "
            f"100.x IP on {PORT} (CLI not in this container)"
        )


if __name__ == "__main__":
    announce_urls()
    uvicorn.run("main:app", host=HOST, port=PORT)
