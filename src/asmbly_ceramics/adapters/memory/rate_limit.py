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
        hits = self._hits.get(key, [])
        # Hits later than `now` count: a slow request that read the clock before a fast
        # one must not forget the fast one's hit.
        counted = [at for at in hits if start < at]
        allowed = len(counted) < limit.limit
        # Counted, allowed or not. The latest `limit` hits of all stored, not only of
        # those in this hit's window: a hit outside it may still be inside the window of
        # an earlier-clocked hit that arrives later. Only those can decide a later hit,
        # so no more are kept (the DynamoDB item keeps the same bound).
        self._hits[key] = sorted([*hits, now])[-limit.limit :]
        return allowed
