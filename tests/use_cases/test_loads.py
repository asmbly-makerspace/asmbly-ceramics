"""The load use cases (#4), against the fakes: what is stored, queued and logged."""

import logging
from datetime import date, timedelta

import pytest

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus, claim
from asmbly_ceramics.domain.errors import (
    AlreadyFired,
    AlreadyInLoad,
    EmptyLoad,
    FiringTypeLocked,
    FiringTypeMismatch,
    ItemRetired,
    LoadNotLoading,
    NotFound,
    NotInLoad,
    NotWaiting,
    UnknownItem,
    WrongLoadStatus,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import STALE_SENDING_AFTER, STUDIO_TZ
from asmbly_ceramics.domain.load import LoadStatus
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.errors import IdsUnavailable, RecordsUnavailable
from asmbly_ceramics.ports.records import Conflict, Update
from asmbly_ceramics.use_cases.reject import RejectRequest
from tests.domain.builders import NOW, STAFF, TEST_MESSAGE
from tests.use_cases.conftest import World
from tests.use_cases.flows import (
    ATHENA,
    BISQUE,
    GLAZE,
    HELIOS,
    STAFF_MEMBER,
    dropped_off,
    email_of,
    fired,
    loaded,
    send_all,
    version,
)

AC_1, AC_2, AC_3 = DropOffId(1), DropOffId(2), DropOffId(3)
L_1, L_2 = LoadId(1), LoadId(2)


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, object]]:
    return [vars(r) for r in caplog.records if r.getMessage() == name]


def state(world: World, id: DropOffId) -> DropOffState:
    drop_off = world.records.drop_off(id)
    assert drop_off is not None
    return drop_off.state


def firing(world: World, *drop_offs: DropOffId) -> LoadId:
    load_id = loaded(world, *drop_offs)
    world.start_firing(load_id, version(world, load_id), STAFF_MEMBER)
    return load_id


# Starting and changing a load


def test_start_load_defaults_to_today_in_austin(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    late = NOW.replace(hour=4)  # 04:00 UTC is still the day before in Austin
    world.clock.advance(late - NOW)

    load = world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER)

    assert load.date == late.astimezone(STUDIO_TZ).date() == date(2026, 11, 12)
    assert (load.id, load.kiln, load.status, load.started_by, load.version) == (
        L_1,
        HELIOS,
        LoadStatus.LOADING,
        STAFF,
        1,
    )
    assert world.records.load(L_1) == load
    [event] = events(caplog, "load_started")
    assert (event["load_id"], event["user"]) == ("L-1", STAFF)


def test_start_load_on_a_chosen_date(world: World) -> None:
    load = world.start_load(ATHENA, GLAZE, date(2026, 11, 20), STAFF_MEMBER)
    assert (load.date, load.firing_type) == (date(2026, 11, 20), GLAZE)


def test_start_load_refuses_a_retired_kiln(world: World) -> None:
    world.retire_item(CatalogList.KILNS, ATHENA, world.studio().version, STAFF_MEMBER)

    with pytest.raises(ItemRetired):
        world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    with pytest.raises(UnknownItem):
        world.start_load(ItemId("kiln-nine"), BISQUE, None, STAFF_MEMBER)
    # A refused load spends no number: the next one is still L-1.
    assert world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER).id == L_1


def test_change_load_changes_kiln_and_date_with_drop_offs_in_it(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)

    changed = world.change_load(
        load_id, HELIOS, BISQUE, date(2026, 11, 14), version(world, load_id), STAFF_MEMBER
    )

    assert (changed.kiln, changed.date, changed.members) == (HELIOS, date(2026, 11, 14), (AC_1,))
    assert world.records.load(load_id) == changed
    [event] = events(caplog, "load_changed")
    assert (event["load_id"], event["user"]) == ("L-1", STAFF)


