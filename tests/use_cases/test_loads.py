"""The load use cases (#4), against the fakes: what is stored, queued and logged."""

import logging
from collections.abc import Callable
from datetime import date, timedelta

import pytest

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus, claim
from asmbly_ceramics.domain.errors import (
    AlreadyFired,
    AlreadyInLoad,
    EmptyLoad,
    FiredLoadNotDeletable,
    FiringTypeLocked,
    FiringTypeMismatch,
    InvalidRecord,
    ItemRetired,
    LoadFull,
    LoadNotLoading,
    NotFound,
    NotInLoad,
    NotWaiting,
    StepNotReached,
    StepTimeInFuture,
    StepTimeOutOfOrder,
    TooManyNotesToMove,
    UnknownItem,
    WrongLoadStatus,
)
from asmbly_ceramics.domain.firing import record_values
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId, NoteId
from asmbly_ceramics.domain.limits import (
    LOAD_CAPACITY,
    NUMBERS_DATE_MARGIN,
    NUMBERS_LOOKBACK,
    NUMBERS_READ_AHEAD,
    STALE_SENDING_AFTER,
    STUDIO_TZ,
)
from asmbly_ceramics.domain.load import LoadStatus, Step
from asmbly_ceramics.domain.notes import remove_note
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.errors import IdsUnavailable, RecordsUnavailable
from asmbly_ceramics.ports.records import MAX_CHANGES, Conflict, Put, Update
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.loads import NOTES_MOVED_MAX
from asmbly_ceramics.use_cases.reject import RejectRequest
from tests.domain.builders import NOW, STAFF, TEST_MESSAGE, a_drop_off, a_load, a_note, an_address
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
        load_id, HELIOS, BISQUE, date(2026, 11, 14), version(world, load_id), STAFF_MEMBER, test=False
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
        world.change_load(
            load_id, ATHENA, GLAZE, NOW.date(), version(world, load_id), STAFF_MEMBER, test=False
        )

    assert len(world.records.commits) == commits


def test_change_load_changes_the_firing_type_of_an_empty_load(world: World) -> None:
    load_id = loaded(world)

    changed = world.change_load(
        load_id, ATHENA, GLAZE, NOW.date(), version(world, load_id), STAFF_MEMBER, test=False
    )

    assert changed.firing_type == GLAZE


def test_change_load_refuses_a_load_that_isnt_loading(world: World) -> None:
    dropped_off(world, 1)
    load_id = firing(world, AC_1)
    commits = len(world.records.commits)

    with pytest.raises(LoadNotLoading):
        world.change_load(
            load_id, HELIOS, BISQUE, NOW.date(), version(world, load_id), STAFF_MEMBER, test=False
        )
    world.mark_fired(load_id, version(world, load_id), STAFF_MEMBER)
    commits = len(world.records.commits)
    with pytest.raises(LoadNotLoading):
        world.change_load(
            load_id, HELIOS, BISQUE, NOW.date(), version(world, load_id), STAFF_MEMBER, test=False
        )

    assert len(world.records.commits) == commits


def test_change_load_with_a_stale_version_is_a_conflict(world: World) -> None:
    load_id = loaded(world)
    with pytest.raises(Conflict):
        world.change_load(
            load_id, HELIOS, BISQUE, NOW.date(), version(world, load_id) - 1, STAFF_MEMBER, test=False
        )


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


