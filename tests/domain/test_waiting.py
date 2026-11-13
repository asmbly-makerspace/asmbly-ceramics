from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import cast

import pytest

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.limits import OVERDUE_AFTER, STUDIO_TZ
from asmbly_ceramics.domain.waiting import days_waiting, is_overdue, oldest_first, totals, waiting_order
from tests.domain.builders import NOW, a_drop_off

BISQUE, GLAZE = ItemId("bisque"), ItemId("glaze")
DIP, COMMERCIAL = ItemId("house-dip-glaze"), ItemId("commercial-glaze")
DAY = timedelta(days=1)


def at_austin(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=STUDIO_TZ)


def made(number: int, days_ago: float, pieces: int = 3, glaze: ItemId | None = None) -> DropOff:
    drop_off = replace(a_drop_off(number, at=NOW - timedelta(days=days_ago)), pieces=pieces)
    if glaze is not None:
        drop_off = replace(drop_off, firing_type=GLAZE, glaze_type=glaze)
    return drop_off


def test_waiting_is_oldest_first() -> None:
    same_time = NOW - 2 * DAY
    drop_offs = [
        made(1, days_ago=1),
        a_drop_off(5, at=same_time),
        made(2, days_ago=10),
        a_drop_off(4, at=same_time),
        a_drop_off(3, DropOffState.IN_LOAD, at=NOW - 30 * DAY),
        a_drop_off(6, DropOffState.REJECTED, at=NOW - 30 * DAY),
        a_drop_off(7, DropOffState.FIRED, at=NOW - 30 * DAY),
        a_drop_off(8, DropOffState.CLOSED, at=NOW - 30 * DAY),
    ]
    ordered = waiting_order(drop_offs)
    # Oldest first; two made at the same time go by ID; only waiting ones are listed.
    assert [d.id for d in ordered] == [DropOffId(2), DropOffId(4), DropOffId(5), DropOffId(1)]


def test_oldest_first_orders_any_drop_offs() -> None:
    # Any states, unlike waiting_order: what a search or the overdue list sorts.
    drop_offs = [
        made(3, days_ago=1),
        a_drop_off(2, DropOffState.FIRED, at=NOW - 5 * DAY),
        a_drop_off(1, DropOffState.REJECTED, at=NOW - 5 * DAY),
    ]
    assert [d.id for d in oldest_first(drop_offs)] == [DropOffId(1), DropOffId(2), DropOffId(3)]
    assert waiting_order(drop_offs) == oldest_first([drop_offs[0]])


def test_waiting_order_sorts_ids_by_number_not_text() -> None:
    ordered = waiting_order([a_drop_off(10), a_drop_off(9)])
    assert [d.id for d in ordered] == [DropOffId(9), DropOffId(10)]


def test_totals_count_pieces_per_firing_type_and_glaze() -> None:
    drop_offs = [
        made(1, 1, pieces=3),
        made(2, 1, pieces=5),
        made(3, 1, pieces=2, glaze=DIP),
        made(4, 1, pieces=4, glaze=DIP),
        made(5, 1, pieces=1, glaze=COMMERCIAL),
        replace(a_drop_off(6, DropOffState.IN_LOAD), pieces=50),  # not waiting: not counted
        replace(a_drop_off(7, DropOffState.REJECTED), pieces=50),
    ]
    result = totals(drop_offs, NOW)
    assert dict(result.drop_offs) == {BISQUE: 2, GLAZE: 3}
    assert dict(result.pieces) == {BISQUE: 8, GLAZE: 7}
    assert dict(result.pieces_by_glaze) == {DIP: 6, COMMERCIAL: 1}
    assert result.overdue == 0


def test_totals_of_nothing_are_empty() -> None:
    result = totals([], NOW)
    assert dict(result.drop_offs) == dict(result.pieces) == dict(result.pieces_by_glaze) == {}
    assert result.overdue == 0


def test_totals_are_read_only() -> None:
    result = totals([made(1, 1)], NOW)
    assert isinstance(result.pieces, MappingProxyType)
    with pytest.raises(TypeError):
        cast("dict[ItemId, int]", result.pieces)[BISQUE] = 0


