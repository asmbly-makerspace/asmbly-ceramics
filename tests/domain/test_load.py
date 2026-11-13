from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta

import pytest

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus
from asmbly_ceramics.domain.errors import (
    AlreadyFired,
    AlreadyInLoad,
    DomainError,
    EmptyLoad,
    FiringTypeLocked,
    FiringTypeMismatch,
    ItemRetired,
    LoadFull,
    LoadNotLoading,
    NotInLoad,
    NotWaiting,
    UnknownItem,
    WrongLoadStatus,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import LOAD_CAPACITY
from asmbly_ceramics.domain.load import (
    Load,
    LoadStatus,
    add_to_load,
    change_load,
    fire,
    remove_from_load,
    start_firing,
    start_load,
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
        fire(a_load(status=LoadStatus.FIRING, members=[1]), [in_load(1)], naive)


def test_change_load_changes_kiln_and_date_and_keeps_members() -> None:
    load = a_load(members=[1, 2])
    changed = change_load(load, HELIOS, load.firing_type, TODAY + timedelta(days=1), a_studio())
    assert (changed.kiln, changed.firing_type, changed.date) == (HELIOS, BISQUE, TODAY + timedelta(days=1))
    assert changed.members == load.members
    assert changed.status is LoadStatus.LOADING


def test_change_load_changes_the_firing_type_of_an_empty_load() -> None:
    changed = change_load(a_load(), ATHENA, GLAZE, TODAY, a_studio())
    assert changed.firing_type == GLAZE


def test_change_load_refuses_a_new_firing_type_once_it_has_members() -> None:
    # Each member was added, and any mismatch confirmed, against the load's firing type (#4).
    with pytest.raises(FiringTypeLocked) as caught:
        change_load(a_load(members=[1]), ATHENA, GLAZE, TODAY, a_studio())
    assert caught.value.message == (
        "Load L-1 has drop-offs in it: remove them before changing its firing type."
    )
    assert caught.value.load_id == LoadId(1)


def test_change_load_only_while_loading() -> None:
    for status in (LoadStatus.FIRING, LoadStatus.FIRED):
        with pytest.raises(LoadNotLoading, match=f"L-1 is {status}"):
            change_load(a_load(status=status, members=[1]), HELIOS, BISQUE, TODAY, a_studio())


def test_change_load_refuses_a_retired_kiln_or_firing_type_it_changes_to() -> None:
    studio, _ = retire_item(a_studio(), CatalogList.KILNS, HELIOS, STAFF, NOW)
    with pytest.raises(ItemRetired):
        change_load(a_load(), HELIOS, BISQUE, TODAY, studio)
    studio, _ = retire_item(a_studio(), CatalogList.FIRING_TYPES, GLAZE, STAFF, NOW)
    with pytest.raises(ItemRetired):
        change_load(a_load(), ATHENA, GLAZE, TODAY, studio)


def test_change_load_checks_only_what_changes() -> None:
    # The load's kiln and firing type were retired after it was started: its date can
    # still move, and keeping them is not picking them again.
    load = a_load()
    assert (load.kiln, load.firing_type) == (ATHENA, BISQUE)
    studio, _ = retire_item(a_studio(), CatalogList.KILNS, ATHENA, STAFF, NOW)
    studio, _ = retire_item(studio, CatalogList.FIRING_TYPES, BISQUE, STAFF, NOW)
    changed = change_load(load, ATHENA, BISQUE, TODAY + timedelta(days=2), studio)
    assert changed.date == TODAY + timedelta(days=2)
    # The same holds for a load with members, whose firing type isn't changing.
    with_members = a_load(members=[1])
    assert change_load(with_members, ATHENA, BISQUE, TODAY, studio).members == with_members.members


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
    load = start_firing(a_load(members=[1]))
    assert load.status is LoadStatus.FIRING
    assert load.members == (DropOffId(1),)


def test_start_firing_refuses_an_empty_load() -> None:
    with pytest.raises(EmptyLoad, match="L-1 is empty"):
        start_firing(a_load())


@pytest.mark.parametrize("status", [LoadStatus.FIRING, LoadStatus.FIRED])
def test_start_firing_only_from_loading(status: LoadStatus) -> None:
    with pytest.raises(WrongLoadStatus) as caught:
        start_firing(a_load(status=status, members=[1]))
    assert caught.value.message == f"Load L-1 is {status}, not loading."


def test_fire_marks_every_member_fired_and_queues_one_ready_email_each() -> None:
    load = a_load(status=LoadStatus.FIRING, members=[3, 1, 2])
    result = fire(load, [in_load(1), in_load(2), in_load(3)], LATER)
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
    fired = fire(load, [in_load(1)], LATER)
    with pytest.raises(AlreadyFired) as caught:
        fire(fired.load, fired.drop_offs, LATER + timedelta(minutes=1))
    assert caught.value.message == "Load L-1 is already fired; nothing was sent again."


def test_fire_refuses_a_loading_load() -> None:
    with pytest.raises(WrongLoadStatus) as caught:
        fire(a_load(members=[1]), [in_load(1)], LATER)
    assert caught.value.message == "Load L-1 is loading, not firing."


def test_fire_with_the_wrong_members_is_a_bug() -> None:
    load = a_load(status=LoadStatus.FIRING, members=[1, 2])
    for members in (
        [in_load(1)],  # one missing
        [in_load(1), in_load(2), in_load(3)],  # one extra
        [in_load(1), in_load(1), in_load(2)],  # a duplicate
    ):
        with pytest.raises(ValueError, match="exactly"):
            fire(load, members, LATER)
    with pytest.raises(ValueError, match="AC-2 isn't in load L-1"):
        fire(load, [in_load(1), in_load(2, load=9)], LATER)
    with pytest.raises(ValueError, match="AC-2 isn't in load L-1"):
        fire(load, [in_load(1), a_drop_off(2)], LATER)


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