def test_add_many_moves_every_one_in_a_single_commit(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    dropped_off(world, 1)
    dropped_off(world, 2)
    dropped_off(world, 3)
    load_id = loaded(world)
    commits = len(world.records.commits)

    load = world.add_many_to_load(load_id, [AC_2, AC_1, AC_2], staff=STAFF_MEMBER)

    assert load.members == (AC_2, AC_1)
    assert len(world.records.commits) == commits + 1
    assert [row.drop_off.id for row in world.waiting().rows] == [DropOffId(3)]
    assert [e["drop_off_id"] for e in events(caplog, "added_to_load")] == ["AC-2", "AC-1"]


def test_add_many_adds_none_when_one_is_refused(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2, firing_type="glaze", glaze_type="house-dip-glaze")
    load_id = loaded(world)
    commits = len(world.records.commits)

    with pytest.raises(FiringTypeMismatch) as asked:
        world.add_many_to_load(load_id, [AC_1, AC_2], staff=STAFF_MEMBER)

    assert asked.value.drop_off_id == AC_2
    assert len(world.records.commits) == commits
    assert world.view_load(load_id).members == ()


def test_add_many_with_none_given_changes_nothing(world: World) -> None:
    load_id = loaded(world)
    commits = len(world.records.commits)

    assert world.add_many_to_load(load_id, [], staff=STAFF_MEMBER).members == ()
    assert len(world.records.commits) == commits


def test_two_staff_adding_many_at_once_one_gets_a_conflict(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)
    dropped_off(world, 3)
    load_id = loaded(world)
    stale = world.records.load(load_id)
    world.add_to_load(load_id, AC_1, confirmed=False, staff=STAFF_MEMBER)
    read = world.records.load

    def stale_read(id: LoadId) -> object:
        return stale if id == load_id else read(id)

    world.records.load = stale_read  # type: ignore[assignment,method-assign]  # the fake read replaced to stage a race
    with pytest.raises(Conflict):
        world.add_many_to_load(load_id, [AC_2, DropOffId(3)], staff=STAFF_MEMBER)
    world.records.load = read  # type: ignore[method-assign]  # the fake read replaced to stage a race

    assert world.view_load(load_id).load.members == (AC_1,)
    assert [row.drop_off.id for row in world.waiting().rows] == [AC_2, DropOffId(3)]


def test_add_many_refuses_past_the_loads_capacity(world: World) -> None:
    ids = [DropOffId(n) for n in range(1, LOAD_CAPACITY + 2)]
    world.records.commit([Put(a_drop_off(id.number)) for id in ids])
    load_id = loaded(world)

    with pytest.raises(LoadFull):
        world.add_many_to_load(load_id, ids, staff=STAFF_MEMBER)

    assert world.view_load(load_id).members == ()


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
        "Load",
        "LoadEvent",
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


# Deleting a load started by mistake


@pytest.mark.parametrize("start_it_firing", [False, True])
def test_delete_load_puts_its_drop_offs_back_and_hides_it_everywhere(
    world: World, caplog: pytest.LogCaptureFixture, start_it_firing: bool
) -> None:
    caplog.set_level(logging.INFO)
    dropped_off(world, 1)
    dropped_off(world, 2)
    load_id = firing(world, AC_1, AC_2) if start_it_firing else loaded(world, AC_1, AC_2)
    commits = len(world.records.commits)

    deleted = world.delete_load(load_id, version(world, load_id), STAFF_MEMBER)

    assert deleted.status is LoadStatus.DELETED
    assert len(world.records.commits) == commits + 1  # the load and its drop-offs together
    assert state(world, AC_1) is DropOffState.WAITING
    assert state(world, AC_2) is DropOffState.WAITING
    assert [row.drop_off.id for row in world.waiting().rows] == [AC_1, AC_2]
    stored = world.records.load(load_id)
    assert stored is not None
    assert (stored.deleted_by, stored.deleted_at) == (STAFF, NOW)
    assert world.list_loads() == ([], [])
    with pytest.raises(NotFound):
        world.view_load(load_id)
    with pytest.raises(NotFound):
        world.delete_load(load_id, version(world, load_id), STAFF_MEMBER)
    with pytest.raises(NotFound):
        world.add_to_load(load_id, AC_1, confirmed=True, staff=STAFF_MEMBER)
    [event] = events(caplog, "load_deleted")
    assert (event["load_id"], event["count"], event["user"]) == ("L-1", 2, STAFF)
    # The drop-offs can go in another load, and the next load takes a new number.
    assert world.add_to_load(loaded(world), AC_1, confirmed=False, staff=STAFF_MEMBER).id == L_2


def test_delete_load_refuses_a_fired_load_and_changes_nothing(world: World) -> None:
    dropped_off(world, 1)
    load_id = fired(world, AC_1)
    commits = len(world.records.commits)

    with pytest.raises(FiredLoadNotDeletable):
        world.delete_load(load_id, version(world, load_id), STAFF_MEMBER)

    assert len(world.records.commits) == commits
    assert state(world, AC_1) is DropOffState.FIRED


def test_delete_load_with_a_stale_version_is_a_conflict(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world)
    shown = version(world, load_id)
    world.add_to_load(load_id, AC_1, confirmed=False, staff=STAFF_MEMBER)  # after the page was shown

    with pytest.raises(Conflict):
        world.delete_load(load_id, shown, STAFF_MEMBER)

    assert world.view_load(load_id).load.members == (AC_1,)
    assert state(world, AC_1) is DropOffState.IN_LOAD


def test_a_deleted_load_no_longer_keeps_its_kiln_in_use(world: World) -> None:
    load_id = loaded(world, kiln=HELIOS)
    assert world.records.is_item_used(CatalogList.KILNS, HELIOS)
    world.delete_load(load_id, version(world, load_id), STAFF_MEMBER)
    assert not world.records.is_item_used(CatalogList.KILNS, HELIOS)


def delete_after(world: World, load_id: LoadId, other: Callable[[], object]) -> None:
    """Delete `load_id` as a page shown before `other` landed: the delete's first read of
    the load is from before `other`, its reads after that see what `other` committed."""
    stale = world.records.load(load_id)
    assert stale is not None
    other()
    read = world.records.load
    reads = 0

    def first_read_stale(id: LoadId) -> object:
        nonlocal reads
        reads += 1
        return stale if reads == 1 else read(id)

    world.records.load = first_read_stale  # type: ignore[assignment,method-assign]  # the fake read replaced to stage a race
    try:
        world.delete_load(load_id, stale.version, STAFF_MEMBER)
    finally:
        world.records.load = read  # type: ignore[method-assign]  # restored


def test_delete_load_losing_to_a_fire_says_fired(world: World) -> None:
    dropped_off(world, 1)
    load_id = firing(world, AC_1)
    with pytest.raises(FiredLoadNotDeletable):
        delete_after(world, load_id, lambda: world.mark_fired(load_id, version(world, load_id), STAFF_MEMBER))
    assert state(world, AC_1) is DropOffState.FIRED


def test_delete_load_losing_to_a_remove_is_a_conflict(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)
    load_id = loaded(world, AC_1, AC_2)
    with pytest.raises(Conflict):
        delete_after(world, load_id, lambda: world.remove_from_load(load_id, AC_1, STAFF_MEMBER))
    assert world.view_load(load_id).load.members == (AC_2,)
    assert state(world, AC_2) is DropOffState.IN_LOAD


def test_two_staff_deleting_at_once_one_gets_not_found(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    commits = len(world.records.commits)
    with pytest.raises(NotFound):
        delete_after(
            world, load_id, lambda: world.delete_load(load_id, version(world, load_id), STAFF_MEMBER)
        )
    assert len(world.records.commits) == commits + 1  # the first delete only
    assert state(world, AC_1) is DropOffState.WAITING


def test_a_delete_that_cant_reach_the_store_stores_nothing(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    commits = len(world.records.commits)
    world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        world.delete_load(load_id, version(world, load_id), STAFF_MEMBER)
    assert len(world.records.commits) == commits
    assert state(world, AC_1) is DropOffState.IN_LOAD


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


# Test firings and who moved the load (#42)

OTHER_STAFF = StaffMember("robin", an_address("robin.kiln"))


def test_start_load_as_test(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    assert load.test
    assert world.records.load(load.id) == load
    [event] = events(caplog, "load_started")
    assert (event["load_id"], event["kind"], event["user"]) == ("L-1", "test", STAFF)
    regular = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    assert not regular.test
    assert "kind" not in events(caplog, "load_started")[1]


def test_change_load_corrects_test_while_loading(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    changed = world.change_load(load.id, ATHENA, BISQUE, load.date, load.version, STAFF_MEMBER, test=False)
    assert not changed.test
    assert world.records.load(load.id) == changed


def test_start_firing_empty_test_load(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    firing_load = world.start_firing(load.id, load.version, STAFF_MEMBER)
    assert (firing_load.status, firing_load.members) == (LoadStatus.FIRING, ())

    done = world.mark_fired(load.id, firing_load.version, OTHER_STAFF)

    assert (done.status, done.fired_by) == (LoadStatus.FIRED, "robin")
    assert world.records.load(load.id) == done
    assert world.records.emails_in(set(EmailStatus)) == []  # nobody to email
    with pytest.raises(LoadNotLoading):
        world.change_load(load.id, ATHENA, BISQUE, load.date, done.version, STAFF_MEMBER, test=False)


def test_start_firing_records_who_and_when(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    world.clock.advance(timedelta(hours=2))

    load = world.start_firing(load_id, version(world, load_id), OTHER_STAFF)

    assert (load.firing_started_by, load.firing_started_at) == ("robin", NOW + timedelta(hours=2))
    assert (load.started_by, load.started_at) == (STAFF, NOW)
    assert world.records.load(load_id) == load


def test_mark_fired_records_who(world: World) -> None:
    dropped_off(world, 1)
    load_id = firing(world, AC_1)
    world.clock.advance(timedelta(hours=10))

    load = world.mark_fired(load_id, version(world, load_id), OTHER_STAFF)

    assert (load.fired_by, load.fired_at) == ("robin", NOW + timedelta(hours=10))
    assert (load.firing_started_by, load.firing_started_at) == (STAFF, NOW)
    assert world.records.load(load_id) == load


# A load's history (#42)


def history(world: World, load_id: LoadId) -> list[tuple[str, str]]:
    """(username, what) of each line of the load's history, oldest first."""
    return [(line.by, line.what) for line in world.records.load_events(load_id)]


def last_commit_types(world: World) -> list[str]:
    return sorted(type(change.item).__name__ for change in world.records.commits[-1])


def test_start_load_writes_its_history_line_in_its_commit(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    assert last_commit_types(world) == ["Load", "LoadEvent"]
    [line] = world.records.load_events(load.id)
    assert (line.by, line.at, line.what) == (STAFF, NOW, "Started the load")

    test = world.start_load(ATHENA, BISQUE, None, OTHER_STAFF, test=True)
    assert history(world, test.id) == [("robin", "Started the load as a test firing")]


def test_change_load_writes_one_line_per_change(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load = world.start_load(ATHENA, BISQUE, date(2026, 11, 12), STAFF_MEMBER)
    world.clock.advance(timedelta(minutes=5))

    changed = world.change_load(
        load.id, HELIOS, GLAZE, date(2026, 11, 13), load.version, OTHER_STAFF, test=True
    )

    [_, line] = world.records.load_events(load.id)
    assert (line.by, line.at) == ("robin", NOW + timedelta(minutes=5))
    assert line.what == (
        "Kiln: Athena → Helios; Firing type: Bisque → Glaze; Date: Nov 12 → Nov 13; "
        "Marked a test firing; Firing record: Preheat: 0 h; Cone: ^6; Speed: medium; Hold: 7 min"
    )
    assert last_commit_types(world) == ["Load", "LoadEvent"]
    assert world.records.load(load.id) == changed
    world.clock.advance(timedelta(minutes=1))  # two lines at one instant come in no promised order
    world.change_load(load.id, HELIOS, GLAZE, changed.date, changed.version, OTHER_STAFF, test=False)
    assert history(world, load.id)[-1] == ("robin", "No longer a test firing")
    assert len(events(caplog, "load_changed")) == 2


def test_change_load_without_changes_writes_no_line(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    commits = len(world.records.commits)

    same = world.change_load(load.id, ATHENA, BISQUE, load.date, load.version, STAFF_MEMBER, test=False)

    assert same == load
    assert len(world.records.commits) == commits
    assert history(world, load.id) == [(STAFF, "Started the load")]
    assert events(caplog, "load_changed") == []
    with pytest.raises(Conflict):  # a stale page still hears so
        world.change_load(load.id, ATHENA, BISQUE, load.date, load.version - 1, STAFF_MEMBER, test=False)


def put_notes(world: World, load_id: LoadId, first: int, count: int) -> None:
    load = world.records.load(load_id)
    assert load is not None
    notes = [
        a_note(number, load, glaze_types=(), clay_bodies=(), studio=world.studio())
        for number in range(first, first + count)
    ]
    world.records.commit([Put(note) for note in notes])


def note_kiln(world: World, load_id: LoadId, number: int) -> ItemId:
    note = world.records.note(load_id, NoteId(number))
    assert note is not None
    return note.kiln


def test_change_load_kiln_moves_its_notes(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    other = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    put_notes(world, load.id, 1, 3)
    put_notes(world, other.id, 4, 1)
    removed = world.records.note(load.id, NoteId(3))
    assert removed is not None
    world.records.commit([Update(remove_note(removed, STAFF, NOW))])

    world.change_load(load.id, HELIOS, BISQUE, load.date, load.version, STAFF_MEMBER, test=False)

    assert last_commit_types(world) == ["FiringNote", "FiringNote", "Load", "LoadEvent"]
    assert [note_kiln(world, load.id, n) for n in (1, 2)] == [HELIOS, HELIOS]
    assert note_kiln(world, load.id, 3) == ATHENA  # removed: listed nowhere, so not moved
    assert note_kiln(world, other.id, 4) == ATHENA


def test_change_load_kiln_with_too_many_notes_refused(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    put_notes(world, load.id, 1, NOTES_MOVED_MAX)
    # At the limit, the commit is exactly MAX_CHANGES.
    moved = world.change_load(load.id, HELIOS, BISQUE, load.date, load.version, STAFF_MEMBER, test=False)
    assert len(world.records.commits[-1]) == MAX_CHANGES
    put_notes(world, load.id, NOTES_MOVED_MAX + 1, 1)
    commits = len(world.records.commits)

    with pytest.raises(TooManyNotesToMove):
        world.change_load(load.id, ATHENA, BISQUE, load.date, moved.version, STAFF_MEMBER, test=False)

    assert len(world.records.commits) == commits
    assert note_kiln(world, load.id, 1) == HELIOS


def test_change_load_date_only_reads_no_notes(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    reads = len(world.records.reads)
    world.clock.advance(timedelta(minutes=1))  # two lines at one instant come in no promised order
    world.change_load(load.id, ATHENA, BISQUE, date(2026, 11, 20), load.version, STAFF_MEMBER, test=False)
    assert "notes_for" not in world.records.reads[reads:]
    assert history(world, load.id)[-1] == (STAFF, "Date: Nov 13 → Nov 20")


def test_start_firing_writes_its_history_line(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    world.clock.advance(timedelta(hours=1))
    world.start_firing(load.id, load.version, OTHER_STAFF)
    assert last_commit_types(world) == ["Load", "LoadEvent"]
    [_, line] = world.records.load_events(load.id)
    assert (line.by, line.at, line.what) == ("robin", NOW + timedelta(hours=1), "Started firing")


def test_mark_fired_full_load_commits_98_changes(world: World) -> None:
    ids = [DropOffId(n) for n in range(1, LOAD_CAPACITY + 1)]
    world.records.commit([Put(a_drop_off(id.number)) for id in ids])
    load_id = firing(world, *ids)
    world.clock.advance(timedelta(hours=9))

    world.mark_fired(load_id, version(world, load_id), OTHER_STAFF)

    assert len(world.records.commits[-1]) == 1 + 2 * LOAD_CAPACITY + 1 == 98
    line = world.records.load_events(load_id)[-1]
    assert (line.by, line.at, line.what) == ("robin", NOW + timedelta(hours=9), "Marked fired")


def test_delete_load_writes_its_history_line(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    world.clock.advance(timedelta(minutes=1))  # two lines at one instant come in no promised order
    world.delete_load(load_id, version(world, load_id), OTHER_STAFF)
    assert last_commit_types(world) == ["DropOff", "Load", "LoadEvent"]
    assert history(world, load_id)[-1] == ("robin", "Deleted the load")


def test_adding_and_removing_write_no_history_line(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    world.remove_from_load(load_id, AC_1, STAFF_MEMBER)
    assert history(world, load_id) == [(STAFF, "Started the load")]


def test_a_failed_commit_writes_no_history_line(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    attempts: list[Callable[[], object]] = [
        lambda: world.start_firing(load.id, load.version, STAFF_MEMBER),
        lambda: world.change_load(load.id, HELIOS, BISQUE, load.date, load.version, STAFF_MEMBER, test=True),
        lambda: world.delete_load(load.id, load.version, STAFF_MEMBER),
        lambda: world.save_firing_record(load.id, {"percent_full": "50"}, load.version, STAFF_MEMBER),
        lambda: world.correct_step_time(
            load.id, Step.STARTED, NOW - timedelta(hours=1), load.version, STAFF_MEMBER
        ),
    ]
    for attempt in attempts:
        world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")
        with pytest.raises(RecordsUnavailable):
            attempt()
    assert world.records.load(load.id) == load
    assert history(world, load.id) == [(STAFF, "Started the load as a test firing")]

    world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER, test=True)  # L-2's number is spent
    assert world.records.load(L_2) is None
    assert history(world, L_2) == []

    firing = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    world.clock.advance(timedelta(minutes=1))
    firing = world.start_firing(firing.id, firing.version, STAFF_MEMBER)
    world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        world.mark_fired(firing.id, firing.version, STAFF_MEMBER)
    assert world.records.load(firing.id) == firing
    assert history(world, firing.id) == [
        (STAFF, "Started the load as a test firing"),
        (STAFF, "Started firing"),
    ]


# The firing record (#42)


def test_save_firing_record(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load = world.start_load(ATHENA, GLAZE, None, STAFF_MEMBER)  # Glaze's default program
    world.clock.advance(timedelta(minutes=30))
    values = record_values(load.record) | {"percent_full": "85", "max_temp_f": "2236", "cost": "8.19"}

    saved = world.save_firing_record(load.id, values, load.version, OTHER_STAFF)

    assert (saved.record.percent_full, saved.record.max_temp_f, saved.record.cost_cents) == (85, 2236, 819)
    assert saved.record.program == load.record.program
    assert world.records.load(load.id) == saved
    assert last_commit_types(world) == ["Load", "LoadEvent"]
    line = world.records.load_events(load.id)[-1]
    assert (line.by, line.at) == ("robin", NOW + timedelta(minutes=30))
    assert line.what == "Firing record: % full: 85%; Max temp: 2,236 °F; Cost: $8.19"
    [event] = events(caplog, "firing_record_saved")
    assert (event["load_id"], event["user"], event["fields"]) == (
        "L-1",
        "robin",
        "percent_full,max_temp_f,cost",
    )


def test_save_firing_record_unchanged_no_commit(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load = world.start_load(ATHENA, GLAZE, None, STAFF_MEMBER)
    commits = len(world.records.commits)

    same = world.save_firing_record(load.id, record_values(load.record), load.version, STAFF_MEMBER)

    assert same == load
    assert len(world.records.commits) == commits
    assert events(caplog, "firing_record_saved") == []


def test_save_firing_record_invalid_names_fields(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    commits = len(world.records.commits)

    with pytest.raises(InvalidRecord) as refused:
        world.save_firing_record(
            load.id, {"percent_full": "101", "cone": "item-9", "cost": "8.19"}, load.version, STAFF_MEMBER
        )

    assert set(refused.value.errors) == {"percent_full", "cone"}
    assert len(world.records.commits) == commits


def test_save_firing_record_conflict(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    with pytest.raises(Conflict):
        world.save_firing_record(load.id, {"percent_full": "50"}, load.version - 1, STAFF_MEMBER)
    assert world.records.load(load.id) == load


def test_save_firing_record_on_fired_load_keeps_members_and_sends_nothing(world: World) -> None:
    dropped_off(world, 1)
    load_id = fired(world, AC_1)
    before = world.records.load(load_id)
    assert before is not None
    emails = world.records.emails_in(set(EmailStatus))

    saved = world.save_firing_record(load_id, {"firing_time": "11:38"}, before.version, STAFF_MEMBER)

    assert (saved.status, saved.members, saved.record.firing_minutes) == (LoadStatus.FIRED, (AC_1,), 698)
    assert last_commit_types(world) == ["Load", "LoadEvent"]  # no drop-off, no email
    assert world.records.emails_in(set(EmailStatus)) == emails
    assert state(world, AC_1) is DropOffState.FIRED


def test_save_firing_record_deleted_load_not_found(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    deleted = world.delete_load(load.id, load.version, STAFF_MEMBER)
    with pytest.raises(NotFound):
        world.save_firing_record(load.id, {"percent_full": "50"}, deleted.version, STAFF_MEMBER)
    with pytest.raises(NotFound):
        world.save_firing_record(LoadId(9), {}, 1, STAFF_MEMBER)


def test_save_firing_record_retired_cone_already_on_record_saves(world: World) -> None:
    load = world.start_load(ATHENA, GLAZE, None, STAFF_MEMBER)  # its program names ^6
    cone_6, cone_5 = ItemId("item-6"), ItemId("item-5")
    for cone in (cone_6, cone_5):
        world.retire_item(CatalogList.CONES, cone, world.studio().version, STAFF_MEMBER)
    assert [cone.name for cone in world.view_load(load.id).cones] == ["^06", "^6"]

    saved = world.save_firing_record(
        load.id, record_values(load.record) | {"hold_minutes": "9"}, load.version, STAFF_MEMBER
    )
    assert (saved.record.program.cone, saved.record.program.hold_minutes) == (cone_6, 9)
    with pytest.raises(InvalidRecord) as refused:
        world.save_firing_record(load.id, {"cone": str(cone_5)}, saved.version, STAFF_MEMBER)
    assert set(refused.value.errors) == {"cone"}


# Correcting a step's time (#42)


def test_correct_step_time_writes_old_and_new(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    world.clock.advance(timedelta(hours=4))  # 16:30 Austin
    load = world.start_firing(load_id, version(world, load_id), STAFF_MEMBER)
    world.clock.advance(timedelta(minutes=10))
    earlier = NOW + timedelta(hours=3, minutes=45)

    corrected = world.correct_step_time(load_id, Step.FIRING, earlier, load.version, OTHER_STAFF)

    assert (corrected.firing_started_at, corrected.firing_started_by) == (earlier, STAFF)
    assert world.records.load(load_id) == corrected
    line = world.records.load_events(load_id)[-1]
    assert (line.by, line.at) == ("robin", NOW + timedelta(hours=4, minutes=10))
    assert line.what == "Corrected when it started firing: Nov 13, 4:30 pm → Nov 13, 4:15 pm"
    [event] = events(caplog, "step_time_corrected")
    assert (event["load_id"], event["kind"], event["user"]) == ("L-1", "firing", "robin")


def test_correct_step_time_names_each_step(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    load = world.start_firing(load.id, load.version, STAFF_MEMBER)
    load = world.mark_fired(load.id, load.version, STAFF_MEMBER)
    world.clock.advance(timedelta(hours=1))
    load = world.correct_step_time(
        load.id, Step.FIRED, NOW + timedelta(minutes=30), load.version, STAFF_MEMBER
    )
    world.clock.advance(timedelta(minutes=1))  # two lines at one instant come in no promised order
    load = world.correct_step_time(
        load.id, Step.STARTED, NOW - timedelta(hours=12), load.version, STAFF_MEMBER
    )
    assert [what for _, what in history(world, load.id)[-2:]] == [
        "Corrected when it was fired: Nov 13, 12:30 pm → Nov 13, 1:00 pm",
        "Corrected when it was started: Nov 13, 12:30 pm → Nov 13, 12:30 am",
    ]
    commits = len(world.records.commits)
    assert world.correct_step_time(load.id, Step.STARTED, load.started_at, load.version, STAFF_MEMBER) == load
    assert len(world.records.commits) == commits  # the same time again: nothing to record


def test_correct_step_time_the_same_minute_is_unchanged(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    world.clock.advance(timedelta(seconds=42))
    load = world.start_firing(load.id, load.version, STAFF_MEMBER)  # at 12:30:42 pm
    world.clock.advance(timedelta(hours=1))
    commits = len(world.records.commits)

    # The page posts minutes: its prefilled form sent back as it is changes nothing.
    same = world.correct_step_time(load.id, Step.FIRING, NOW, load.version, STAFF_MEMBER)

    assert same == load
    assert same.firing_started_at == NOW + timedelta(seconds=42)  # the seconds stay
    assert len(world.records.commits) == commits


def test_correct_step_time_shows_the_years_when_they_differ(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    world.clock.advance(timedelta(minutes=1))
    a_year_back = NOW - timedelta(days=365)

    world.correct_step_time(load.id, Step.STARTED, a_year_back, load.version, STAFF_MEMBER)

    assert history(world, load.id)[-1][1] == (
        "Corrected when it was started: Nov 13, 2026, 12:30 pm → Nov 13, 2025, 12:30 pm"
    )


def test_change_load_date_shows_the_years_when_they_differ(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER)
    world.clock.advance(timedelta(minutes=1))

    world.change_load(load.id, ATHENA, BISQUE, date(2027, 11, 13), load.version, STAFF_MEMBER, test=False)

    assert history(world, load.id)[-1][1] == "Date: Nov 13, 2026 → Nov 13, 2027"


def test_correct_step_time_refusals(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    commits = len(world.records.commits)
    with pytest.raises(StepNotReached):
        world.correct_step_time(load.id, Step.FIRING, NOW, load.version, STAFF_MEMBER)
    with pytest.raises(StepTimeInFuture):
        world.correct_step_time(load.id, Step.STARTED, NOW + timedelta(minutes=1), load.version, STAFF_MEMBER)
    firing_load = world.start_firing(load.id, load.version, STAFF_MEMBER)
    with pytest.raises(StepTimeOutOfOrder):
        world.correct_step_time(
            load.id, Step.FIRING, NOW - timedelta(minutes=1), firing_load.version, STAFF_MEMBER
        )
    with pytest.raises(Conflict):
        world.correct_step_time(load.id, Step.STARTED, NOW - timedelta(hours=1), load.version, STAFF_MEMBER)
    deleted = world.delete_load(load.id, firing_load.version, STAFF_MEMBER)
    with pytest.raises(NotFound):
        world.correct_step_time(
            load.id, Step.STARTED, NOW - timedelta(hours=1), deleted.version, STAFF_MEMBER
        )
    assert len(world.records.commits) == commits + 2  # the firing and the delete only


# Viewing a load's steps, record and history (#42)


def test_view_load_steps_with_who(world: World) -> None:
    load = world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER, test=True)
    view = world.view_load(load.id)
    assert [(s.step, s.label, s.reached, s.by, s.at, s.can_correct) for s in view.steps] == [
        (Step.STARTED, "Loading", True, STAFF, NOW, True),
        (Step.FIRING, "Firing", False, None, None, False),
        (Step.FIRED, "Fired", False, None, None, False),
    ]
    world.clock.advance(timedelta(hours=1))
    load = world.start_firing(load.id, load.version, OTHER_STAFF)
    world.clock.advance(timedelta(hours=1))
    world.mark_fired(load.id, load.version, STAFF_MEMBER)

    view = world.view_load(load.id)

    assert [(s.reached, s.by, s.at) for s in view.steps] == [
        (True, STAFF, NOW),
        (True, "robin", NOW + timedelta(hours=1)),
        (True, STAFF, NOW + timedelta(hours=2)),
    ]


def test_view_load_old_load_firing_not_recorded(world: World) -> None:
    world.studio()
    world.records.commit([Put(a_load(5, LoadStatus.FIRED, before_42=True))])

    view = world.view_load(LoadId(5))

    assert [(s.reached, s.by, s.at, s.can_correct) for s in view.steps] == [
        (True, STAFF, NOW, True),
        (True, None, None, False),  # the page says "not recorded", and offers no correction
        (True, None, NOW, True),
    ]
    assert view.history == ()


def test_view_load_history_oldest_first(world: World) -> None:
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    world.clock.advance(timedelta(minutes=1))
    world.change_load(
        load_id, HELIOS, BISQUE, date(2026, 11, 14), version(world, load_id), STAFF_MEMBER, test=False
    )
    world.clock.advance(timedelta(minutes=1))
    world.start_firing(load_id, version(world, load_id), OTHER_STAFF)
    world.clock.advance(timedelta(minutes=1))
    world.mark_fired(load_id, version(world, load_id), OTHER_STAFF)

    view = world.view_load(load_id)

    assert [(line.by, line.what) for line in view.history] == [
        (STAFF, "Started the load"),
        (STAFF, "Kiln: Athena → Helios; Date: Nov 13 → Nov 14"),
        ("robin", "Started firing"),
        ("robin", "Marked fired"),
    ]
    assert [line.at for line in view.history] == [NOW + timedelta(minutes=m) for m in range(4)]


def test_view_load_record_fields_as_the_form_shows_them(world: World) -> None:
    load = world.start_load(ATHENA, GLAZE, None, STAFF_MEMBER)
    saved = world.save_firing_record(
        load.id, record_values(load.record) | {"firing_time": "11:38", "cone_bottom": "none"}, 1, STAFF_MEMBER
    )
    view = world.view_load(load.id)
    assert view.record_fields == record_values(saved.record)
    assert (view.record_fields["firing_time"], view.record_fields["cone_bottom"]) == ("11:38", "none")
    assert view.record_fields["cone"] == "item-6"
    assert [cone.name for cone in view.cones] == ["^06", "^5", "^6"]


def numbered_fired(world: World, kiln: ItemId, since: str, total: str) -> LoadId:
    load = world.start_load(kiln, BISQUE, None, STAFF_MEMBER, test=True)
    load = world.start_firing(load.id, load.version, STAFF_MEMBER)
    load = world.mark_fired(load.id, load.version, STAFF_MEMBER)
    values = {"firing_number": since, "all_time_number": total}
    world.save_firing_record(load.id, values, load.version, STAFF_MEMBER)
    return load.id


def test_view_load_suggested_numbers(world: World) -> None:
    world.set_kiln_counts(HELIOS, "97", "251", world.studio().version, STAFF_MEMBER)
    world.clock.advance(timedelta(hours=1))
    assert world.view_load(world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER).id).suggested == (98, 252)
    world.clock.advance(timedelta(hours=1))
    numbered_fired(world, HELIOS, "98", "252")
    numbered_fired(world, ATHENA, "500", "900")  # another kiln's firing doesn't count
    world.clock.advance(timedelta(hours=1))
    ranges = len(world.records.date_ranges)

    assert world.view_load(L_1).suggested == (99, 253)
    today = date(2026, 11, 13)
    assert world.records.date_ranges[ranges:] == [(today - NUMBERS_DATE_MARGIN, today + NUMBERS_READ_AHEAD)]


def test_view_load_no_suggestion_for_a_load_fired_before_the_counts(world: World) -> None:
    load = world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER, test=True)
    load = world.start_firing(load.id, load.version, STAFF_MEMBER)
    world.clock.advance(timedelta(hours=1))
    world.mark_fired(load.id, load.version, STAFF_MEMBER)
    world.clock.advance(timedelta(hours=1))
    # Counts set after it was fired: they already count it.
    world.set_kiln_counts(HELIOS, "97", "251", world.studio().version, STAFF_MEMBER)
    world.clock.advance(timedelta(hours=1))
    reads = len(world.records.reads)

    assert world.view_load(load.id).suggested == (None, None)
    assert "loads_dated_between" not in world.records.reads[reads:]
    # The next new load is still suggested the counts plus 1.
    assert world.view_load(world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER).id).suggested == (98, 252)


def test_view_load_reads_a_bounded_window_around_when_it_was_fired(world: World) -> None:
    world.set_kiln_counts(HELIOS, "97", "251", world.studio().version, STAFF_MEMBER)
    world.clock.advance(timedelta(hours=1))
    load = world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER, test=True)
    load = world.start_firing(load.id, load.version, STAFF_MEMBER)
    world.mark_fired(load.id, load.version, STAFF_MEMBER)
    world.clock.advance(timedelta(days=3 * 365))  # years later, the counts never set again
    ranges = len(world.records.date_ranges)

    assert world.view_load(load.id).suggested == (98, 252)
    fired_day = date(2026, 11, 13)
    start, end = world.records.date_ranges[ranges]
    assert (start, end) == (fired_day - NUMBERS_DATE_MARGIN, fired_day + NUMBERS_READ_AHEAD)
    assert end - start <= NUMBERS_LOOKBACK + NUMBERS_READ_AHEAD


def test_view_load_suggests_from_firings_before_a_fired_load(world: World) -> None:
    unnumbered = world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER, test=True)
    unnumbered = world.start_firing(unnumbered.id, unnumbered.version, STAFF_MEMBER)
    world.clock.advance(timedelta(hours=1))
    numbered_fired(world, HELIOS, "4", "40")  # fired before the unnumbered one
    world.clock.advance(timedelta(hours=1))
    world.mark_fired(unnumbered.id, unnumbered.version, STAFF_MEMBER)
    world.clock.advance(timedelta(hours=1))
    numbered_fired(world, HELIOS, "6", "60")  # fired after it

    assert world.view_load(unnumbered.id).suggested == (5, 41)


def fired_unnumbered(world: World, kiln: ItemId, *, drop_off: int | None = None) -> LoadId:
    """A fired test load on `kiln` whose record holds no number: empty, or holding the
    drop-off numbered `drop_off`."""
    load_id = world.start_load(kiln, BISQUE, None, STAFF_MEMBER, test=True).id
    if drop_off is not None:
        world.add_to_load(load_id, dropped_off(world, drop_off), confirmed=True, staff=STAFF_MEMBER)
    world.start_firing(load_id, version(world, load_id), STAFF_MEMBER)
    world.mark_fired(load_id, version(world, load_id), STAFF_MEMBER)
    return load_id


def test_view_load_counts_every_firing_numbered_or_not(world: World) -> None:
    """Any firing counts toward the numbers (#42): an empty test and a test with
    drop-offs, fired with no record saved (the rule reads neither `test` nor members)."""
    world.set_kiln_counts(HELIOS, "97", "251", world.studio().version, STAFF_MEMBER)
    world.clock.advance(timedelta(hours=1))
    empty_test = fired_unnumbered(world, HELIOS)
    world.clock.advance(timedelta(hours=1))
    assert world.view_load(world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER).id).suggested == (99, 253)
    numbered_fired(world, HELIOS, "99", "253")
    world.clock.advance(timedelta(hours=1))
    with_drop_offs = fired_unnumbered(world, HELIOS, drop_off=1)
    stored = world.records.load(with_drop_offs)
    assert stored is not None
    assert (stored.test, stored.members) == (True, (AC_1,))
    world.clock.advance(timedelta(hours=1))

    assert world.view_load(world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER).id).suggested == (101, 255)
    # A fired load is suggested its own numbers from the firings before it alone.
    assert world.view_load(empty_test).suggested == (98, 252)
    assert world.view_load(with_drop_offs).suggested == (100, 254)


def test_view_load_no_suggestion_once_numbered(world: World) -> None:
    world.set_kiln_counts(HELIOS, "97", "251", world.studio().version, STAFF_MEMBER)
    load = world.start_load(HELIOS, BISQUE, None, STAFF_MEMBER)
    world.save_firing_record(load.id, {"firing_number": "98"}, load.version, STAFF_MEMBER)
    reads = len(world.records.reads)

    assert world.view_load(load.id).suggested == (None, None)
    assert "loads_dated_between" not in world.records.reads[reads:]
    assert world.view_load(world.start_load(ATHENA, BISQUE, None, STAFF_MEMBER).id).suggested == (None, None)


def test_delete_load_removes_its_notes(world: World) -> None:
    """A deleted load's notes are removed with it, so its tags count as used nowhere (#17)."""
    dropped_off(world, 1)
    load_id = loaded(world, AC_1)
    load = world.records.load(load_id)
    assert load is not None
    note = a_note(
        1, load, glaze_types=("commercial-glaze",), clay_bodies=("buffalo-wallow",), studio=world.studio()
    )
    world.records.commit([Put(note)])
    assert world.records.is_item_used(CatalogList.CLAY_BODIES, ItemId("buffalo-wallow"))
    world.clock.advance(timedelta(minutes=1))

    world.delete_load(load_id, version(world, load_id), OTHER_STAFF)

    assert last_commit_types(world) == ["DropOff", "FiringNote", "Load", "LoadEvent"]
    removed = world.records.note(load_id, NoteId(1))
    assert removed is not None
    assert (removed.removed_by, removed.removed_at) == ("robin", NOW + timedelta(minutes=1))
    assert world.records.notes_for(load_id) == []
    assert not world.records.is_item_used(CatalogList.CLAY_BODIES, ItemId("buffalo-wallow"))
    assert not world.records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("commercial-glaze"))


def test_delete_load_with_too_many_notes_is_refused(world: World) -> None:
    for number in (1, 2):
        dropped_off(world, number)
    load_id = loaded(world, AC_1, AC_2)
    room = MAX_CHANGES - 2 - 2
    put_notes(world, load_id, 1, room)
    world.delete_load(load_id, version(world, load_id), STAFF_MEMBER)  # at the limit: exactly MAX_CHANGES
    assert len(world.records.commits[-1]) == MAX_CHANGES

    other = loaded(world)
    put_notes(world, other, room + 1, MAX_CHANGES - 1)
    commits = len(world.records.commits)
    with pytest.raises(TooManyNotesToMove) as refused:
        world.delete_load(other, version(world, other), STAFF_MEMBER)
    assert (
        refused.value.message
        == f"Load {other} has more than {MAX_CHANGES - 2} notes, so it can't be deleted."
        " Remove some of its notes first."
    )
    assert len(world.records.commits) == commits
    still = world.records.load(other)
    assert still is not None
    assert still.status is LoadStatus.LOADING
