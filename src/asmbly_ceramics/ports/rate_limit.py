"""Counting submissions per device and address (#2: 10 per device in 10 minutes), per
recipient address (#18: 3 in 24 hours), and the form's daily cap on received emails (#30)."""

from datetime import datetime
from typing import Protocol

from asmbly_ceramics.domain.limits import RateLimit


class RateLimiter(Protocol):
    def hit(self, key: str, limit: RateLimit, now: datetime) -> bool:
        """Counts this hit for `key` and says whether it is allowed.

        The window is rolling, not fixed: a hit is allowed only if, counting it, `key`
        has at most `limit.limit` hits later than `now - limit.window`, hits later than
        `now` included. Those happen when overlapping callers read the clock in one order
        and hit in the other (a slow submit that read it before a fast one): they are
        counted and kept, never forgotten. So no rolling window ever holds more than
        `limit.limit` allowed hits, across any boundary (#2: "more than 10 within 10
        minutes are refused"). A refused hit counts too, so retrying inside the window
        stays refused.

        Only the latest `limit.limit` hits (by time, not by arrival) are kept (the hits
        that can decide a later one), so a caller that changes `limit` between hits on one
        key (the daily cap, whose number staff set in the console) gets this: a lowered
        limit refuses at once when the kept hits already reach it, and trims the kept hits
        to the new limit at that hit (not before one arrives); a
        raised one counts only the hits kept, at most the old limit's, so after a lower
        limit trimmed them it allows up to the raised limit's number again in the same
        window.

        `key` must be a keyed hash (phase 2's `KeyHasher`), or a fixed name that holds
        nothing personal (the daily cap's `received-emails`), never a raw address or
        cookie value: the adapter stores it.

        `now` is aware (`ValueError` otherwise). `RecordsUnavailable` when the count
        can't be read or written: the limiter fails closed, so the caller refuses.
        """
        ...
