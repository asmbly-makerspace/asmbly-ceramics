from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from asmbly_ceramics.domain.counts import Week, count_week, week_containing
from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.load import LoadStatus
from tests.domain.builders import a_drop_off, a_load

MONDAY = date(2026, 11, 9)
WEEK = Week(MONDAY)


def austin(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=STUDIO_TZ)


def test_a_week_runs_monday_to_sunday_austin_time() -> None:
    assert week_containing(MONDAY + timedelta(days=6)) == WEEK
    assert week_containing(MONDAY) == WEEK
    assert WEEK.sunday() == date(2026, 11, 15)
    start, end = WEEK.utc_bounds()
    assert start == datetime(2026, 11, 9, 6, tzinfo=UTC)  # CST is UTC-6
    assert end == datetime(2026, 11, 16, 6, tzinfo=UTC)

    late_sunday = austin(WEEK.sunday(), 23, 30)  # Monday 05:30 in UTC
    early_monday = austin(MONDAY + timedelta(days=7), 0, 10)  # Monday 06:10 in UTC
    assert late_sunday.astimezone(UTC).weekday() == early_monday.astimezone(UTC).weekday() == 0
    assert WEEK.holds(late_sunday)
    assert not WEEK.holds(early_monday)
    assert week_containing(early_monday.date()) == Week(MONDAY + timedelta(days=7))


def test_a_week_starts_on_a_monday_and_takes_aware_times() -> None:
    with pytest.raises(ValueError, match="Monday"):
        Week(MONDAY + timedelta(days=1))
    with pytest.raises(ValueError, match="aware"):
        WEEK.holds(datetime(2026, 11, 10, 12))  # noqa: DTZ001 - the naive time is the point


def test_a_week_across_the_change_of_daylight_saving_time() -> None:
    # The clocks go forward on Sunday 8 March 2026: that week is an hour short in UTC.
    start, end = Week(date(2026, 3, 2)).utc_bounds()
    assert (start.hour, end.hour, end - start) == (6, 5, timedelta(days=7, hours=-1))


def test_counts_by_firing_type_kiln_and_reason() -> None:
    inside = austin(MONDAY, 9)
    outside = inside - timedelta(days=1)
    bisque = replace(a_drop_off(1, at=inside), pieces=3)
    glaze = replace(a_drop_off(2, at=inside), firing_type=ItemId("glaze"), pieces=5)
    earlier = a_drop_off(3, at=outside)
    loads = [
        a_load(1, LoadStatus.FIRED, kiln="athena", at=inside),
        a_load(2, LoadStatus.FIRED, kiln="athena", at=inside + timedelta(days=2)),
        a_load(3, LoadStatus.FIRED, kiln="helios", at=inside),
        a_load(4, LoadStatus.FIRED, kiln="vulcan", at=outside),
        a_load(5, LoadStatus.FIRING, kiln="vulcan", at=inside),
    ]
    rejected = [
        a_drop_off(4, DropOffState.REJECTED, at=inside, reason="other"),
        a_drop_off(5, DropOffState.REJECTED, at=inside, reason="other"),
        a_drop_off(6, DropOffState.REJECTED, at=inside, reason="needs-more-time-to-dry"),
        a_drop_off(7, DropOffState.REJECTED, at=outside, reason="other"),
    ]

    counts = count_week(WEEK, [bisque, glaze, earlier], loads, rejected)

    assert counts.week == WEEK
    assert dict(counts.drop_offs) == {ItemId("bisque"): 1, ItemId("glaze"): 1}
    assert dict(counts.pieces) == {ItemId("bisque"): 3, ItemId("glaze"): 5}
    assert dict(counts.loads) == {ItemId("athena"): 2, ItemId("helios"): 1}
    assert dict(counts.rejections) == {ItemId("other"): 2, ItemId("needs-more-time-to-dry"): 1}


def test_closed_drop_offs_still_count() -> None:
    inside = austin(MONDAY, 9)
    closed = a_drop_off(1, DropOffState.CLOSED, at=inside, reason="other")
    assert closed.contact is None

    counts = count_week(WEEK, [closed], [], [closed])

    assert dict(counts.drop_offs) == {ItemId("bisque"): 1}
    assert dict(counts.pieces) == {ItemId("bisque"): closed.pieces}
    assert dict(counts.rejections) == {ItemId("other"): 1}


def test_an_undone_rejection_doesnt_count() -> None:
    undone = a_drop_off(1, at=austin(MONDAY, 9))  # waiting again: no rejection
    assert count_week(WEEK, [], [], [undone]).rejections == {}
