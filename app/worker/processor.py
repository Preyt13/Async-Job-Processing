"""Mock job execution and retry backoff helpers."""

from __future__ import annotations

import random
import time
from typing import Any


def compute_backoff_seconds(
    attempt: int,
    *,
    base_seconds: float,
    jitter_ratio: float,
) -> float:
    """Exponential backoff with symmetric jitter.

    attempt is 1-based (first retry after failure uses attempt=1).
    delay = base * 2^(attempt-1) * (1 ± jitter)
    """
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    exp = base_seconds * (2 ** (attempt - 1))
    jitter = exp * jitter_ratio * random.uniform(-1.0, 1.0)
    return max(0.0, exp + jitter)


def process_job(
    payload: dict[str, Any],
    *,
    should_fail: bool = False,
    work_seconds: float,
) -> dict[str, Any]:
    """Simulate work with a sleep. Raises on should_fail."""
    time.sleep(work_seconds)
    if should_fail:
        raise RuntimeError("mock processing failure")
    return {
        "echo": payload,
        "processed": True,
        "work_seconds": work_seconds,
    }
