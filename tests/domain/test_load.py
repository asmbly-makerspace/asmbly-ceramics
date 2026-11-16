from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus
from asmbly_ceramics.domain.errors import (
    AlreadyFired,
    AlreadyInLoad,
    DomainError,
    EmptyLoad,
    FiredLoadNotDeletable,
    FiringTypeLocked,
    FiringTypeMismatch,
    ItemRetired,
    LoadFull,
    LoadNotLoading,
    NotFound,
    NotInLoad,
    NotWaiting,
    StepNotReached,
    StepTimeInFuture,
    StepTimeOutOfOrder,
    UnknownItem,
    WrongLoadStatus,
)
from asmbly_ceramics.domain.firing import EMPTY_RECORD, FiringRecord, Program, Speed
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import LOAD_CAPACITY
from asmbly_ceramics.domain.load import (
    LIVE_STATUSES,
    Load,
    LoadStatus,
    Step,
    accepts_drop_offs,
    add_to_load,
    can_delete,
    can_start_firing,
    change_load,
    correct_step_time,
    delete_load,
    fire,
    firing_type_locked,
    remove_from_load,
    require_deletable,
    require_firing,
    require_loading,
    set_firing_record,
    start_firing,
    start_load,
    step_time,
)
from asmbly_ceramics.domain.studio import CatalogList, retire_item
from tests.domain.builders import NOW, STAFF, TEST_EMAIL, TEST_NAME, a_drop_off, a_load, a_studio

ATHENA, HELIOS = ItemId("athena"), ItemId("helios")
BISQUE, GLAZE = ItemId("bisque"), ItemId("glaze")
TODAY = date(2026, 11, 13)
LATER = NOW + timedelta(hours=10)


def in_load(number: int, load: int = 1) -> DropOff:
    return a_drop_off(number, DropOffState.IN_LOAD, load=load)


def a_glaze_drop_off(number: int) -> DropOff:
    return replace(a_drop_off(number), firing_type=GLAZE, glaze_type=ItemId("house-dip-glaze"))


# start_load and change_load


def test_start_load_makes_an_empty_loading_load() -> None:
    load = start_load(LoadId(4), ATHENA, BISQUE, TODAY, STAFF, NOW, a_studio())
    assert load == Load(LoadId(4), ATHENA, BISQUE, TODAY, LoadStatus.LOADING, (), STAFF, NOW)
    assert load.version == 0
    assert load.fired_at is None


def test_start_load_refuses_a_retired_kiln_or_firing_type() -> None:
    studio, _ = retire_item(a_studio(), CatalogList.KILNS, ATHENA, STAFF, NOW)
    with pytest.raises(ItemRetired, match="Athena"):
        start_load(LoadId(1), ATHENA, BISQUE, TODAY, STAFF, NOW, studio)
    studio, _ = retire_item(a_studio(), CatalogList.FIRING_TYPES, GLAZE, STAFF, NOW)
    with pytest.raises(ItemRetired, match="Glaze"):
        start_load(LoadId(1), HELIOS, GLAZE, TODAY, STAFF, NOW, studio)


def test_start_load_refuses_an_unknown_kiln_or_firing_type() -> None:
    with pytest.raises(UnknownItem, match="kiln"):
        start_load(LoadId(1), ItemId("kiln-9"), BISQUE, TODAY, STAFF, NOW, a_studio())
    with pytest.raises(UnknownItem, match="firing type"):
        start_load(LoadId(1), ATHENA, ItemId("raku"), TODAY, STAFF, NOW, a_studio())
    # A firing type's ID is not a kiln's.
    with pytest.raises(UnknownItem, match="kiln"):
        start_load(LoadId(1), BISQUE, BISQUE, TODAY, STAFF, NOW, a_studio())


def test_start_load_needs_the_staff_username() -> None:
    with pytest.raises(ValueError, match="username"):
        start_load(LoadId(1), ATHENA, BISQUE, TODAY, "", NOW, a_studio())


def test_naive_times_are_refused() -> None:
    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="aware"):
        start_load(LoadId(1), ATHENA, BISQUE, TODAY, STAFF, naive, a_studio())
    with pytest.raises(ValueError, match="aware"):
        fire(a_load(status=LoadStatus.FIRING, members=[1]), [in_load(1)], STAFF, naive)