def test_overdue_at_60_days_waiting_not_59() -> None:
    assert timedelta(days=60) == OVERDUE_AFTER
    assert not is_overdue(made(1, days_ago=59), NOW)
    assert is_overdue(a_drop_off(1, at=NOW - OVERDUE_AFTER), NOW)
    assert is_overdue(made(1, days_ago=61), NOW)
    result = totals([made(1, 59), made(2, 60), made(3, 90)], NOW)
    assert result.overdue == 2


def test_overdue_counts_austin_days_not_elapsed_hours() -> None:
    # Made at 23:30 Austin time 60 days ago: overdue from midnight, though fewer than
    # 60 x 24 hours have passed; made at 00:10 on the 59th day back, not yet overdue.
    now = at_austin(2026, 11, 13, 0, 5)
    late = a_drop_off(1, at=at_austin(2026, 9, 14, 23, 30))
    assert now - late.created_at < OVERDUE_AFTER
    assert days_waiting(late, now) == 60
    assert is_overdue(late, now)
    early = a_drop_off(2, at=at_austin(2026, 9, 15, 0, 10))
    assert days_waiting(early, now) == 59
    assert not is_overdue(early, now)
    assert totals([late, early], now).overdue == 1


def test_days_waiting_are_whole_austin_days() -> None:
    made_at = at_austin(2026, 11, 12, 23, 59)
    drop_off = a_drop_off(1, at=made_at)
    assert days_waiting(drop_off, made_at) == 0
    assert days_waiting(drop_off, at_austin(2026, 11, 12, 23, 59, 59)) == 0
    # One minute later it is the next day in Austin: one day waiting.
    assert days_waiting(drop_off, made_at + timedelta(minutes=1)) == 1
    assert days_waiting(drop_off, at_austin(2026, 11, 13, 23, 59)) == 1
    assert days_waiting(drop_off, at_austin(2026, 11, 14, 0, 0)) == 2
    # Austin's day, not UTC's: 19:00 in Austin is already the next day in UTC.
    evening = a_drop_off(2, at=at_austin(2026, 11, 12, 19, 0))
    assert evening.created_at.astimezone(UTC).date() == date(2026, 11, 13)
    assert days_waiting(evening, at_austin(2026, 11, 12, 23, 0)) == 0
    # The same answer for a `now` in any time zone.
    assert days_waiting(drop_off, (made_at + timedelta(minutes=1)).astimezone(UTC)) == 1


def test_days_waiting_across_a_daylight_saving_change() -> None:
    # Austin's clocks went back an hour on 2026-11-01: a calendar day is still one day,
    # though 2026-10-31 to 2026-11-01 is 25 hours long.
    before = a_drop_off(1, at=at_austin(2026, 10, 31, 0, 30))
    assert days_waiting(before, at_austin(2026, 11, 1, 0, 15)) == 1
    assert days_waiting(before, at_austin(2026, 11, 1, 23, 59)) == 1
    assert days_waiting(before, at_austin(2026, 11, 2, 0, 0)) == 2
    # And forward on 2026-03-08: a 23-hour day.
    spring = a_drop_off(2, at=at_austin(2026, 3, 7, 23, 30))
    assert days_waiting(spring, at_austin(2026, 3, 8, 23, 45)) == 1
    assert days_waiting(spring, at_austin(2026, 3, 9, 0, 0)) == 2


@pytest.mark.parametrize(
    "state", [DropOffState.IN_LOAD, DropOffState.FIRED, DropOffState.REJECTED, DropOffState.CLOSED]
)
def test_only_a_waiting_drop_off_is_overdue(state: DropOffState) -> None:
    assert not is_overdue(a_drop_off(1, state, at=NOW - 100 * DAY), NOW)


def test_naive_times_are_refused() -> None:
    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="aware"):
        days_waiting(made(1, 1), naive)
    with pytest.raises(ValueError, match="aware"):
        is_overdue(made(1, 1), naive)
    with pytest.raises(ValueError, match="aware"):
        totals([], naive)
