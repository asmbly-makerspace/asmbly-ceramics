"""`WeeklyCounts` (#7), against the fakes."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from asmbly_ceramics.domain.counts import Week
from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.load import LoadStatus
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import Put
from tests.domain.builders import NOW, a_drop_off, a_load
from tests.use_cases.conftest import World

MONDAY = date(2026, 11, 9)  # NOW is Friday 13 November


def test_this_weeks_counts_by_firing_type_kiln_and_reason(world: World) -> None:
    world.studio()
    last_week = NOW - timedelta(days=7)
    # A load dated Sunday 8 November and fired overnight into Monday 9 November, Austin
    # time, counts in this week.
    overnight = replace(
        a_load(1, LoadStatus.FIRED, kiln="helios", at=last_week),
        date=date(2026, 11, 8),
        fired_at=datetime(2026, 11, 9, 7, tzinfo=UTC),  # 01:00 Monday in Austin
    )
    world.records.commit(
        [
            Put(a_drop_off(1)),
            Put(replace(a_drop_off(2), firing_type=ItemId("glaze"), pieces=5)),
            Put(a_drop_off(3, at=last_week)),
            Put(a_drop_off(4, DropOffState.REJECTED, reason="has-glaze-issues")),
            Put(a_drop_off(5, DropOffState.CLOSED, reason="other")),
            Put(a_drop_off(6, DropOffState.REJECTED, at=last_week, reason="other")),
            Put(a_load(2, LoadStatus.FIRED, kiln="athena")),
            Put(a_load(3, LoadStatus.FIRING, kiln="athena")),
            Put(a_load(4, LoadStatus.FIRED, kiln="vulcan", at=last_week)),
            Put(overnight),
        ]
    )

    view = world.counts()

    assert view.counts.week == Week(MONDAY)
    assert dict(view.counts.drop_offs) == {ItemId("bisque"): 3, ItemId("glaze"): 1}
    assert dict(view.counts.pieces) == {ItemId("bisque"): 9, ItemId("glaze"): 5}
    assert dict(view.counts.loads) == {ItemId("athena"): 1, ItemId("helios"): 1}
    assert dict(view.counts.rejections) == {ItemId("has-glaze-issues"): 1, ItemId("other"): 1}
    assert view.names[CatalogList.KILNS, ItemId("helios")] == "Helios"
    assert view.names[CatalogList.REASONS, ItemId("has-glaze-issues")] == "Has glaze issues"
    assert world.counts(MONDAY - timedelta(days=1)).counts.week == Week(MONDAY - timedelta(days=7))
    assert dict(world.counts(MONDAY - timedelta(days=1)).counts.loads) == {ItemId("vulcan"): 1}


def test_the_week_is_austins_late_on_sunday(world: World) -> None:
    sunday_night = datetime(2026, 11, 16, 5, 30, tzinfo=UTC)  # 23:30 Sunday 15 November in Austin
    world.clock.advance(sunday_night - NOW)
    assert sunday_night.astimezone(STUDIO_TZ).weekday() == 6
    assert world.counts().counts.week == Week(MONDAY)


def test_overdue_drop_offs_are_listed_oldest_first(world: World) -> None:
    world.studio()
    world.records.commit(
        [
            Put(a_drop_off(1, at=NOW - timedelta(days=61))),
            Put(a_drop_off(2, at=NOW - timedelta(days=70))),
            Put(a_drop_off(3, at=NOW - timedelta(days=59))),
            Put(a_drop_off(4, DropOffState.REJECTED, at=NOW - timedelta(days=90))),
        ]
    )

    view = world.counts()

    assert [row.drop_off.id for row in view.overdue] == [DropOffId(2), DropOffId(1)]
    assert all(row.overdue for row in view.overdue)


def test_counts_raise_when_the_store_cant_be_reached(world: World) -> None:
    world.studio()
    world.records.fail_reads_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        world.counts()
