"""The public form's rate limits (#2), counted the one way every use case counts them."""

import logging
from datetime import datetime

from asmbly_ceramics.domain.errors import TooManySubmissions
from asmbly_ceramics.domain.limits import RateLimit
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.rate_limit import RateLimiter
from asmbly_ceramics.use_cases.log import log_event


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