def test_change_load_changes_kiln_and_date_and_keeps_members() -> None:
    load = a_load(members=[1, 2])
    changed = change_load(load, HELIOS, load.firing_type, TODAY + timedelta(days=1), a_studio(), test=False)
    assert (changed.kiln, changed.firing_type, changed.date) == (HELIOS, BISQUE, TODAY + timedelta(days=1))
    assert changed.members == load.members
    assert changed.status is LoadStatus.LOADING


def test_change_load_changes_the_firing_type_of_an_empty_load() -> None:
    changed = change_load(a_load(), ATHENA, GLAZE, TODAY, a_studio(), test=False)
    assert changed.firing_type == GLAZE


def test_change_load_refuses_a_new_firing_type_once_it_has_members() -> None:
    # Each member was added, and any mismatch confirmed, against the load's firing type (#4).
    with pytest.raises(FiringTypeLocked) as caught:
        change_load(a_load(members=[1]), ATHENA, GLAZE, TODAY, a_studio(), test=False)
    assert caught.value.message == (
        "Load L-1 has drop-offs in it: remove them before changing its firing type."
    )
    assert caught.value.load_id == LoadId(1)


def test_change_load_only_while_loading() -> None:
    for status in (LoadStatus.FIRING, LoadStatus.FIRED):
        with pytest.raises(LoadNotLoading, match=f"L-1 is {status}"):
            change_load(a_load(status=status, members=[1]), HELIOS, BISQUE, TODAY, a_studio(), test=False)


def test_change_load_refuses_a_retired_kiln_or_firing_type_it_changes_to() -> None:
    studio, _ = retire_item(a_studio(), CatalogList.KILNS, HELIOS, STAFF, NOW)
    with pytest.raises(ItemRetired):
        change_load(a_load(), HELIOS, BISQUE, TODAY, studio, test=False)
    studio, _ = retire_item(a_studio(), CatalogList.FIRING_TYPES, GLAZE, STAFF, NOW)
    with pytest.raises(ItemRetired):
        change_load(a_load(), ATHENA, GLAZE, TODAY, studio, test=False)


def test_change_load_checks_only_what_changes() -> None:
    # The load's kiln and firing type were retired after it was started: its date can
    # still move, and keeping them is not picking them again.
    load = a_load()
    assert (load.kiln, load.firing_type) == (ATHENA, BISQUE)
    studio, _ = retire_item(a_studio(), CatalogList.KILNS, ATHENA, STAFF, NOW)
    studio, _ = retire_item(studio, CatalogList.FIRING_TYPES, BISQUE, STAFF, NOW)
    changed = change_load(load, ATHENA, BISQUE, TODAY + timedelta(days=2), studio, test=False)
    assert changed.date == TODAY + timedelta(days=2)
    # The same holds for a load with members, whose firing type isn't changing.
    with_members = a_load(members=[1])
    assert (
        change_load(with_members, ATHENA, BISQUE, TODAY, studio, test=False).members == with_members.members
    )


# add_to_load


def test_add_to_load_moves_a_waiting_drop_off_in() -> None:
    load, drop_off = add_to_load(a_load(members=[1]), a_drop_off(2), confirmed=False)
    assert load.members == (DropOffId(1), DropOffId(2))
    assert drop_off.state is DropOffState.IN_LOAD
    assert drop_off.load_id == LoadId(1)
    assert drop_off.version == 0


def test_add_refuses_a_drop_off_in_another_load_naming_it() -> None:
    # Records that disagree (it names a load that doesn't list it) are refused, not a bug.
    with pytest.raises(AlreadyInLoad) as caught:
        add_to_load(a_load(1), in_load(7, load=3), confirmed=True)
    assert caught.value.message == "AC-7 is already in load L-3."
    # Adding it to its own load again is the same refusal.
    with pytest.raises(AlreadyInLoad, match="L-1"):
        add_to_load(a_load(1, members=[7]), in_load(7, load=1), confirmed=True)


@pytest.mark.parametrize("state", [DropOffState.FIRED, DropOffState.REJECTED, DropOffState.CLOSED])
def test_add_refuses_fired_rejected_and_closed(state: DropOffState) -> None:
    with pytest.raises(NotWaiting) as caught:
        add_to_load(a_load(), a_drop_off(5, state), confirmed=True)
    assert caught.value.message == f"AC-5 isn't waiting: it is {state.label}."


