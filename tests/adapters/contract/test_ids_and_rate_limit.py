"""`IdNumbers`' and `RateLimiter`'s contracts, on the fakes and the DynamoDB adapters on
moto."""

from collections.abc import Iterator
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from asmbly_ceramics.adapters.aws.ids import DynamoDbIdNumbers
from asmbly_ceramics.adapters.aws.rate_limit import DynamoDbRateLimiter
from asmbly_ceramics.adapters.memory.ids import MemoryIdNumbers
from asmbly_ceramics.adapters.memory.rate_limit import MemoryRateLimiter
from asmbly_ceramics.domain.ids import DropOffId, LoadId
from asmbly_ceramics.domain.limits import DEVICE_LIMIT, RateLimit
from asmbly_ceramics.ports.ids import IdNumbers
from asmbly_ceramics.ports.rate_limit import RateLimiter
from tests.adapters.conftest import TABLE
from tests.domain.builders import NOW

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
else:
    DynamoDBClient = Any

KEY = "made-up-keyed-hash"


@pytest.fixture(params=["memory", "dynamodb"])
def ids(request: pytest.FixtureRequest) -> Iterator[IdNumbers]:
    if request.param == "memory":
        yield MemoryIdNumbers()
    else:
        client: DynamoDBClient = request.getfixturevalue("dynamodb")
        yield DynamoDbIdNumbers(client, TABLE)


@pytest.fixture(params=["memory", "dynamodb"])
def limiter(request: pytest.FixtureRequest) -> Iterator[RateLimiter]:
    if request.param == "memory":
        yield MemoryRateLimiter()
    else:
        client: DynamoDBClient = request.getfixturevalue("dynamodb")
        yield DynamoDbRateLimiter(client, TABLE)


def test_ids_never_repeat_and_start_at_one(ids: IdNumbers) -> None:
    assert ids.next_drop_off_id() == DropOffId(1)  # AC-1 on an empty table
    assert ids.next_drop_off_id() == DropOffId(2)
    assert ids.next_load_id() == LoadId(1)  # its own counter
    assert ids.next_drop_off_id() == DropOffId(3)
    assert ids.next_load_id() == LoadId(2)


def test_rate_limiter_allows_limit_then_refuses_in_the_rolling_window(limiter: RateLimiter) -> None:
    for minute in range(DEVICE_LIMIT.limit):
        assert limiter.hit(KEY, DEVICE_LIMIT, NOW + timedelta(seconds=30 * minute))
    assert not limiter.hit(KEY, DEVICE_LIMIT, NOW + timedelta(minutes=5))
    assert limiter.hit("another-keyed-hash", DEVICE_LIMIT, NOW + timedelta(minutes=5))
    # A refused hit counts too: still refused just inside the window of the 2nd hit.
    assert not limiter.hit(KEY, DEVICE_LIMIT, NOW + timedelta(minutes=10, seconds=29))
    assert limiter.hit(KEY, DEVICE_LIMIT, NOW + timedelta(minutes=30))


def test_eleventh_hit_in_a_rolling_window_is_refused_across_a_ten_minute_boundary(
    limiter: RateLimiter,
) -> None:
    # 10 hits at 18:39 to 18:39:45 and then at 18:41: a fixed 18:30-18:40 window would let
    # the 18:41 hit through, but 18:31 to 18:41 already holds 10.
    start = NOW + timedelta(minutes=9)
    for n in range(DEVICE_LIMIT.limit):
        assert limiter.hit(KEY, DEVICE_LIMIT, start + timedelta(seconds=4 * n))
    assert not limiter.hit(KEY, DEVICE_LIMIT, NOW + timedelta(minutes=11))


def test_hits_older_than_the_window_stop_counting(limiter: RateLimiter) -> None:
    small = RateLimit(limit=2, window=timedelta(minutes=10))
    assert limiter.hit(KEY, small, NOW)
    assert limiter.hit(KEY, small, NOW + timedelta(minutes=1))
    assert not limiter.hit(KEY, small, NOW + timedelta(minutes=2))
    assert limiter.hit(KEY, small, NOW + timedelta(minutes=12, seconds=1))


def test_a_lowered_limit_refuses_at_once_and_a_raised_one_counts_only_the_hits_kept(
    limiter: RateLimiter,
) -> None:
    window = timedelta(hours=24)
    four = RateLimit(limit=4, window=window)
    two = RateLimit(limit=2, window=window)
    for n in range(4):
        assert limiter.hit(KEY, four, NOW + timedelta(minutes=n))
    # Lowered below the hits kept: refused at once, and only the latest 2 are kept.
    assert not limiter.hit(KEY, two, NOW + timedelta(minutes=4))
    # Raised again: 5 hits fell in the window, but only the 2 kept count, so 2 more pass.
    assert limiter.hit(KEY, four, NOW + timedelta(minutes=5))
    assert limiter.hit(KEY, four, NOW + timedelta(minutes=6))
    assert not limiter.hit(KEY, four, NOW + timedelta(minutes=7))


def test_a_hit_with_an_earlier_time_does_not_forget_later_hits(limiter: RateLimiter) -> None:
    # A slow caller read the clock before two fast ones and hits after them: their hits,
    # later than its `now`, still count and are still kept.
    three = RateLimit(limit=3, window=timedelta(hours=24))
    assert limiter.hit(KEY, three, NOW)
    assert limiter.hit(KEY, three, NOW + timedelta(seconds=20))
    assert limiter.hit(KEY, three, NOW + timedelta(seconds=21))
    assert not limiter.hit(KEY, three, NOW + timedelta(seconds=5))
    assert not limiter.hit(KEY, three, NOW + timedelta(seconds=30))
    # The kept hits are the latest three by time: when NOW leaves the window, the others
    # (5 s, 20 s, 21 s, 30 s) still fill it.
    assert not limiter.hit(KEY, three, NOW + timedelta(hours=24, seconds=1))


def test_a_later_clocked_hit_keeps_hits_an_earlier_clocked_one_still_counts(
    limiter: RateLimiter,
) -> None:
    # Three hits just inside the window ending at NOW; a fast caller's hit at NOW + 2 s
    # is outside their window and allowed, but must not drop them: a slow caller's hit at
    # NOW, arriving after it, would make (NOW - 24 h, NOW] hold four.
    three = RateLimit(limit=3, window=timedelta(hours=24))
    early = NOW - timedelta(hours=24) + timedelta(seconds=1)
    for _ in range(3):
        assert limiter.hit(KEY, three, early)
    assert limiter.hit(KEY, three, NOW + timedelta(seconds=2))
    assert not limiter.hit(KEY, three, NOW)


def test_a_naive_time_is_refused(limiter: RateLimiter) -> None:
    with pytest.raises(ValueError, match="aware"):
        limiter.hit(KEY, DEVICE_LIMIT, NOW.replace(tzinfo=None))
