"""`WaitingList` and `FindDropOffs` (#3), against the fakes. The people are made up."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from asmbly_ceramics.domain.dropoff import Contact, DropOff, DropOffState
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import OVERDUE_AFTER
from asmbly_ceramics.domain.studio import ItemStatus
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import Put, Update
from asmbly_ceramics.use_cases.waiting import SEARCH_MAX, Found
from tests.domain.builders import NOW, TEST_EMAIL, TEST_PHONE_DIGITS, a_drop_off
from tests.use_cases.conftest import World

GLAZE = ItemId("glaze")
HOUSE_DIP = ItemId("house-dip-glaze")


def stored(world: World, *drop_offs: DropOff) -> None:
    world.records.commit([Put(drop_off) for drop_off in drop_offs])


def glazed(number: int, pieces: int = 2, *, at: datetime = NOW) -> DropOff:
    drop_off = a_drop_off(number, at=at)
    return replace(drop_off, firing_type=GLAZE, glaze_type=HOUSE_DIP, pieces=pieces)


def named(number: int, name: str, state: DropOffState = DropOffState.WAITING) -> DropOff:
    """Made `number` hours before now, so a higher number is older."""
    drop_off = a_drop_off(number, state, at=NOW - timedelta(hours=number))
    return replace(drop_off, contact=Contact(name, TEST_EMAIL, TEST_PHONE_DIGITS))


def retire_firing_type(world: World, id: ItemId) -> None:
    studio = world.studio()
    firing_types = tuple(
        replace(item, status=ItemStatus.RETIRED) if item.id == id else item for item in studio.firing_types
    )
    world.records.commit([Update(replace(studio, firing_types=firing_types))])


def test_waiting_is_oldest_first_with_bisque_and_glaze_totals_in_pieces(world: World) -> None:
    newest = replace(a_drop_off(1), pieces=3)
    oldest = glazed(2, pieces=5, at=NOW - timedelta(days=3))
    middle = replace(a_drop_off(3), pieces=4, created_at=NOW - timedelta(days=1))
    stored(
        world,
        newest,
        oldest,
        middle,
        a_drop_off(4, DropOffState.IN_LOAD),
        a_drop_off(5, DropOffState.REJECTED),
    )

    view = world.waiting()

    assert [str(row.drop_off.id) for row in view.rows] == ["AC-2", "AC-3", "AC-1"]
    assert [row.days_waiting for row in view.rows] == [3, 1, 0]
    assert [(row.firing_type, row.glaze_type) for row in view.rows] == [
        ("Glaze", "House dip glaze"),
        ("Bisque", None),
        ("Bisque", None),
    ]
    assert dict(view.totals.pieces) == {ItemId("bisque"): 7, GLAZE: 5}
    assert dict(view.totals.drop_offs) == {ItemId("bisque"): 2, GLAZE: 1}
    assert dict(view.totals.pieces_by_glaze) == {HOUSE_DIP: 5}


def test_the_filter_narrows_rows_not_totals(world: World) -> None:
    stored(world, a_drop_off(1), glazed(2))

    view = world.waiting(GLAZE)

    assert [str(row.drop_off.id) for row in view.rows] == ["AC-2"]
    assert dict(view.totals.drop_offs) == {ItemId("bisque"): 1, GLAZE: 1}


def test_an_unknown_filter_gives_no_rows(world: World) -> None:
    stored(world, a_drop_off(1))

    view = world.waiting(ItemId("raku"))

    assert view.rows == ()
    assert dict(view.totals.drop_offs) == {ItemId("bisque"): 1}


def test_overdue_rows_are_marked(world: World) -> None:
    stored(
        world,
        a_drop_off(1, at=NOW - OVERDUE_AFTER),
        a_drop_off(2, at=NOW - OVERDUE_AFTER + timedelta(days=1)),
    )

    view = world.waiting()

    assert [(str(row.drop_off.id), row.overdue) for row in view.rows] == [("AC-1", True), ("AC-2", False)]
    assert view.totals.overdue == 1


def test_the_filter_offers_active_types_in_the_studios_order(world: World) -> None:
    view = world.waiting()

    assert [item.id for item in view.firing_types] == [ItemId("bisque"), GLAZE]


def test_the_filter_offers_a_retired_type_that_still_has_waiting_rows(world: World) -> None:
    stored(world, glazed(1))
    retire_firing_type(world, GLAZE)
    retire_firing_type(world, ItemId("bisque"))

    view = world.waiting()

    assert [item.id for item in view.firing_types] == [GLAZE]
    assert [row.firing_type for row in view.rows] == ["Glaze"]


def test_a_firing_type_the_studio_lacks_shows_as_its_id(world: World) -> None:
    stored(world, replace(a_drop_off(1), firing_type=ItemId("raku")))

    [row] = world.waiting().rows

    assert row.firing_type == "raku"


def test_the_waiting_list_logs_nothing(world: World, caplog: pytest.LogCaptureFixture) -> None:
    world.studio()  # seeding logs once; the list itself doesn't
    stored(world, a_drop_off(1))
    caplog.clear()

    world.waiting()
    world.find("Test")

    assert caplog.records == []


@pytest.mark.parametrize("query", ["AC-12", "ac12", "12", " ac 12 "])
def test_find_by_every_id_form(world: World, query: str) -> None:
    stored(world, a_drop_off(12), a_drop_off(1))

    assert [str(row.drop_off.id) for row in world.find(query).rows] == ["AC-12"]


def test_find_by_part_of_a_name(world: World) -> None:
    stored(world, named(1, "Ada Example"), named(2, "Grace Sample"), named(3, "Adam Placeholder"))

    found = world.find("ada").rows

    # Oldest first: AC-3 was made three hours before now, AC-1 one hour.
    assert [str(row.drop_off.id) for row in found] == ["AC-3", "AC-1"]


def test_find_by_name_covers_every_state_with_a_name(world: World) -> None:
    stored(
        world,
        named(1, "Ada Example"),
        named(2, "Ada Example", DropOffState.IN_LOAD),
        named(3, "Ada Example", DropOffState.FIRED),
        named(4, "Ada Example", DropOffState.REJECTED),
        a_drop_off(5, DropOffState.CLOSED),
    )

    found = world.find("ada").rows

    assert sorted(str(row.drop_off.id) for row in found) == ["AC-1", "AC-2", "AC-3", "AC-4"]
    assert all(not row.overdue for row in found)


def test_find_by_number_finds_a_closed_drop_off(world: World) -> None:
    stored(world, a_drop_off(7, DropOffState.CLOSED))

    [row] = world.find("AC-7").rows

    assert row.drop_off.state is DropOffState.CLOSED
    assert row.drop_off.contact is None


def test_find_an_unknown_number_finds_nothing(world: World) -> None:
    assert world.find("AC-99") == Found(rows=(), truncated=False)


def test_find_returns_at_most_50(world: World) -> None:
    stored(world, *(named(n, "Ada Example") for n in range(1, SEARCH_MAX + 6)))

    result = world.find("ada")
    found = result.rows

    assert SEARCH_MAX == 50
    assert len(found) == SEARCH_MAX
    assert result.truncated
    # The oldest 50: the highest numbers were made earliest.
    assert str(found[0].drop_off.id) == f"AC-{SEARCH_MAX + 5}"
    assert str(found[-1].drop_off.id) == "AC-6"


def test_find_waiting_only_skips_other_states(world: World) -> None:
    stored(
        world,
        named(1, "Ada Example"),
        named(2, "Ada Example", DropOffState.IN_LOAD),
        named(3, "Ada Example", DropOffState.REJECTED),
    )

    assert [str(row.drop_off.id) for row in world.find("ada", waiting_only=True).rows] == ["AC-1"]
    assert world.find("AC-2", waiting_only=True).rows == ()
    assert [str(row.drop_off.id) for row in world.find("AC-1", waiting_only=True).rows] == ["AC-1"]


@pytest.mark.parametrize("query", ["", "   ", "AC-0", "AC-0000"])
def test_an_empty_query_finds_nothing(world: World, query: str) -> None:
    stored(world, named(1, "Ada Example"))

    assert world.find(query) == Found(rows=(), truncated=False)


def test_find_does_not_search_email_or_phone(world: World) -> None:
    stored(world, named(1, "Ada Example"))

    assert world.find(TEST_EMAIL).rows == ()
    assert world.find(TEST_PHONE_DIGITS).rows == ()


def test_find_marks_a_waiting_rows_overdue(world: World) -> None:
    stored(world, replace(named(1, "Ada Example"), created_at=NOW - OVERDUE_AFTER))

    [row] = world.find("ada").rows

    assert row.overdue
    assert row.days_waiting == OVERDUE_AFTER.days


def test_find_says_when_more_matched_than_it_returns(world: World) -> None:
    stored(world, *(named(n, "Ada Example") for n in range(1, SEARCH_MAX + 1)))

    exactly = world.find("ada")
    stored(world, named(SEARCH_MAX + 1, "Ada Example"))
    one_more = world.find("ada")

    assert (len(exactly.rows), exactly.truncated) == (SEARCH_MAX, False)
    assert (len(one_more.rows), one_more.truncated) == (SEARCH_MAX, True)


def test_the_view_names_the_glaze_types_its_totals_count(world: World) -> None:
    stored(world, glazed(1), a_drop_off(2))
    studio = world.studio()
    glaze_types = tuple(
        replace(item, status=ItemStatus.RETIRED) if item.id == HOUSE_DIP else item
        for item in studio.glaze_types
    )
    world.records.commit([Update(replace(studio, glaze_types=glaze_types))])

    view = world.waiting(ItemId("bisque"))

    assert [str(row.drop_off.id) for row in view.rows] == ["AC-2"]
    assert dict(view.totals.pieces_by_glaze) == {HOUSE_DIP: 2}
    assert [(item.id, item.name) for item in view.glaze_types] == [
        (HOUSE_DIP, "House dip glaze"),
        (ItemId("commercial-glaze"), "Commercial glaze"),
    ]


def test_a_retired_glaze_type_nobody_waits_with_is_not_offered(world: World) -> None:
    studio = world.studio()
    glaze_types = tuple(replace(item, status=ItemStatus.RETIRED) for item in studio.glaze_types)
    world.records.commit([Update(replace(studio, glaze_types=glaze_types))])

    assert world.waiting().glaze_types == ()


def test_the_list_and_search_raise_when_records_are_unavailable(world: World) -> None:
    world.studio()
    world.records.fail_reads_with = RecordsUnavailable("ThrottlingException")

    with pytest.raises(RecordsUnavailable):
        world.waiting()
    with pytest.raises(RecordsUnavailable):
        world.find("ada")
    with pytest.raises(RecordsUnavailable):
        world.find("AC-1")