def test_change_load_refuses_a_new_firing_type_once_it_has_drop_offs(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    commits = len(world.records.commits)

    with pytest.raises(FiringTypeLocked):
        world.change_load(load_id, ATHENA, GLAZE, NOW.date(), version(world, load_id), STAFF_MEMBER)

    assert len(world.records.commits) == commits


def test_change_load_changes_the_firing_type_of_an_empty_load(world: World) -> None:
    load_id = loaded(world)

    changed = world.change_load(load_id, ATHENA, GLAZE, NOW.date(), version(world, load_id), STAFF_MEMBER)

    assert changed.firing_type == GLAZE


def test_change_load_refuses_a_load_that_isnt_loading(world: World) -> None:
    dropped_off(world, 1)
    load_id = firing(world, AC_1)
    commits = len(world.records.commits)

    with pytest.raises(LoadNotLoading):
        world.change_load(load_id, HELIOS, BISQUE, NOW.date(), version(world, load_id), STAFF_MEMBER)
    world.mark_fired(load_id, version(world, load_id), STAFF_MEMBER)
    commits = len(world.records.commits)
    with pytest.raises(LoadNotLoading):
        world.change_load(load_id, HELIOS, BISQUE, NOW.date(), version(world, load_id), STAFF_MEMBER)

    assert len(world.records.commits) == commits


def test_change_load_with_a_stale_version_is_a_conflict(world: World) -> None:
    load_id = loaded(world)
    with pytest.raises(Conflict):
        world.change_load(load_id, HELIOS, BISQUE, NOW.date(), version(world, load_id) - 1, STAFF_MEMBER)


def test_an_unknown_load_is_not_found(world: World) -> None:
    dropped_off(world, 1)
    with pytest.raises(NotFound):
        world.add_to_load(LoadId(9), AC_1, confirmed=False, staff=STAFF_MEMBER)
    with pytest.raises(NotFound):
        world.view_load(LoadId(9))
    load_id = loaded(world)
    with pytest.raises(NotFound):
        world.add_to_load(load_id, DropOffId(99), confirmed=False, staff=STAFF_MEMBER)


# Adding and removing


def test_add_by_id_moves_it_from_waiting_into_the_load(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    dropped_off(world, 1)
    load_id = loaded(world)

    load = world.add_to_load(load_id, AC_1, confirmed=False, staff=STAFF_MEMBER)

    assert load.members == (AC_1,)
    assert world.records.load(load_id) == load
    stored = world.records.drop_off(AC_1)
    assert stored is not None
    assert (stored.state, stored.load_id) == (DropOffState.IN_LOAD, load_id)
    assert world.waiting().rows == ()
    [event] = events(caplog, "added_to_load")
    assert (event["load_id"], event["drop_off_id"], event["user"]) == ("L-1", "AC-1", STAFF)


def test_add_by_a_name_search_finds_only_waiting_drop_offs(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)
    load_id = loaded(world, AC_2)

    [row] = world.find("test pers", waiting_only=True).rows
    world.add_to_load(load_id, row.drop_off.id, confirmed=False, staff=STAFF_MEMBER)

    assert world.view_load(load_id).load.members == (AC_2, AC_1)


def test_add_refuses_a_drop_off_that_isnt_waiting_with_the_reason(world: World) -> None:
    dropped_off(world, 1)
    world.reject(RejectRequest(AC_1, ItemId("other"), TEST_MESSAGE, version=1, staff=STAFF_MEMBER))
    load_id = loaded(world)
    commits = len(world.records.commits)

    with pytest.raises(NotWaiting) as refused:
        world.add_to_load(load_id, AC_1, confirmed=True, staff=STAFF_MEMBER)

    assert refused.value.message == "AC-1 isn't waiting: it is rejected."
    assert len(world.records.commits) == commits


def test_add_refuses_one_already_in_another_load_naming_it(world: World) -> None:
    dropped_off(world, 1)
    loaded(world, AC_1)
    other = loaded(world)
    commits = len(world.records.commits)

    with pytest.raises(AlreadyInLoad) as refused:
        world.add_to_load(other, AC_1, confirmed=True, staff=STAFF_MEMBER)

    assert refused.value.message == "AC-1 is already in load L-1."
    assert len(world.records.commits) == commits
    assert world.view_load(other).members == ()


def test_a_different_firing_type_asks_then_adds_when_confirmed(world: World) -> None:
    dropped_off(world, 1, firing_type="glaze", glaze_type="house-dip-glaze")
    load_id = loaded(world)  # a bisque load
    commits = len(world.records.commits)

    with pytest.raises(FiringTypeMismatch) as asked:
        world.add_to_load(load_id, AC_1, confirmed=False, staff=STAFF_MEMBER)
    assert (asked.value.drop_off_firing_type, asked.value.load_firing_type) == (GLAZE, BISQUE)
    assert len(world.records.commits) == commits

    load = world.add_to_load(load_id, AC_1, confirmed=True, staff=STAFF_MEMBER)
    assert load.members == (AC_1,)


def test_remove_puts_it_back_in_the_waiting_list(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    dropped_off(world, 1)
    dropped_off(world, 2)
    load_id = loaded(world, AC_1, AC_2)

    load = world.remove_from_load(load_id, AC_1, STAFF_MEMBER)

    assert load.members == (AC_2,)
    assert state(world, AC_1) is DropOffState.WAITING
    assert [row.drop_off.id for row in world.waiting().rows] == [AC_1]
    [event] = events(caplog, "removed_from_load")
    assert (event["load_id"], event["drop_off_id"]) == ("L-1", "AC-1")
    with pytest.raises(NotInLoad):
        world.remove_from_load(load_id, AC_1, STAFF_MEMBER)


def test_nothing_can_be_added_or_removed_once_firing(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)
    load_id = firing(world, AC_1)
    commits = len(world.records.commits)

    with pytest.raises(LoadNotLoading):
        world.add_to_load(load_id, AC_2, confirmed=True, staff=STAFF_MEMBER)
    with pytest.raises(LoadNotLoading):
        world.remove_from_load(load_id, AC_1, STAFF_MEMBER)

    assert len(world.records.commits) == commits


def test_two_staff_adding_at_once_one_gets_a_conflict(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)
    load_id = loaded(world)
    stale = world.records.load(load_id)
    assert stale is not None
    world.add_to_load(load_id, AC_1, confirmed=False, staff=STAFF_MEMBER)
    # The second staff member read the load before the first add landed.
    read = world.records.load

    def stale_read(id: LoadId) -> object:
        return stale if id == load_id else read(id)

    world.records.load = stale_read  # type: ignore[assignment,method-assign]  # the fake read replaced to stage a race
    with pytest.raises(Conflict):
        world.add_to_load(load_id, AC_2, confirmed=False, staff=STAFF_MEMBER)
    world.records.load = read  # type: ignore[method-assign]  # the fake read replaced to stage a race

    assert world.view_load(load_id).load.members == (AC_1,)
    assert state(world, AC_2) is DropOffState.WAITING


# Firing


def test_start_firing_refuses_an_empty_load_and_a_stale_version(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    load_id = loaded(world)
    with pytest.raises(EmptyLoad):
        world.start_firing(load_id, version(world, load_id), STAFF_MEMBER)
    dropped_off(world, 1)
    world.add_to_load(load_id, AC_1, confirmed=False, staff=STAFF_MEMBER)
    with pytest.raises(Conflict):
        world.start_firing(load_id, version(world, load_id) - 1, STAFF_MEMBER)

    load = world.start_firing(load_id, version(world, load_id), STAFF_MEMBER)

    assert load.status is LoadStatus.FIRING
    assert [e["load_id"] for e in events(caplog, "load_firing")] == ["L-1"]
    with pytest.raises(WrongLoadStatus):
        world.start_firing(load_id, version(world, load_id), STAFF_MEMBER)


def test_mark_fired_marks_every_member_and_queues_one_ready_email_each_in_one_commit(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    for number in (1, 2, 3):
        dropped_off(world, number)
    load_id = firing(world, AC_1, AC_2, AC_3)
    commits = len(world.records.commits)

    load = world.mark_fired(load_id, version(world, load_id), STAFF_MEMBER)

    assert (load.status, load.fired_at) == (LoadStatus.FIRED, NOW)
    assert len(world.records.commits) == commits + 1
    commit = world.records.commits[-1]
    assert sorted(type(change.item).__name__ for change in commit) == ["DropOff"] * 3 + ["Email"] * 3 + [
        "Load"
    ]
    for id in (AC_1, AC_2, AC_3):
        assert state(world, id) is DropOffState.FIRED
        ready = [e for e in world.records.emails_for(id) if e.kind is EmailKind.READY]
        assert [e.status for e in ready] == [EmailStatus.PENDING]
    [event] = events(caplog, "load_fired")
    assert (event["load_id"], event["count"], event["user"]) == ("L-1", 3, STAFF)


def test_marking_fired_again_queues_nothing(world: World) -> None:
    dropped_off(world, 1)
    load_id = fired(world, AC_1)
    commits = len(world.records.commits)

    with pytest.raises(AlreadyFired):
        world.mark_fired(load_id, version(world, load_id), STAFF_MEMBER)
    # A second click, from a page that still shows the version before the fire.
    with pytest.raises(AlreadyFired):
        world.mark_fired(load_id, version(world, load_id) - 1, STAFF_MEMBER)

    assert len(world.records.commits) == commits
    assert len([e for e in world.records.emails_for(AC_1) if e.kind is EmailKind.READY]) == 1


def test_mark_fired_refuses_a_load_still_loading(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    with pytest.raises(WrongLoadStatus):
        world.mark_fired(load_id, version(world, load_id), STAFF_MEMBER)


def test_a_fired_load_and_its_drop_offs_cant_change(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)
    load_id = fired(world, AC_1)
    commits = len(world.records.commits)

    with pytest.raises(LoadNotLoading):
        world.add_to_load(load_id, AC_2, confirmed=True, staff=STAFF_MEMBER)
    with pytest.raises(LoadNotLoading):
        world.remove_from_load(load_id, AC_1, STAFF_MEMBER)
    other = loaded(world)
    with pytest.raises(NotWaiting):
        world.add_to_load(other, AC_1, confirmed=True, staff=STAFF_MEMBER)
    fired_version = world.records.drop_off(AC_1)
    assert fired_version is not None
    with pytest.raises(NotWaiting):
        world.reject(
            RejectRequest(
                AC_1, ItemId("other"), TEST_MESSAGE, version=fired_version.version, staff=STAFF_MEMBER
            )
        )

    assert len(world.records.commits) == commits + 1  # only the new load
    drop_off = world.records.drop_off(AC_1)
    assert drop_off is not None
    assert (drop_off.state, drop_off.load_id) == (DropOffState.FIRED, load_id)


# Viewing


def test_view_load_counts_drop_offs_pieces_and_sent_emails_and_lists_failures(world: World) -> None:
    for number in (1, 2, 3):
        dropped_off(world, number)
    send_all(world)
    load_id = fired(world, AC_1, AC_2, AC_3)
    world.send_email(AC_1, EmailKind.READY, "")
    world.mailer.fail_with = "MessageRejected"
    world.send_email(AC_2, EmailKind.READY, "")

    view = world.view_load(load_id)

    assert (view.kiln, view.firing_type) == ("Athena", "Bisque")
    assert [d.id for d in view.members] == [AC_1, AC_2, AC_3]
    assert (view.total_drop_offs, view.total_pieces, view.sent) == (3, 9, 1)
    assert set(view.emails) == {AC_1, AC_2, AC_3}
    assert [(e.drop_off_id, e.error_code) for e in view.needing_attention] == [(AC_2, "MessageRejected")]
    assert view.waiting == ()


def test_view_load_lists_an_email_stuck_sending(world: World) -> None:
    dropped_off(world, 1)
    load_id = fired(world, AC_1)
    ready = email_of(world, AC_1, EmailKind.READY)
    world.records.commit([Update(claim(ready, NOW))])
    assert world.view_load(load_id).needing_attention == ()
    world.clock.advance(STALE_SENDING_AFTER + timedelta(seconds=1))

    assert [e.drop_off_id for e in world.view_load(load_id).needing_attention] == [AC_1]


def test_view_load_waiting_list_defaults_to_the_load_firing_type(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2, firing_type="glaze", glaze_type="house-dip-glaze")
    load_id = loaded(world)

    assert [row.drop_off.id for row in world.view_load(load_id).waiting] == [AC_1]
    assert [row.drop_off.id for row in world.view_load(load_id, all_firing_types=True).waiting] == [
        AC_1,
        AC_2,
    ]


def test_past_loads_are_listed_with_their_contents(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)
    old = fired(world, AC_1)
    world.clock.advance(timedelta(days=1))
    recent = fired(world, AC_2)
    world.clock.advance(timedelta(days=1))
    open_load = loaded(world)
    world.clock.advance(
        timedelta(weeks=8) - timedelta(days=2, hours=1)
    )  # L-1 fired 1 hour short of 8 weeks ago

    loading, past = world.list_loads()

    assert [load.id for load in loading] == [open_load]
    assert [load.id for load in past] == [recent, old]
    world.clock.advance(timedelta(hours=2))
    assert [load.id for load in world.list_loads()[1]] == [recent]
    # Older loads stay viewable by their ID, with what was in them.
    assert [d.id for d in world.view_load(old).members] == [AC_1]


def test_a_store_that_cant_be_reached_stores_nothing(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world)
    commits = len(world.records.commits)

    world.ids.fail_with = IdsUnavailable("InternalServerError")
    with pytest.raises(IdsUnavailable):
        world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER)
    world.ids.fail_with = None
    world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        world.add_to_load(load_id, AC_1, confirmed=False, staff=STAFF_MEMBER)
    world.records.fail_reads_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        world.view_load(load_id)
    with pytest.raises(RecordsUnavailable):
        world.list_loads()

    assert len(world.records.commits) == commits
    world.records.fail_reads_with = None
    assert state(world, AC_1) is DropOffState.WAITING


def test_two_staff_marking_fired_at_once_queues_one_ready_email_each(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)
    load_id = firing(world, AC_1, AC_2)
    stale = world.records.load(load_id)
    assert stale is not None
    world.mark_fired(load_id, stale.version, STAFF_MEMBER)
    # The second click read the load while it was still firing, then its members fired.
    read = world.records.load
    reads = 0

    def first_read_stale(id: LoadId) -> object:
        nonlocal reads
        reads += 1
        return stale if reads == 1 else read(id)

    world.records.load = first_read_stale  # type: ignore[assignment,method-assign]  # the fake read replaced to stage a race
    with pytest.raises(AlreadyFired):
        world.mark_fired(load_id, stale.version, STAFF_MEMBER)
    world.records.load = read  # type: ignore[method-assign]  # restored

    for id in (AC_1, AC_2):
        assert len([e for e in world.records.emails_for(id) if e.kind is EmailKind.READY]) == 1


def test_view_load_of_a_past_load_whose_drop_offs_closed(world: World) -> None:
    dropped_off(world, 1)
    load_id = fired(world, AC_1)
    send_all(world)
    world.clock.advance(timedelta(days=30))
    assert world.close().closed == (AC_1,)

    view = world.view_load(load_id)

    assert (view.total_drop_offs, view.total_pieces, view.sent) == (1, 3, 1)
    assert view.members[0].contact is None
    assert view.members[0].photos == ()
    assert view.needing_attention == ()
