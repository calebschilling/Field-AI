"""
Step 1 of 5 — the decisions.

Everything else in this project reads from here so limits and paths are
not scattered as magic numbers. Secrets come from `.env` (gitignored).

Next: audio.py (how we inspect and store a .wav).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load `.env` from the project root so `DATABASE_URL` etc. are in os.environ.
load_dotenv()

# Where accepted files land.
#
# Cursor docker: set AUDIO_DIR in `.env` to a writable folder.
# Host compose: docker-compose.yml bind-mounts ./data/audio -> /audio
# so recordings stay on the host disk across container rebuilds.
AUDIO_DIR = Path(os.environ.get("AUDIO_DIR", "/audio"))

# Postgres. From this container use the Tailscale IP, not 127.0.0.1
# (127.0.0.1 here is this container, not the host).
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Mac Studio running LM Studio, OpenAI-compatible transcription endpoint.
TRANSCRIBE_URL = os.environ.get(
    "TRANSCRIBE_URL",
    "http://100.121.55.88:8000/v1/audio/transcriptions",
)

# Same machine, Ollama / MLX chat. Used only by enhance.py.
LLM_URL = os.environ.get("LLM_URL", "http://100.121.55.88:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:14b")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")

# Hard cap. An unbounded upload will fill the disk. Raise this if your
# field recordings are larger; the streaming write in audio.py still
# never loads the whole file into RAM.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# We only accept this suffix. The real safety check is the file header
# in audio.py — a renamed .exe called "note.wav" will still be rejected.
ALLOWED_SUFFIX = ".wav"

# How much we read from disk at a time while saving. 1 MB is a balance
# between syscall overhead and memory use.
CHUNK_BYTES = 1024 * 1024

# Bind address.
#
# 127.0.0.1 = this process only. Tailscale packets arrive on a different
# interface (usually 100.x.x.x) and would never reach us.
# 0.0.0.0    = every interface. In the HOST compose file that is the
#              container's eth0; compose publishes host 8080 -> 8080
#              so Tailscale-on-the-host can forward traffic in.
# See docker-compose.yml.
HOST = "0.0.0.0"

# Listen port inside the process. Compose maps host 8080 to this.
PORT = 8080
