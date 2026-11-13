"""`RateLimiter` in memory: the latest hit times per key, in a rolling window."""

from datetime import datetime

from asmbly_ceramics.domain.limits import RateLimit


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[datetime]] = {}
        self.keys_hit: list[str] = []  # every key counted, in order, for tests of the hashing
        self.fail_with: Exception | None = None

    def hit(self, key: str, limit: RateLimit, now: datetime) -> bool:
        if now.utcoffset() is None:
            raise ValueError("a rate limit's time is aware")
        if self.fail_with is not None:
            raise self.fail_with
        self.keys_hit.append(key)
        start = now - limit.window
        earlier = [at for at in self._hits.get(key, []) if start < at <= now]
        allowed = len(earlier) < limit.limit
        # Counted, allowed or not. Only the latest `limit` hits can decide a later one,
        # so no more are kept (phase 4's item keeps the same bound).
        self._hits[key] = [*earlier, now][-limit.limit :]
        return allowed