def test_add_with_a_different_firing_type_needs_confirmation() -> None:
    with pytest.raises(FiringTypeMismatch) as caught:
        add_to_load(a_load(firing_type="bisque"), a_glaze_drop_off(3), confirmed=False)
    assert caught.value.message == "AC-3's firing type is glaze; this load's is bisque."
    # Both firing types are kept by ID, for the page to name them from the studio.
    assert caught.value.drop_off_id == DropOffId(3)
    assert (caught.value.drop_off_firing_type, caught.value.load_firing_type) == (GLAZE, BISQUE)


def test_add_with_a_different_firing_type_added_when_confirmed() -> None:
    load, drop_off = add_to_load(a_load(firing_type="bisque"), a_glaze_drop_off(3), confirmed=True)
    assert load.members == (DropOffId(3),)
    assert drop_off.state is DropOffState.IN_LOAD
    assert drop_off.firing_type == GLAZE  # the drop-off keeps its own firing type


def test_a_load_holds_at_most_48() -> None:
    assert LOAD_CAPACITY == 48
    load = a_load(members=range(1, LOAD_CAPACITY))
    load, _ = add_to_load(load, a_drop_off(LOAD_CAPACITY), confirmed=False)
    assert len(load.members) == LOAD_CAPACITY
    with pytest.raises(LoadFull, match="L-1 already holds 48"):
        add_to_load(load, a_drop_off(LOAD_CAPACITY + 1), confirmed=False)


@pytest.mark.parametrize("status", [LoadStatus.FIRING, LoadStatus.FIRED])
def test_nothing_is_added_or_removed_once_firing(status: LoadStatus) -> None:
    load = a_load(status=status, members=[1])
    with pytest.raises(LoadNotLoading, match=f"L-1 is {status}: nothing can be added or removed"):
        add_to_load(load, a_drop_off(2), confirmed=True)
    with pytest.raises(LoadNotLoading):
        remove_from_load(load, in_load(1))


def test_nothing_is_added_or_removed_once_fired() -> None:
    load = a_load(status=LoadStatus.FIRED, members=[1])
    fired = a_drop_off(1, DropOffState.FIRED)
    with pytest.raises(LoadNotLoading):
        remove_from_load(load, fired)
    with pytest.raises(LoadNotLoading):
        add_to_load(load, a_drop_off(2), confirmed=True)


def test_add_with_inconsistent_records_is_a_bug() -> None:
    with pytest.raises(ValueError, match="listed in load"):
        add_to_load(a_load(members=[2]), a_drop_off(2), confirmed=False)
    with pytest.raises(ValueError, match="no load ID"):
        add_to_load(a_load(), replace(a_drop_off(2), state=DropOffState.IN_LOAD), confirmed=False)


# remove_from_load


def test_remove_puts_the_drop_off_back_to_waiting() -> None:
    load, drop_off = remove_from_load(a_load(members=[1, 2, 3]), in_load(2))
    assert load.members == (DropOffId(1), DropOffId(3))
    assert drop_off.state is DropOffState.WAITING
    assert drop_off.load_id is None


def test_remove_refuses_a_drop_off_not_in_this_load() -> None:
    load = a_load(1, members=[1])
    for drop_off in (
        a_drop_off(2),  # waiting
        in_load(2, load=2),  # in another load
        in_load(2, load=1),  # says load 1, but not a member
    ):
        with pytest.raises(NotInLoad) as caught:
            remove_from_load(load, drop_off)
        assert caught.value.message == "AC-2 isn't in load L-1."


def test_remove_refuses_a_waiting_drop_off_listed_in_the_load() -> None:
    # Records that disagree (the load lists AC-1, but AC-1 says it is waiting) are refused,
    # not silently "removed".
    with pytest.raises(NotInLoad) as caught:
        remove_from_load(a_load(1, members=[1]), a_drop_off(1))
    assert caught.value.message == "AC-1 isn't in load L-1."


# start_firing and fire


def test_start_firing_moves_a_loading_load_to_firing() -> None:
    load = start_firing(a_load(members=[1]), STAFF, LATER)
    assert load.status is LoadStatus.FIRING
    assert load.members == (DropOffId(1),)


def test_start_firing_refuses_an_empty_load() -> None:
    with pytest.raises(EmptyLoad, match="L-1 is empty"):
        start_firing(a_load(), STAFF, LATER)


