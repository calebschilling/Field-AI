"""
Step 2 of 5 — what we do with a .wav once it arrives.

This module has no HTTP in it on purpose. It only knows files:
  - is this actually a WAV?
  - write it to AUDIO_DIR under a name we control
  - insert a queued row in Postgres (same UUID)

The HTTP layer (main.py) calls accept_upload() and turns failures into
status codes.

WAV header, first 12 bytes (little-endian):

    0–3   "RIFF"     container type
    4–7   file size  we ignore this; we count bytes ourselves
    8–11  "WAVE"     payload type

A client can lie about the filename or Content-Type. They cannot easily
fake those magic bytes unless they actually send a WAV.

Next: db.py (the Postgres helpers).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile

from config import ALLOWED_SUFFIX, AUDIO_DIR, CHUNK_BYTES, MAX_UPLOAD_BYTES
from db import delete_job, get_job, insert_job

# A WAV always starts with these two 4-byte tags.
_RIFF = b"RIFF"
_WAVE = b"WAVE"


class RejectedWav(Exception):
    """
    We refused the file. `status` is a hint for the HTTP layer
    (400 = bad file, 413 = too big, 404 = unknown id).
    The message is safe to show the client.
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def is_wav_header(header: bytes) -> bool:
    """True if the first 12 bytes look like a real WAV, not just a .wav name."""
    return (
        len(header) >= 12
        and header[:4] == _RIFF
        and header[8:12] == _WAVE
    )


def ensure_audio_dir() -> None:
    """Create AUDIO_DIR on first use (local .env path, or /audio in production)."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def audio_path(audio_id: str) -> Path:
    """
    Map an id back to a file.

    We only allow a UUID-shaped name (hex + hyphens). That blocks path
    tricks like `../../etc/passwd` in the URL.
    """
    try:
        UUID(audio_id)
    except ValueError as exc:
        raise RejectedWav("Unknown audio id") from exc
    return AUDIO_DIR / f"{audio_id}{ALLOWED_SUFFIX}"


async def save_wav(file: UploadFile) -> dict:
    """
    Stream `file` to disk. Does not touch Postgres — accept_upload() does that
    after the bytes are safely on disk.

    Why stream: `UploadFile` is a temp-file / spool. Reading it in 1 MB
    chunks means a 40 MB recording never sits fully in Python memory.

    Why a UUID name: the client's filename is untrusted. `../` in a
    filename would let someone write outside AUDIO_DIR. We keep their
    original name in Postgres as original_name.
    """
    original_name = file.filename or ""
    if not original_name.lower().endswith(ALLOWED_SUFFIX):
        raise RejectedWav("Only .wav files are accepted")

    header = await file.read(12)
    if not is_wav_header(header):
        raise RejectedWav("File is not a valid WAV (missing RIFF/WAVE header)")

    ensure_audio_dir()
    audio_id = str(uuid4())
    dest = audio_path(audio_id)

    written = 0
    try:
        with dest.open("wb") as out:
            out.write(header)
            written += len(header)
            while True:
                chunk = await file.read(CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise RejectedWav(
                        f"File too large (max {MAX_UPLOAD_BYTES} bytes)",
                        status=413,
                    )
                out.write(chunk)
    except RejectedWav:
        dest.unlink(missing_ok=True)
        raise

    return {
        "id": audio_id,
        "filename": original_name,
        "path": str(dest),
        "bytes": written,
    }


async def accept_upload(file: UploadFile) -> dict:
    """
    The full ingest step: save the wav, then insert queued.

    If Postgres rejects the insert we delete the file so we do not leave
    orphans the worker would never see.
    """
    saved = await save_wav(file)
    try:
        job = insert_job(saved["id"], saved["filename"], saved["path"])
    except Exception:
        Path(saved["path"]).unlink(missing_ok=True)
        raise
    return {
        "id": job["id"],
        "filename": job["original_name"],
        "bytes": saved["bytes"],
        "status": job["status"],
        "path": job["path"],
    }


def describe_job(audio_id: str) -> dict:
    """Status/transcript for GET /audio/{id}. 404 if we never accepted it."""
    job = get_job(audio_id)
    if job is None:
        raise RejectedWav("Audio not found", status=404)
    return job


def remove_recording(audio_id: str) -> dict:
    """Delete the Postgres row and the wav. 404 if the id is unknown."""
    job = delete_job(audio_id)
    if job is None:
        raise RejectedWav("Audio not found", status=404)
    audio_path(audio_id).unlink(missing_ok=True)
    return job
