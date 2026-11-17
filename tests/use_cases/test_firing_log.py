"""The firing log (#42), against the fakes: which fired loads it lists, in what order, and
the range it reads."""

import logging
from datetime import date, timedelta

import pytest

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.errors import InvalidLogRange, UnknownItem
from asmbly_ceramics.domain.ids import ItemId, LoadId
from asmbly_ceramics.domain.limits import LOG_DEFAULT_AHEAD, LOG_DEFAULT_RANGE, LOG_RANGE_MAX
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.use_cases.firing_log import FiringKind, FiringLog
from tests.use_cases.conftest import World
from tests.use_cases.flows import ATHENA, GLAZE, HELIOS, STAFF_MEMBER, dropped_off

TODAY = date(2026, 11, 13)  # NOW, in Austin


@pytest.fixture
def log(world: World) -> FiringLog:
    return world.firing_log


def fired_on(world: World, on: date, *, kiln: ItemId = ATHENA, test: bool = False) -> LoadId:
    """A load dated `on`, fired an hour after the last one: a test with nothing in it, or a
    regular load holding one drop-off made through the form."""
    world.clock.advance(timedelta(hours=1))
    load = world.start_load(kiln, GLAZE, on, STAFF_MEMBER, test=test)
    if not test:
        number = len(world.records.drop_offs_in(set(DropOffState))) + 1
        drop_off = dropped_off(world, number, firing_type="glaze", glaze_type="house-dip-glaze")
        load = world.add_to_load(load.id, drop_off, confirmed=True, staff=STAFF_MEMBER)
    load = world.start_firing(load.id, load.version, STAFF_MEMBER)
    return world.mark_fired(load.id, load.version, STAFF_MEMBER).id


def ids(log_view_rows: object) -> list[LoadId]:
    assert isinstance(log_view_rows, tuple)
    return [row.load.id for row in log_view_rows]


