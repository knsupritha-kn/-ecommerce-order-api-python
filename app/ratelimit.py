"""Tiny in-memory sliding-window rate limiter (per process, resets on restart)."""

import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException

from app.auth.dependencies import get_current_user

AI_LIMIT = 10  # requests ...
AI_WINDOW_SECONDS = 60.0  # ... per window, per user

_hits: dict[str, deque[float]] = defaultdict(deque)


def reset() -> None:
    _hits.clear()


def check(key: str, limit: int, window: float) -> float | None:
    """Record a hit. Returns None if allowed, else seconds until the next slot frees up."""
    now = time.monotonic()
    hits = _hits[key]
    while hits and now - hits[0] >= window:
        hits.popleft()
    if len(hits) >= limit:
        return window - (now - hits[0])
    hits.append(now)
    return None


async def ai_rate_limit(current_user: dict = Depends(get_current_user)) -> None:
    """Dependency for /ai/* endpoints: AI_LIMIT requests per AI_WINDOW_SECONDS per user."""
    retry_after = check(str(current_user["_id"]), AI_LIMIT, AI_WINDOW_SECONDS)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many AI requests, please slow down",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
