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
Extract a short note from one voice-memo transcript. Speaker is Caleb.

Use only facts he said. Do not invent people, dates, places, tasks, or amounts.
Copy names as spoken. Do not quote the transcript. Do not give advice.
Do not copy these instructions into the note.

Allowed headings, in this order. Skip a heading if it has no fact.

# Title
One short line.

# Do
Work he still has to do. Imperative. One fact per bullet.

# Waiting
Blocked on someone else.

# Spent
Money he said he spent: what and how much.

# Done
Work already finished.

# Context
Other facts that are not Do, Waiting, Spent, or Done.

Example — he said he biked with his dad and this is just a test:
# Title
Bike ride with Dad
# Done
- Went on a bike ride with Dad
# Context
- Test memo to end the day
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
    text = _THINK.sub("", _content_text(response.choices[0].message)).strip()
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
