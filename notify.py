"""Tell Aria a summary is ready. Do not call the model from here."""

from __future__ import annotations

import os

import httpx

from dotenv import load_dotenv

load_dotenv()


def notify_aria(audio_id: str) -> None:
    url = (os.environ.get("ARIA_INTAKE_URL") or "").strip()
    if not url:
        print("ARIA_INTAKE_URL empty — skip push")
        return
    headers = {}
    key = (os.environ.get("ARIA_SKILLS_KEY") or "").strip()
    if key:
        headers["X-Skills-Key"] = key
    try:
        response = httpx.post(
            url,
            json={"audio_id": audio_id},
            headers=headers,
            timeout=120.0,
        )
        response.raise_for_status()
        print(f"aria notified  {audio_id}  {response.status_code}")
    except Exception as exc:
        print(f"aria notify failed  {audio_id}  {exc}")