@pytest.mark.parametrize("status", [LoadStatus.FIRING, LoadStatus.FIRED])
def test_start_firing_only_from_loading(status: LoadStatus) -> None:
    with pytest.raises(WrongLoadStatus) as caught:
        start_firing(a_load(status=status, members=[1]), STAFF, LATER)
    assert caught.value.message == f"Load L-1 is {status}, not loading."


@pytest.mark.parametrize("status", list(LoadStatus))
@pytest.mark.parametrize("members", [[], [1]])
@pytest.mark.parametrize("test", [False, True])
def test_the_predicates_agree_with_the_refusals(status: LoadStatus, members: list[int], test: bool) -> None:
    """What a page asks beforehand is what the rule then does."""
    load = a_load(status=status, members=members, test=test)
    try:
        start_firing(load, STAFF, LATER)
    except EmptyLoad, WrongLoadStatus:
        assert not can_start_firing(load)
    else:
        assert can_start_firing(load)
    try:
        require_loading(load)
    except LoadNotLoading:
        assert not accepts_drop_offs(load)
    else:
        assert accepts_drop_offs(load)
    if status is LoadStatus.LOADING:
        try:
            change_load(load, load.kiln, GLAZE, TODAY, a_studio(), test=False)
        except FiringTypeLocked:
            assert firing_type_locked(load)
        else:
            assert not firing_type_locked(load)


def test_fire_marks_every_member_fired_and_queues_one_ready_email_each() -> None:
    load = a_load(status=LoadStatus.FIRING, members=[3, 1, 2])
    result = fire(load, [in_load(1), in_load(2), in_load(3)], STAFF, LATER)
    assert result.load.status is LoadStatus.FIRED
    assert result.load.fired_at == LATER
    assert result.load.members == load.members
    assert [d.id for d in result.drop_offs] == [DropOffId(3), DropOffId(1), DropOffId(2)]
    for drop_off in result.drop_offs:
        assert drop_off.state is DropOffState.FIRED
        assert drop_off.fired_at == LATER
        assert drop_off.load_id == LoadId(1)
    assert [(e.drop_off_id, e.kind, e.status, e.occasion) for e in result.emails] == [
        (DropOffId(n), EmailKind.READY, EmailStatus.PENDING, "") for n in (3, 1, 2)
    ]
    assert all(email.created_at == LATER for email in result.emails)


def test_firing_again_is_refused_and_queues_nothing() -> None:
    load = a_load(status=LoadStatus.FIRING, members=[1])
    fired = fire(load, [in_load(1)], STAFF, LATER)
    with pytest.raises(AlreadyFired) as caught:
        fire(fired.load, fired.drop_offs, STAFF, LATER + timedelta(minutes=1))
    assert caught.value.message == "Load L-1 is already fired; nothing was sent again."


def test_fire_refuses_a_loading_load() -> None:
    with pytest.raises(WrongLoadStatus) as caught:
        fire(a_load(members=[1]), [in_load(1)], STAFF, LATER)
    assert caught.value.message == "Load L-1 is loading, not firing."


def test_the_page_s_checks_are_the_rules_the_changes_use() -> None:
    """A page asks `require_loading` before its name search and `require_firing` before
    "Mark L-1 fired?": the same refusals the changes raise, decided once here."""
    require_loading(a_load())
    for status in (LoadStatus.FIRING, LoadStatus.FIRED):
        with pytest.raises(LoadNotLoading, match=f"L-1 is {status}"):
            require_loading(a_load(status=status, members=[1]))
    require_firing(a_load(status=LoadStatus.FIRING, members=[1]))
    with pytest.raises(AlreadyFired):
        require_firing(a_load(status=LoadStatus.FIRED, members=[1]))
    with pytest.raises(WrongLoadStatus, match="L-1 is loading, not firing"):
        require_firing(a_load(members=[1]))


def test_fire_with_the_wrong_members_is_a_bug() -> None:
    load = a_load(status=LoadStatus.FIRING, members=[1, 2])
    for members in (
        [in_load(1)],  # one missing
        [in_load(1), in_load(2), in_load(3)],  # one extra
        [in_load(1), in_load(1), in_load(2)],  # a duplicate
    ):
        with pytest.raises(ValueError, match="exactly"):
            fire(load, members, STAFF, LATER)
    with pytest.raises(ValueError, match="AC-2 isn't in load L-1"):
        fire(load, [in_load(1), in_load(2, load=9)], STAFF, LATER)
    with pytest.raises(ValueError, match="AC-2 isn't in load L-1"):
        fire(load, [in_load(1), a_drop_off(2)], STAFF, LATER)


