"""
Call the Mac Studio chat model. enhance.py uses this after a transcript exists.

The raw transcript is never rewritten here. We only produce the note.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

import httpx
from openai import OpenAI

from config import LLM_API_KEY, LLM_MODEL, LLM_URL

SYSTEM_PROMPT = """
You extract a structured note from one raw voice-memo transcript.

The speaker is the person who recorded it. Keep "I" as that person.

Hard rules:
- Use only facts in the transcript. Do not invent people, dates, places, or tasks.
- Do not guess unclear names. Copy the spelling as spoken.
- Do not quote the whole transcript back.
- Do not add advice, context, or a preamble.
- Do not infer "today", "scheduled", or why the memo was recorded.
- Do not show reasoning. Output the markdown only.
- If a section has no facts, omit the section. Do not write "None" or keep an empty heading.

# Title
One short line that names the point of the memo.

# Action Items
- Only work the speaker still has to do.
- Past tense (finished, sent, told, built) is done — put it in Notes, not here.
- Waiting on someone else ("once they send dates") is a Note, not a task.
- A finding or problem ("reviews vanished") is a Note unless they said they will act on it.
- Imperative. One task per line. Who/when only if they said it.

# People
- Human proper names only, one per line.
- Skip roles (manager), companies, teams, and "potential customer".
- A garbled name stays as spoken. Do not clean it up.

# Notes
- Done work, waits, findings, dates, places, constraints.
- Include a spoken company or unclear name if it is not a person.
""".strip()

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_client: OpenAI | None = None


@dataclass(frozen=True)
class SummaryResult:
    text: str
    model: str
    prompt_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


def _client_once() -> OpenAI:
    global _client
    if _client is None:
        http_client = httpx.Client(timeout=180.0)
        _client = OpenAI(
            base_url=LLM_URL,
            api_key=LLM_API_KEY or "ollama",
            http_client=http_client,
        )
    return _client


def _content_text(message) -> str:
    raw = getattr(message, "content", None)
    if raw is None:
        raw = getattr(message, "reasoning", None) or ""
    if isinstance(raw, list):
        parts = []
        for part in raw:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                text = getattr(part, "text", None)
                if text:
                    parts.append(str(text))
        raw = "".join(parts)
    return str(raw)


def _usage(response) -> tuple[int | None, int | None, int | None]:
    """prompt (input), output (summary), total. Ollama sometimes omits usage."""
    u = getattr(response, "usage", None)
    if u is None:
        return None, None, None
    prompt = getattr(u, "prompt_tokens", None)
    if prompt is None:
        prompt = getattr(u, "input_tokens", None)
    output = getattr(u, "completion_tokens", None)
    if output is None:
        output = getattr(u, "output_tokens", None)
    total = getattr(u, "total_tokens", None)
    if total is None and prompt is not None and output is not None:
        total = prompt + output
    return prompt, output, total


def _drop_empty_sections(md: str) -> str:
    """Models sometimes emit '# Notes\\nNone'. The prompt already forbids that."""
    blocks = re.split(r"(?m)(?=^# )", md)
    kept = []
    for block in blocks:
        body = re.sub(r"^# .*\n?", "", block).strip()
        if not body or body.lower() in {"none", "n/a", "- none"}:
            if block.startswith("# "):
                continue
        kept.append(block.rstrip())
    return "\n\n".join(p for p in kept if p).strip()


def enhance_transcript(transcript: str) -> SummaryResult:
    """Return the markdown note plus token counts. Raises if the Studio is down."""
    transcript = (transcript or "").strip()
    if not transcript:
        raise RuntimeError("No transcript to summarize")

    response = _client_once().chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        temperature=0.2,
    )
    text = _drop_empty_sections(
        _THINK.sub("", _content_text(response.choices[0].message)).strip()
    )
    if not text:
        raise RuntimeError("LLM returned an empty note")
    used_model = getattr(response, "model", None) or LLM_MODEL
    prompt, output, total = _usage(response)
    return SummaryResult(
        text=text,
        model=used_model,
        prompt_tokens=prompt,
        output_tokens=output,
        total_tokens=total,
    )
