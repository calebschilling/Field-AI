"""
Mac Studio is down or Tailscale blipped.

Retry the HTTP call a few times, then tell the worker to requeue.
A refused connection is not a bad recording.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from config import STUDIO_RETRY_ATTEMPTS, STUDIO_RETRY_BASE_DELAY

T = TypeVar("T")


class StudioUnavailable(Exception):
    """Studio did not answer. Caller requeues; do not mark failed."""


class TransientStudioError(Exception):
    """This attempt failed in a way that is worth retrying."""


def retry_call(
    fn: Callable[[], T],
    *,
    transient: tuple[type[BaseException], ...],
    attempts: int = STUDIO_RETRY_ATTEMPTS,
    base_delay: float = STUDIO_RETRY_BASE_DELAY,
) -> T:
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except transient as exc:
            last = exc
            if i == attempts - 1:
                break
            delay = base_delay * (2**i)
            print(f"studio unreachable; retry in {delay:.0f}s  ({exc})")
            time.sleep(delay)
    raise StudioUnavailable(str(last)) from last