# delete_load


@pytest.mark.parametrize("status", [LoadStatus.LOADING, LoadStatus.FIRING])
def test_delete_load_marks_it_deleted_and_sends_its_drop_offs_back_to_waiting(status: LoadStatus) -> None:
    load = a_load(status=status, members=[1, 2])

    deleted, waiting = delete_load(load, [in_load(2), in_load(1)], "alex", LATER)

    assert deleted.status is LoadStatus.DELETED
    assert deleted.members == ()
    assert (deleted.deleted_by, deleted.deleted_at) == ("alex", LATER)
    assert [d.id for d in waiting] == [DropOffId(1), DropOffId(2)]  # in the load's order
    assert all(d.state is DropOffState.WAITING and d.load_id is None for d in waiting)


def test_delete_an_empty_load() -> None:
    deleted, waiting = delete_load(a_load(), [], STAFF, LATER)
    assert deleted.status is LoadStatus.DELETED
    assert waiting == ()


def test_a_fired_load_cant_be_deleted() -> None:
    load = a_load(status=LoadStatus.FIRED, members=[1])
    with pytest.raises(FiredLoadNotDeletable, match="L-1 is fired: a fired load can't be deleted"):
        delete_load(load, [a_drop_off(1, DropOffState.FIRED)], STAFF, LATER)


def test_a_deleted_load_is_not_found() -> None:
    with pytest.raises(NotFound, match="Load L-1 doesn't exist"):
        delete_load(a_load(status=LoadStatus.DELETED), [], STAFF, LATER)


def test_delete_load_needs_the_staff_username_and_an_aware_time() -> None:
    with pytest.raises(ValueError, match="staff username"):
        delete_load(a_load(), [], "", LATER)
    with pytest.raises(ValueError, match="aware"):
        delete_load(a_load(), [], STAFF, LATER.replace(tzinfo=None))


def test_delete_load_with_the_wrong_members_is_a_bug() -> None:
    load = a_load(members=[1, 2])
    with pytest.raises(ValueError, match="exactly load L-1's members"):
        delete_load(load, [in_load(1)], STAFF, LATER)
    with pytest.raises(ValueError, match="exactly load L-1's members"):
        delete_load(load, [in_load(1), in_load(1), in_load(2)], STAFF, LATER)
    with pytest.raises(ValueError, match="AC-2 isn't in load L-1"):
        delete_load(load, [in_load(1), in_load(2, load=9)], STAFF, LATER)


@pytest.mark.parametrize("status", list(LoadStatus))
def test_can_delete_agrees_with_require_deletable(status: LoadStatus) -> None:
    load = a_load(status=status)
    try:
        require_deletable(load)
    except FiredLoadNotDeletable, NotFound:
        assert not can_delete(load)
    else:
        assert can_delete(load)


def test_every_status_but_deleted_is_live() -> None:
    assert set(LoadStatus) - LIVE_STATUSES == {LoadStatus.DELETED}


REFUSALS: list[Callable[[], object]] = [
    lambda: add_to_load(a_load(), in_load(7, load=3), confirmed=True),
    lambda: add_to_load(a_load(), a_drop_off(7, DropOffState.REJECTED), confirmed=True),
    lambda: add_to_load(a_load(), a_glaze_drop_off(7), confirmed=False),
    lambda: remove_from_load(a_load(), a_drop_off(7)),
]


@pytest.mark.parametrize("call", REFUSALS)
def test_refusals_hold_no_personal_detail(call: Callable[[], object]) -> None:
    with pytest.raises(DomainError) as caught:
        call()
    for text in (caught.value.message, str(caught.value), repr(caught.value)):
        assert "AC-7" in text
        assert TEST_NAME not in text
        assert TEST_EMAIL not in text


# Test firings, who moved the load, and the firing record (#42)

RECORD = FiringRecord(percent_full=85, program=Program(speed=Speed.MEDIUM), max_temp_f=2236)


def test_start_load_stores_test() -> None:
    assert start_load(LoadId(4), ATHENA, BISQUE, TODAY, STAFF, NOW, a_studio(), test=True).test
    load = start_load(LoadId(4), ATHENA, BISQUE, TODAY, STAFF, NOW, a_studio())
    assert not load.test
    assert (load.firing_started_by, load.firing_started_at, load.fired_by, load.record) == (
        None,
        None,
        None,
        EMPTY_RECORD,
    )


