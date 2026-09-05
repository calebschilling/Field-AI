"""
Second lane. worker.py writes the transcript; this process writes the summary.

    python enhance.py

Only claims rows that are already status=done with a transcript.
A failure here never flips the wav job back to failed.
"""

import time

from db import claim_pending_enhance, mark_enhance_failed, mark_enhanced
from llm import enhance_transcript

IDLE_SECONDS = 2


def process_one() -> bool:
    job = claim_pending_enhance()
    if job is None:
        return False

    audio_id = job["id"]
    print(f"summarizing {audio_id}  {job['original_name']}")
    try:
        result = enhance_transcript(job["transcript"])
    except Exception as exc:
        mark_enhance_failed(audio_id, str(exc))
        print(f"summary failed  {audio_id}  {exc}")
        return True

    mark_enhanced(
        audio_id,
        result.text,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
    )
    preview = result.text if len(result.text) < 80 else result.text[:77] + "..."
    print(
        f"summarized  {audio_id}  "
        f"out={result.output_tokens} total={result.total_tokens}  {preview!r}"
    )
    return True


def main() -> None:
    print("enhancer watching audio_jobs (status=done, summary_status=pending)")
    while True:
        if not process_one():
            time.sleep(IDLE_SECONDS)


if __name__ == "__main__":
    main()
