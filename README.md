# Field-AI

Voice memos in. Notes out.

A field recorder drops a `.wav` here. Field-AI stores it, transcribes it on the Mac Studio, and writes a short note (Title, Do, Waiting, Spent, Done, Context — empty sections omitted). The inbox at `/` is the desk.

```
wav  →  Postgres + disk  →  Whisper  →  Qwen 2.5 14B  →  inbox
                              worker      enhancer
```

Aria (separate app) can pick up finished notes. This repo does not run Aria.

## How to use the inbox

Open **http://127.0.0.1:8081/** on this machine, or `http://<host-tailscale-ip>:8081/` from anywhere on the tailnet.

- **Desktop:** walnut rail on the left is the day’s stack. Click a row; the cream page on the right is that note. Play the wav, open the transcript, delete if it was junk.
- **Phone:** same pages, stacked. Search and day filter sit in the header.
- **Search** looks through titles, notes, and transcripts.
- **Day** limits the desk to one calendar day (Los Angeles). **All days** clears it.
- Status on a note is the pipeline, not a guess: queued → transcribing → summarizing → ready / reviewed.

New recordings show up on their own. The page refreshes every few seconds.

### Drop a recording in

From a phone, a recorder, or this machine:

```bash
curl -F "file=@memo.wav" http://127.0.0.1:8081/audio
```

Only real WAVs are accepted (header check, not just the filename). Cap is 50 MB. The response is the job id; the inbox is the human view.

API extras: `GET /audio`, `GET /audio/{id}`, `GET /audio/{id}/wav`, `DELETE /audio/{id}`, `GET /health`, `GET /docs`.

## First-time setup

Postgres already runs on the host. This compose file does **not** start a database.

1. Create the table once:

```bash
psql "$DATABASE_URL" -f schema.sql
```

`schema.sql` is the live `audio_jobs` table (status, transcript, summary, Aria columns, indexes). Not a sketch.

2. Copy env and fill the real values:

```bash
cp .env.example .env
```

| Variable | What it is |
|---|---|
| `DATABASE_URL` | Postgres. From Docker, use the host Tailscale IP, not `127.0.0.1`. |
| `AUDIO_DIR` | Compose forces `/audio` (bind-mounted to `./data/audio` on the host). |
| `TRANSCRIBE_URL` | Studio Whisper endpoint. |
| `LLM_URL` / `LLM_MODEL` | Studio Ollama. Default model is `qwen2.5:14b`. |

3. Start the three processes:

```bash
docker compose up -d --build
```

| Container | Job |
|---|---|
| `api` | Inbox + upload. Host **8081** → container 8080. |
| `worker` | Oldest `queued` wav → Whisper → transcript. |
| `enhancer` | Done transcript → structured note. |

Wavs survive rebuilds. They live on the host at `./data/audio`. `.env` is not in git.

## Layout

- `main.py` — HTTP (inbox, upload, list, delete)
- `audio.py` — WAV check + disk write
- `db.py` — Postgres helpers
- `worker.py` / `studio.py` — transcription
- `enhance.py` / `llm.py` — the note
- `inbox.html` — the desk
- `schema.sql` — create `audio_jobs`