def test_change_load_changes_test_while_loading() -> None:
    made_test = change_load(a_load(members=[1]), ATHENA, BISQUE, TODAY, a_studio(), test=True)
    assert made_test.test
    assert not change_load(made_test, ATHENA, BISQUE, TODAY, a_studio(), test=False).test


@pytest.mark.parametrize("status", [LoadStatus.FIRING, LoadStatus.FIRED])
def test_change_load_changes_test_refused_once_firing(status: LoadStatus) -> None:
    with pytest.raises(LoadNotLoading):
        change_load(a_load(status=status, members=[1]), ATHENA, BISQUE, TODAY, a_studio(), test=True)


def test_empty_regular_load_cannot_start_firing() -> None:
    with pytest.raises(EmptyLoad):
        start_firing(a_load(), STAFF, LATER)
    assert not can_start_firing(a_load())


def test_empty_test_load_starts_firing() -> None:
    load = start_firing(a_load(test=True), "alex", LATER)
    assert (load.status, load.members, load.test) == (LoadStatus.FIRING, (), True)
    assert (load.firing_started_by, load.firing_started_at) == ("alex", LATER)


def test_can_start_firing_for_empty_test() -> None:
    assert can_start_firing(a_load(test=True))
    assert not can_start_firing(a_load(status=LoadStatus.FIRING, test=True))


def test_start_firing_stamps_who_and_when() -> None:
    load = start_firing(a_load(members=[1]), "alex", LATER)
    assert (load.firing_started_by, load.firing_started_at) == ("alex", LATER)
    assert (load.started_by, load.started_at) == (STAFF, NOW)  # unchanged
    with pytest.raises(ValueError, match="username"):
        start_firing(a_load(members=[1]), "", LATER)
    with pytest.raises(ValueError, match="aware"):
        start_firing(a_load(members=[1]), "alex", LATER.replace(tzinfo=None))


def test_fire_stamps_fired_by() -> None:
    load = start_firing(a_load(members=[1]), STAFF, NOW)
    result = fire(load, [in_load(1)], "alex", LATER)
    assert (result.load.fired_by, result.load.fired_at) == ("alex", LATER)
    assert (result.load.firing_started_by, result.load.firing_started_at) == (STAFF, NOW)
    assert (result.load.started_by, result.load.started_at) == (STAFF, NOW)
    with pytest.raises(ValueError, match="username"):
        fire(load, [in_load(1)], "", LATER)


def test_empty_test_load_fires_with_no_emails() -> None:
    result = fire(start_firing(a_load(test=True), STAFF, NOW), [], "alex", LATER)
    assert result.load.status is LoadStatus.FIRED
    assert (result.drop_offs, result.emails, result.load.fired_by) == ((), (), "alex")


def test_test_load_with_drop_offs_fires_them_and_queues_their_emails() -> None:
    load = start_firing(a_load(members=[1, 2], test=True), STAFF, NOW)
    result = fire(load, [in_load(2), in_load(1)], STAFF, LATER)
    assert [(d.id, d.state) for d in result.drop_offs] == [
        (DropOffId(1), DropOffState.FIRED),
        (DropOffId(2), DropOffState.FIRED),
    ]
    assert [(e.drop_off_id, e.kind) for e in result.emails] == [
        (DropOffId(1), EmailKind.READY),
        (DropOffId(2), EmailKind.READY),
    ]


@pytest.mark.parametrize("status", sorted(LIVE_STATUSES))
def test_set_firing_record_on_loading_firing_and_fired(status: LoadStatus) -> None:
    load = a_load(status=status, members=[1])
    changed = set_firing_record(load, RECORD)
    assert changed.record == RECORD
    assert changed == replace(load, record=RECORD)  # nothing else moves
    assert set_firing_record(changed, EMPTY_RECORD).record == EMPTY_RECORD


@pytest.mark.parametrize("status", sorted(LIVE_STATUSES))
def test_set_firing_record_keeps_members(status: LoadStatus) -> None:
    load = a_load(status=status, members=[3, 1, 2])
    changed = set_firing_record(load, RECORD)
    assert (changed.members, changed.status) == (load.members, load.status)


