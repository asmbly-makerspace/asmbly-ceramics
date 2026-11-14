"""`SystemClock`."""

from datetime import UTC, datetime, timedelta

from asmbly_ceramics.adapters.clock import SystemClock
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.ports.clock import Clock


def test_clock_is_utc_aware() -> None:
    clock: Clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is UTC
    assert abs(datetime.now(UTC) - now) < timedelta(seconds=5)
    assert now.astimezone(STUDIO_TZ).utcoffset() in (timedelta(hours=-6), timedelta(hours=-5))  # tzdata