def test_default_range_last_12_weeks(world: World, log: FiringLog, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    old = fired_on(world, TODAY - LOG_DEFAULT_RANGE - timedelta(days=1))
    first = fired_on(world, TODAY - LOG_DEFAULT_RANGE)
    last = fired_on(world, TODAY)
    caplog.clear()

    view = log(None, None, None, FiringKind.ALL)

    assert (view.start, view.end) == (TODAY - LOG_DEFAULT_RANGE, TODAY)
    assert ids(view.rows) == [last, first]
    assert old not in ids(view.rows)
    assert world.records.date_ranges[-1] == (
        TODAY - LOG_DEFAULT_RANGE,
        TODAY + timedelta(days=1) + LOG_DEFAULT_AHEAD,
    )
    assert caplog.records == []  # a read logs nothing


def test_default_range_lists_a_load_dated_after_today_and_already_fired(world: World, log: FiringLog) -> None:
    ahead = fired_on(world, TODAY + timedelta(days=3))
    too_far = fired_on(world, TODAY + LOG_DEFAULT_AHEAD + timedelta(days=1))

    view = log(None, None, None, FiringKind.ALL)

    assert view.end == TODAY
    assert ids(view.rows) == [ahead]
    assert too_far not in ids(view.rows)
    # A chosen end is read as chosen.
    assert ids(log(None, None, TODAY, FiringKind.ALL).rows) == []


def test_one_kiln(world: World, log: FiringLog) -> None:
    world.set_kiln_counts(HELIOS, "97", "251", world.studio().version, STAFF_MEMBER)
    fired_on(world, TODAY, kiln=ATHENA)
    helios = fired_on(world, TODAY, kiln=HELIOS)

    view = log(HELIOS, None, None, FiringKind.ALL)

    assert ids(view.rows) == [helios]
    [row] = view.rows
    assert (row.kiln, row.firing_type, row.cone) == ("Helios", "Glaze", "^6")
    assert (row.started_by, row.firing_started_by, row.fired_by) == (
        STAFF_MEMBER.username,
        STAFF_MEMBER.username,
        STAFF_MEMBER.username,
    )
    assert view.kiln == HELIOS
    assert view.counts is not None
    assert (view.counts.since_elements, view.counts.all_time) == (97, 251)


def test_all_kilns(world: World, log: FiringLog) -> None:
    athena = fired_on(world, TODAY, kiln=ATHENA)
    helios = fired_on(world, TODAY, kiln=HELIOS)
    view = log(None, None, None, FiringKind.ALL)
    assert ids(view.rows) == [helios, athena]
    assert view.counts is None


def test_tests_only(world: World, log: FiringLog) -> None:
    fired_on(world, TODAY)
    test = fired_on(world, TODAY, test=True)
    assert ids(log(None, None, None, FiringKind.TESTS).rows) == [test]


def test_regular_only(world: World, log: FiringLog) -> None:
    regular = fired_on(world, TODAY)
    fired_on(world, TODAY, test=True)
    assert ids(log(None, None, None, FiringKind.REGULAR).rows) == [regular]


def test_newest_fired_first(world: World, log: FiringLog) -> None:
    # Ordered by when each was fired, not by its date.
    later_date = fired_on(world, TODAY)
    earlier_date = fired_on(world, TODAY - timedelta(days=3))
    assert ids(log(None, None, None, FiringKind.ALL).rows) == [earlier_date, later_date]


def test_a_chosen_range_is_inclusive(world: World, log: FiringLog) -> None:
    before = fired_on(world, date(2026, 10, 31))
    first = fired_on(world, date(2026, 11, 1))
    last = fired_on(world, date(2026, 11, 5))
    after = fired_on(world, date(2026, 11, 6))

    view = log(None, date(2026, 11, 1), date(2026, 11, 5), FiringKind.ALL)

    assert ids(view.rows) == [last, first]
    assert {before, after}.isdisjoint(ids(view.rows))
    assert ids(log(None, None, date(2026, 11, 5), FiringKind.ALL).rows) == [last, first, before]
    assert ids(log(None, date(2026, 11, 6), None, FiringKind.ALL).rows) == [after]


def test_unknown_kiln(log: FiringLog) -> None:
    with pytest.raises(UnknownItem):
        log(ItemId("kiln-nine"), None, None, FiringKind.ALL)


def test_range_too_long(world: World, log: FiringLog) -> None:
    longest = log(None, TODAY - LOG_RANGE_MAX, TODAY, FiringKind.ALL)
    assert longest.start == TODAY - LOG_RANGE_MAX
    reads = len(world.records.date_ranges)
    with pytest.raises(InvalidLogRange):
        log(None, TODAY - LOG_RANGE_MAX - timedelta(days=1), TODAY, FiringKind.ALL)
    with pytest.raises(InvalidLogRange):
        log(None, None, date.max, FiringKind.ALL)
    with pytest.raises(InvalidLogRange):
        log(None, None, date.min, FiringKind.ALL)
    assert len(world.records.date_ranges) == reads  # refused before anything is read


def test_range_backwards(log: FiringLog) -> None:
    with pytest.raises(InvalidLogRange):
        log(None, TODAY, TODAY - timedelta(days=1), FiringKind.ALL)
    assert log(None, TODAY, TODAY, FiringKind.ALL).rows == ()


def test_deleted_and_unfired_loads_left_out(world: World, log: FiringLog) -> None:
    loading = world.start_load(ATHENA, GLAZE, TODAY, STAFF_MEMBER, test=True)
    firing = world.start_load(ATHENA, GLAZE, TODAY, STAFF_MEMBER, test=True)
    world.start_firing(firing.id, firing.version, STAFF_MEMBER)
    deleted = world.start_load(ATHENA, GLAZE, TODAY, STAFF_MEMBER, test=True)
    world.delete_load(deleted.id, deleted.version, STAFF_MEMBER)
    fired = fired_on(world, TODAY, test=True)

    assert ids(log(None, None, None, FiringKind.ALL).rows) == [fired]
    assert loading.id != fired


def test_a_store_that_cant_be_reached(world: World, log: FiringLog) -> None:
    world.studio()
    world.records.fail_reads_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        log(None, None, None, FiringKind.ALL)