def test_set_firing_record_deleted_load_not_found() -> None:
    with pytest.raises(NotFound):
        set_firing_record(a_load(status=LoadStatus.DELETED), RECORD)


def a_fired_load() -> Load:
    """Started at NOW, firing an hour later, fired ten hours after that."""
    firing = start_firing(a_load(members=[1]), "robin", NOW + timedelta(hours=1))
    return fire(firing, [in_load(1)], "alex", NOW + timedelta(hours=11)).load


def test_correct_step_time_each_step() -> None:
    load = a_fired_load()
    now = NOW + timedelta(days=1)
    for step, at in (
        (Step.STARTED, NOW - timedelta(minutes=30)),
        (Step.FIRING, NOW + timedelta(minutes=50)),
        (Step.FIRED, NOW + timedelta(hours=12)),
    ):
        corrected = correct_step_time(load, step, at, now)
        assert step_time(corrected, step) == at
        others = [s for s in Step if s is not step]
        assert [step_time(corrected, s) for s in others] == [step_time(load, s) for s in others]
    # Equal times keep the order: a step pressed at the same instant as the one before.
    assert correct_step_time(load, Step.FIRING, NOW, now).firing_started_at == NOW


def test_correct_step_time_not_reached() -> None:
    with pytest.raises(StepNotReached, match="L-1 hasn't reached firing"):
        correct_step_time(a_load(), Step.FIRING, NOW, LATER)
    with pytest.raises(StepNotReached, match="L-1 hasn't reached fired"):
        correct_step_time(a_load(status=LoadStatus.FIRING, members=[1]), Step.FIRED, NOW, LATER)
    assert correct_step_time(a_load(), Step.STARTED, NOW - timedelta(hours=1), LATER).started_at == (
        NOW - timedelta(hours=1)
    )


def test_correct_step_time_old_fired_load_firing_step_not_reached() -> None:
    old = a_load(status=LoadStatus.FIRED, members=[1], before_42=True)
    with pytest.raises(StepNotReached):
        correct_step_time(old, Step.FIRING, NOW, LATER)
    # Its known steps can still be corrected, in order with each other.
    assert correct_step_time(old, Step.FIRED, NOW + timedelta(hours=2), LATER).fired_at == NOW + timedelta(
        hours=2
    )
    with pytest.raises(StepTimeOutOfOrder):
        correct_step_time(old, Step.STARTED, NOW + timedelta(hours=1), LATER)


def test_correct_step_time_in_future() -> None:
    load = a_fired_load()
    now = NOW + timedelta(days=1)
    with pytest.raises(StepTimeInFuture):
        correct_step_time(load, Step.FIRED, now + timedelta(seconds=1), now)
    assert correct_step_time(load, Step.FIRED, now, now).fired_at == now


@pytest.mark.parametrize(
    ("step", "at"),
    [
        (Step.STARTED, NOW + timedelta(hours=2)),  # after firing started
        (Step.FIRING, NOW - timedelta(minutes=1)),  # before it was started
        (Step.FIRING, NOW + timedelta(hours=12)),  # after it was fired
        (Step.FIRED, NOW + timedelta(minutes=59)),  # before firing started
    ],
)
def test_correct_step_time_out_of_order_each_way(step: Step, at: datetime) -> None:
    with pytest.raises(StepTimeOutOfOrder) as caught:
        correct_step_time(a_fired_load(), step, at, NOW + timedelta(days=1))
    assert caught.value.load_id == LoadId(1)


def test_correct_step_time_keeps_who() -> None:
    load = a_fired_load()
    for step in Step:
        corrected = correct_step_time(load, step, step_time(load, step) or NOW, NOW + timedelta(days=1))
        assert (corrected.started_by, corrected.firing_started_by, corrected.fired_by) == (
            STAFF,
            "robin",
            "alex",
        )


def test_correct_step_time_naive_time_refused() -> None:
    load = a_fired_load()
    with pytest.raises(ValueError, match="aware"):
        correct_step_time(load, Step.FIRED, LATER.replace(tzinfo=None), NOW + timedelta(days=1))
    with pytest.raises(ValueError, match="aware"):
        correct_step_time(load, Step.FIRED, LATER, (NOW + timedelta(days=1)).replace(tzinfo=None))


def test_correct_step_time_deleted_load_not_found() -> None:
    with pytest.raises(NotFound):
        correct_step_time(a_load(status=LoadStatus.DELETED), Step.STARTED, NOW, LATER)
