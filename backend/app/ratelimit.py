# app/ratelimit.py
import time
from collections import defaultdict


class InMemoryRateLimiter:
    """
    In-process sliding window rate limiter.
    Provides check(key, limit, window_s) interface suitable for swapping with Redis later.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, limit: int, window_s: float) -> bool:
        """
        Returns True if the request is permitted, False if limit exceeded.
        """
        now = time.time()
        window_start = now - window_s
        # Filter out timestamps older than the window
        timestamps = [t for t in self._events[key] if t > window_start]
        if len(timestamps) >= limit:
            self._events[key] = timestamps
            return False
        timestamps.append(now)
        self._events[key] = timestamps
        return True

    def reset(self, key: str | None = None) -> None:
        if key is not None:
            self._events.pop(key, None)
        else:
            self._events.clear()


limiter = InMemoryRateLimiter()


from fastapi import HTTPException, Request, status


def check_rate_limit(key: str, limit: int, window_s: float) -> bool:
    return limiter.check(key, limit, window_s)


def rate_limit(tag: str, limit: int, window_s: float):
    async def dependency(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key = f"{tag}:{client_ip}"
        if not check_rate_limit(key, limit, window_s):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded.",
            )
    return dependency

