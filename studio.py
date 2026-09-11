"""
Step 3 of 5 — send a wav to the Mac Studio.

This is the same HTTP call as the original send_wav_file.py, pulled out
so the worker can reuse it. LM Studio speaks the OpenAI-style
/v1/audio/transcriptions endpoint over Tailscale.

Next: main.py (HTTP ingest) then worker.py (batch drain).
"""

from pathlib import Path

import requests

from config import TRANSCRIBE_URL
from reconnect import TransientStudioError, retry_call


def transcribe_wav(path: str | Path) -> str:
    """
    POST the file to the Studio. Returns the `text` field.

    Connection / timeout / 502–504 are retried, then raised as
    StudioUnavailable so the worker can requeue. A bad file or a
    bad JSON body is raised as-is and the job fails.

    We do not transcribe in the upload request — a field device coming
    back online may dump many wavs at once, and each Studio call can
    take a while.
    """
    wav = Path(path)

    def once() -> str:
        with wav.open("rb") as handle:
            response = requests.post(
                TRANSCRIBE_URL,
                files={"file": (wav.name, handle, "audio/wav")},
                timeout=300,
            )
        if response.status_code in (502, 503, 504):
            raise TransientStudioError(f"Studio HTTP {response.status_code}")
        response.raise_for_status()
        payload = response.json()
        text = payload.get("text")
        if not isinstance(text, str):
            raise RuntimeError(f"Studio response had no text: {payload!r}")
        return text

    return retry_call(
        once,
        transient=(
            requests.ConnectionError,
            requests.Timeout,
            TransientStudioError,
        ),
    )
