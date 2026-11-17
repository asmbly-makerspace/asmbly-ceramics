"""The public form's rate limits (#2) and its daily cap on received emails (#30), counted
the one way every use case counts them."""

import logging
from datetime import datetime

from asmbly_ceramics.domain.errors import DropOffNotTaken, TooManySubmissions
from asmbly_ceramics.domain.limits import RECEIVED_CAP_WINDOW, RateLimit
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.rate_limit import RateLimiter
from asmbly_ceramics.use_cases.log import log_event

RECEIVED_CAP_KEY = "received-emails"
"""The daily cap's one bucket per environment (its table). A fixed name that holds
nothing personal, stored as `RATE#received-emails`; never a hash of anything."""


def check_limits(
    limiter: RateLimiter,
    *,
    device_key: str,
    device_limit: RateLimit,
    address_key: str,
    address_limit: RateLimit,
    now: datetime,
    refused_event: str,
) -> None:
    """Counts one hit for the device, then, only if the device is allowed, one for the
    address; `TooManySubmissions` when either is over. A device already over its limit
    isn't counted against the address, so one phone retrying can't fill the bucket
    everyone on the studio's wifi shares (decided in 2a's review). The keys are keyed
    hashes (`KeyHasher`). `RecordsUnavailable` goes up after a log line: the limit fails
    closed. Each refusal is logged as `refused_event` with its `reason`."""
    try:
        device_ok = limiter.hit(device_key, device_limit, now)
        address_ok = device_ok and limiter.hit(address_key, address_limit, now)
    except RecordsUnavailable as error:
        log_event(refused_event, level=logging.WARNING, reason="limiter_unavailable", error_code=error.code)
        raise
    if not device_ok:
        log_event(refused_event, reason="device_limit")
        raise TooManySubmissions()
    if not address_ok:
        log_event(refused_event, reason="address_limit")
        raise TooManySubmissions()


def check_received_cap(limiter: RateLimiter, *, per_day: int, now: datetime, refused_event: str) -> None:
    """Counts one received email against the studio's daily cap, in a rolling
    `RECEIVED_CAP_WINDOW`; `DropOffNotTaken` past it, logged as `refused_event` with
    `reason=daily_cap` at ERROR, so the logged-errors alarm tells the maintainers.
    `RecordsUnavailable` goes up after a WARNING line (`reason=limiter_unavailable`): the
    cap fails closed. Neither line holds the count or the setting's value.

    A cap lowered below the hits kept refuses at once; one raised counts the hits kept
    (at most the old cap's), so it allows more, never fewer, than it should."""
    try:
        allowed = limiter.hit(RECEIVED_CAP_KEY, RateLimit(limit=per_day, window=RECEIVED_CAP_WINDOW), now)
    except RecordsUnavailable as error:
        log_event(refused_event, level=logging.WARNING, reason="limiter_unavailable", error_code=error.code)
        raise
    if not allowed:
        log_event(refused_event, level=logging.ERROR, reason="daily_cap")
        raise DropOffNotTaken()
