"""Counting submissions per device and address (#2: 10 per device in 10 minutes)."""

from datetime import datetime
from typing import Protocol

from asmbly_ceramics.domain.limits import RateLimit


class RateLimiter(Protocol):
    def hit(self, key: str, limit: RateLimit, now: datetime) -> bool:
        """Counts this hit for `key` and says whether it is allowed.

        The window is rolling, not fixed: a hit is allowed only if, counting it, `key`
        has at most `limit.limit` hits in `(now - limit.window, now]`. So no rolling
        window ever holds more than `limit.limit` allowed hits, across any boundary
        (#2: "more than 10 within 10 minutes are refused"). A refused hit counts too, so
        retrying inside the window stays refused.

        `key` must be a keyed hash (phase 2's `KeyHasher`), never a raw address or
        cookie value: the adapter stores it.

        `now` is aware (`ValueError` otherwise). `RecordsUnavailable` when the count
        can't be read or written: the limiter fails closed, so the caller refuses.
        """
        ...
