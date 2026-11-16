"""Kiln loads in the console (#4): start, add three ways, refusals, change, remove, fire,
the ready emails and their retry, past loads, and who may do any of it."""

import html
import logging
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx2
import pytest

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus
from asmbly_ceramics.domain.firing import (
    CONE_READING_TEXT_MAX,
    COST_TEXT_MAX,
    FIRING_TIME_TEXT_MAX,
    NO_CONE,
    RECORD_FIELDS,
    WHOLE_RANGES,
    WITNESS_CONES,
    record_values,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import (
    COST_CENTS_MAX,
    FIRING_MINUTES_MAX,
    LOAD_CAPACITY,
    STEP_TIME_YEAR_MIN,
    STUDIO_TZ,
)
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.studio import STARTING_CONES, CatalogList
from asmbly_ceramics.mail.compose import austin_time
from asmbly_ceramics.ports.records import Conflict, Put, Update
from asmbly_ceramics.use_cases.loads import NOTES_MOVED_MAX
from asmbly_ceramics.use_cases.reject import RejectRequest
from tests.domain.builders import NOW, STAFF, TEST_EMAIL, TEST_NAME, TEST_PHONE, a_load, a_note
from tests.use_cases.flows import ATHENA, HELIOS, STAFF_MEMBER, fired, loaded, send_all
from tests.web.console.conftest import OUTSIDER, Console, events

L_1 = LoadId(1)


@pytest.fixture
def staff(console: Console) -> Console:
    console.sign_in()
    return console


def text(answer: httpx2.Response) -> str:
    return html.unescape(answer.text)


def load_of(console: Console, id: LoadId = L_1) -> Load:
    load = console.world.records.load(id)
    assert load is not None
    return load


def start(
    console: Console, *, kiln: str = "athena", firing_type: str = "bisque", day: str = ""
) -> httpx2.Response:
    fields = {"kiln": kiln, "firing_type": firing_type, "date": day or "2026-11-13"}
    return console.post("/console/loads", fields)


def add(console: Console, typed: str, *, load: LoadId = L_1, confirm: bool = False) -> httpx2.Response:
    fields = {"drop_off": typed} | ({"confirm": "1"} if confirm else {})
    return console.post(f"/console/loads/{load}/add", fields)


def edit_fields(
    console: Console, kiln: str, firing_type: str, day: str, load: LoadId = L_1
) -> dict[str, str]:
    version = str(load_of(console, load).version)
    return {"kiln": kiln, "firing_type": firing_type, "date": day, "version": version}


def state(console: Console, id: DropOffId) -> DropOffState:
    drop_off = console.world.records.drop_off(id)
    assert drop_off is not None
    return drop_off.state


def fire(console: Console, load: LoadId = L_1) -> None:
    v = str(load_of(console, load).version)
    assert console.post(f"/console/loads/{load}/start-firing", {"version": v}).status_code == 303
    v = str(load_of(console, load).version)
    assert console.post(f"/console/loads/{load}/fire", {"version": v, "confirm": "1"}).status_code == 303


# --- starting ------------------------------------------------------------------------------


def test_start_a_load_with_todays_austin_date_by_default(staff: Console) -> None:
    page = staff.get("/console/loads")
    assert page.status_code == 200
    # NOW is 12:30 on Friday 13 November in Austin.
    assert 'value="2026-11-13"' in page.text
    assert 'aria-current="page">Loads' in page.text

    answer = start(staff)

    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/loads/L-1?done=started"
    load = load_of(staff)
    assert (load.kiln, load.firing_type, load.date, load.status) == (
        ATHENA,
        "bisque",
        date(2026, 11, 13),
        LoadStatus.LOADING,
    )
    shown = text(staff.get("/console/loads"))
    assert "Athena · Bisque · Fri Nov 13" in shown
    assert "Load started by" in text(staff.get("/console/loads/L-1"))


def test_a_retired_kiln_cannot_start_a_load(staff: Console) -> None:
    version = staff.world.studio().version
    staff.world.retire_item(CatalogList.KILNS, ATHENA, version, STAFF_MEMBER)
    assert "athena" not in staff.get("/console/loads").text.split("Firing type")[0]

    answer = start(staff)

    assert answer.status_code == 400
    assert "Pick a kiln from the list." in answer.text
    assert staff.world.records.load(L_1) is None


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"kiln": "nope"}, "Pick a kiln from the list."),
        ({"firing_type": "raku"}, "Pick a firing type from the list."),
        ({"firing_type": "<b>"}, "Pick a firing type from the list."),
        ({"day": "13/11/2026"}, "Enter a date like 2026-11-13."),
        ({"day": "2026-02-30"}, "Enter a date like 2026-11-13."),
    ],
)
def test_a_bad_start_is_refused_with_its_message(
    staff: Console, fields: dict[str, str], message: str
) -> None:
    answer = start(staff, **fields)
    assert answer.status_code == 400
    assert message in answer.text
    assert staff.world.records.load(L_1) is None


def test_start_a_load_from_a_drop_off_carries_its_id(staff: Console) -> None:
    id = staff.drop_off(1)
    assert f'href="/console/loads?add={id}"' in staff.get(f"/console/drop-offs/{id}").text
    page = staff.get(f"/console/loads?add={id}")
    assert f'name="add" value="{id}"' in page.text

    answer = staff.post(
        "/console/loads", {"kiln": "athena", "firing_type": "bisque", "date": "2026-11-13", "add": str(id)}
    )

    assert answer.headers["location"] == f"/console/loads/L-1?done=started&add={id}"
    assert f'name="drop_off" value="{id}"' in staff.get(answer.headers["location"]).text


def test_an_open_load_offers_add_here_from_a_drop_off(staff: Console) -> None:
    id = staff.drop_off(1)
    start(staff)
    page = text(staff.get(f"/console/loads?add={id}"))
    assert f"Add {id} here" in page
    assert "Add AC-2 here" not in text(staff.get("/console/loads?add=<script>"))


# --- adding --------------------------------------------------------------------------------


@pytest.mark.parametrize("typed", ["AC-1", "ac1", "1"])
def test_add_by_id(staff: Console, typed: str) -> None:
    id = staff.drop_off(1)
    start(staff)

    answer = add(staff, typed)

    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/loads/L-1?done=added&id=AC-1"
    assert state(staff, id) is DropOffState.IN_LOAD
    page = staff.get(answer.headers["location"])
    assert "AC-1 added." in page.text
    assert 'id="drop_off" name="drop_off" value=""' in page.text  # cleared for the next scan
    assert "autofocus" in page.text


def test_add_by_name_lists_choices_and_adds_the_chosen_one(staff: Console) -> None:
    staff.drop_off(1, name="Robin Example")
    staff.drop_off(2, name="Robin Sample")
    staff.drop_off(3, name="Kim Other")
    start(staff)

    answer = add(staff, "robin")

    assert answer.status_code == 200
    page = text(answer)
    assert "Add AC-1" in page
    assert "Add AC-2" in page
    assert "Add AC-3" not in page
    assert state(staff, DropOffId(1)) is DropOffState.WAITING
    assert add(staff, "AC-2").status_code == 303
    assert load_of(staff).members == (DropOffId(2),)


def test_a_name_that_matches_nothing_says_so(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    answer = add(staff, "nobody")
    assert answer.status_code == 400
    assert "No waiting drop-off matches that. Check the ID, or try part of the name." in answer.text
    assert "No waiting drop-off matches that" in add(staff, "AC-99").text
    assert "Scan a slip, or type an ID or name." in add(staff, "  ").text


def test_add_from_the_waiting_list_filtered_to_the_loads_firing_type(staff: Console) -> None:
    staff.drop_off(1, firing_type="bisque")
    staff.drop_off(2, firing_type="glaze", glaze_type="house-dip-glaze")
    start(staff)

    page = text(staff.get("/console/loads/L-1"))

    waiting = page.split("Waiting · Bisque")[1]
    assert "AC-1" in waiting
    assert "AC-2" not in waiting
    assert add(staff, "AC-1").status_code == 303
    assert load_of(staff).members == (DropOffId(1),)


def test_show_all_firing_types_lifts_the_filter(staff: Console) -> None:
    staff.drop_off(1, firing_type="bisque")
    staff.drop_off(2, firing_type="glaze", glaze_type="house-dip-glaze")
    start(staff)
    page = text(staff.get("/console/loads/L-1?all=1"))
    waiting = page.split("Waiting · all firing types")[1]
    assert "AC-1" in waiting
    assert "AC-2" in waiting


def test_adding_from_all_firing_types_comes_back_to_all_firing_types(staff: Console) -> None:
    """A mixed load: "Show all firing types" stays open after each Add, and after a refusal."""
    staff.drop_off(1, firing_type="bisque")
    staff.drop_off(2, firing_type="glaze", glaze_type="house-dip-glaze")
    staff.drop_off(3, firing_type="glaze", glaze_type="house-dip-glaze")
    start(staff)
    page = staff.get("/console/loads/L-1?all=1").text
    assert '<input type="hidden" name="all" value="1">' in page

    added = staff.post("/console/loads/L-1/add", {"drop_off": "AC-2", "confirm": "1", "all": "1"})

    assert added.status_code == 303
    assert added.headers["location"] == "/console/loads/L-1?done=added&id=AC-2&all=1"
    asked = text(staff.post("/console/loads/L-1/add", {"drop_off": "AC-3", "all": "1"}))
    assert "Waiting · all firing types" in asked
    plain = add(staff, "AC-1")
    assert plain.headers["location"] == "/console/loads/L-1?done=added&id=AC-1"
    assert '<input type="hidden" name="all"' not in staff.get("/console/loads/L-1").text


def test_a_load_started_at_the_same_moment_as_another_is_refused_not_a_500(staff: Console) -> None:
    staff.world.studio()  # seeded, so the next commit is the load's
    staff.world.records.fail_next_commit_with = Conflict([])

    answer = start(staff, day="2026-11-14")

    assert answer.status_code == 409
    assert "Another load was started at the same moment, and this one wasn't saved. Try again." in text(
        answer
    )
    assert 'value="2026-11-14"' in answer.text  # what was picked stays picked
    assert staff.world.records.load(L_1) is None


def test_a_drop_off_that_isnt_waiting_is_refused_with_the_reason(staff: Console) -> None:
    world = staff.world
    in_other, done, refused = staff.drop_off(1), staff.drop_off(2), staff.drop_off(3)
    loaded(world, in_other)  # L-1
    fired(world, done)  # L-2, in Athena
    world.reject(RejectRequest(refused, ItemId("other"), "made-up words", version=1, staff=STAFF_MEMBER))
    start(staff)  # L-3

    other = add(staff, "AC-1", load=LoadId(3))
    assert "AC-1 is already in load L-1." in text(other)
    fired_answer = text(add(staff, "AC-2", load=LoadId(3)))
    assert "AC-2 isn't waiting: it is fired." in fired_answer
    assert "Fired in Athena on Nov 13." in fired_answer
    assert "AC-3 isn't waiting: it is rejected." in text(add(staff, "AC-3", load=LoadId(3)))
    assert load_of(staff, LoadId(3)).members == ()


def test_a_different_firing_type_asks_for_confirmation_then_adds_on_confirm(staff: Console) -> None:
    staff.drop_off(1, firing_type="bisque")
    start(staff, firing_type="glaze")

    asked = add(staff, "AC-1")

    assert asked.status_code == 409
    assert "AC-1 is Bisque. This load is Glaze." in text(asked)
    assert "Add anyway" in asked.text
    assert "Don't add" in asked.text
    assert "'s firing type is" not in text(asked)  # the slugs' message isn't for staff
    assert load_of(staff).members == ()

    assert add(staff, "AC-1", confirm=True).status_code == 303
    assert load_of(staff).members == (DropOffId(1),)


def test_dont_add_leaves_the_load_unchanged(staff: Console) -> None:
    staff.drop_off(1, firing_type="bisque")
    start(staff, firing_type="glaze")
    asked = add(staff, "AC-1")
    assert 'href="/console/loads/L-1">Don\'t add</a>' in asked.text
    staff.get("/console/loads/L-1")
    assert load_of(staff).members == ()
    assert state(staff, DropOffId(1)) is DropOffState.WAITING


def test_a_load_holds_at_most_48(staff: Console) -> None:
    ids = []
    for n in range(1, LOAD_CAPACITY + 2):
        if n % 20 == 0:
            staff.world.clock.advance(timedelta(minutes=11))  # past the form's rate limit
        ids.append(staff.drop_off(n))
    loaded(staff.world, *ids[:LOAD_CAPACITY])

    answer = add(staff, str(ids[-1]))

    assert "Load L-1 already holds 48 drop-offs." in text(answer)
    assert state(staff, ids[-1]) is DropOffState.WAITING


# --- the page, changing and removing --------------------------------------------------------


def test_the_load_page_shows_contents_and_totals(staff: Console) -> None:
    staff.drop_off(1)
    staff.drop_off(2)
    start(staff)
    add(staff, "AC-1")
    add(staff, "AC-2")

    page = text(staff.get("/console/loads/L-1"))

    assert "Athena · Bisque · Fri Nov 13" in page
    assert TEST_NAME in page
    assert "2 drop-offs · " in page
    assert "/console/drop-offs/AC-1/photos/1/thumb" in page
    assert re.search(r'<li aria-current="step">\s*<span class="step-label">1 Loading</span>', page)
    assert page.count(">Remove</button>") == 2
    assert TEST_EMAIL not in page
    assert TEST_PHONE not in page


def test_an_empty_load_says_how_to_add_and_cannot_start_firing(staff: Console) -> None:
    start(staff)
    page = text(staff.get("/console/loads/L-1"))
    assert "Nothing in this load yet. Scan a slip, search, or tap Add in the waiting list." in page
    assert "disabled" in page.split("Start firing")[0].rsplit("<button", 1)[1]
    assert "Add a drop-off first." in page


def test_start_firing_an_empty_load_is_refused(staff: Console) -> None:
    start(staff)
    answer = staff.post("/console/loads/L-1/start-firing", {"version": str(load_of(staff).version)})
    assert answer.status_code == 400
    assert "Load L-1 is empty: add a drop-off before firing." in answer.text
    assert load_of(staff).status is LoadStatus.LOADING


def test_change_kiln_and_date_of_a_load_with_drop_offs_in_it(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    fields = {
        "kiln": "helios",
        "firing_type": "bisque",
        "date": "2026-11-14",
        "version": str(load_of(staff).version),
    }

    answer = staff.post("/console/loads/L-1/edit", fields)

    assert answer.status_code == 303
    load = load_of(staff)
    assert (load.kiln, load.date) == (HELIOS, date(2026, 11, 14))
    assert "Load changed." in staff.get(answer.headers["location"]).text


def test_the_firing_type_is_read_only_once_the_load_has_drop_offs(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    page = text(staff.get("/console/loads/L-1"))
    assert '<select id="edit-firing" disabled' in page
    assert "Remove its drop-offs to change the firing type." in page

    fields = {
        "kiln": "athena",
        "firing_type": "glaze",
        "date": "2026-11-13",
        "version": str(load_of(staff).version),
    }
    answer = staff.post("/console/loads/L-1/edit", fields)

    assert "Load L-1 has drop-offs in it: remove them before changing its firing type." in text(answer)
    assert load_of(staff).firing_type == "bisque"

    start(staff)  # L-2, empty
    fields["version"] = str(load_of(staff, LoadId(2)).version)
    assert staff.post("/console/loads/L-2/edit", fields).status_code == 303
    assert load_of(staff, LoadId(2)).firing_type == "glaze"


def test_a_kiln_change_with_too_many_notes_is_refused_not_a_500(staff: Console) -> None:
    start(staff)
    load = load_of(staff)
    studio = staff.world.studio()
    notes = [
        a_note(number, load, glaze_types=(), clay_bodies=(), studio=studio)
        for number in range(1, NOTES_MOVED_MAX + 2)
    ]
    staff.world.records.commit([Put(note) for note in notes])

    answer = staff.post("/console/loads/L-1/edit", edit_fields(staff, "helios", "bisque", "2026-11-13"))

    assert answer.status_code == 400
    assert f"Load L-1 has more than {NOTES_MOVED_MAX} notes, so its kiln can't be changed." in text(answer)
    assert load_of(staff).kiln == ATHENA


def test_the_edit_form_keeps_a_retired_kiln_selected(staff: Console) -> None:
    start(staff)
    staff.world.retire_item(CatalogList.KILNS, ATHENA, staff.world.studio().version, STAFF_MEMBER)
    page = text(staff.get("/console/loads/L-1"))
    assert '<option value="athena" selected>Athena (retired)</option>' in page
    fields = {
        "kiln": "athena",
        "firing_type": "bisque",
        "date": "2026-11-20",
        "version": str(load_of(staff).version),
    }
    assert staff.post("/console/loads/L-1/edit", fields).status_code == 303
    assert (load_of(staff).kiln, load_of(staff).date) == (ATHENA, date(2026, 11, 20))
    fields = fields | {"kiln": "nope", "version": str(load_of(staff).version)}
    assert "Pick a kiln from the list." in staff.post("/console/loads/L-1/edit", fields).text


def test_remove_puts_it_back_in_the_waiting_list(staff: Console) -> None:
    id = staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")

    answer = staff.post("/console/loads/L-1/remove", {"drop_off": "AC-1"})

    assert answer.status_code == 303
    assert "AC-1 is back in the waiting list." in staff.get(answer.headers["location"]).text
    assert state(staff, id) is DropOffState.WAITING
    assert load_of(staff).members == ()


def test_nothing_can_be_added_or_removed_once_firing(staff: Console) -> None:
    staff.drop_off(1)
    staff.drop_off(2)
    start(staff)
    add(staff, "AC-1")
    staff.post("/console/loads/L-1/start-firing", {"version": str(load_of(staff).version)})
    assert load_of(staff).status is LoadStatus.FIRING
    page = text(staff.get("/console/loads/L-1"))
    assert ">Remove<" not in page
    assert "Add by ID or name" not in page

    assert "Load L-1 is firing: nothing can be added or removed." in text(add(staff, "AC-2"))
    removed = staff.post("/console/loads/L-1/remove", {"drop_off": "AC-1"})
    assert "Load L-1 is firing: nothing can be added or removed." in text(removed)
    assert load_of(staff).members == (DropOffId(1),)


# --- firing --------------------------------------------------------------------------------


def test_mark_fired_asks_first_and_fires_only_on_confirm(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    staff.post("/console/loads/L-1/start-firing", {"version": str(load_of(staff).version)})

    asked = staff.post("/console/loads/L-1/fire", {"version": str(load_of(staff).version)})

    assert asked.status_code == 200
    assert "Mark L-1 fired?" in asked.text
    assert "This emails 1 person" in text(asked)
    assert load_of(staff).status is LoadStatus.FIRING
    assert not [e for e in staff.world.records.emails_for(DropOffId(1)) if e.kind is EmailKind.READY]


def test_mark_fired_queues_one_ready_email_per_drop_off(staff: Console) -> None:
    for n in (1, 2, 3):
        staff.drop_off(n)
        start(staff) if n == 1 else None
        add(staff, f"AC-{n}")

    fire(staff)

    assert load_of(staff).status is LoadStatus.FIRED
    for n in (1, 2, 3):
        assert state(staff, DropOffId(n)) is DropOffState.FIRED
        ready = [e for e in staff.world.records.emails_for(DropOffId(n)) if e.kind is EmailKind.READY]
        assert [e.status for e in ready] == [EmailStatus.PENDING]
    assert "Marked fired." in staff.get("/console/loads/L-1?done=fired").text


def test_marking_fired_again_sends_nothing(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    fire(staff)
    send_all(staff.world)
    sent = len(staff.world.mailer.sent)

    again = staff.post("/console/loads/L-1/fire", {"version": "1", "confirm": "1"})
    asked = staff.post("/console/loads/L-1/fire", {"version": "1"})

    assert "Load L-1 is already fired; nothing was sent again." in again.text
    assert "Load L-1 is already fired; nothing was sent again." in asked.text
    send_all(staff.world)
    assert len(staff.world.mailer.sent) == sent


def test_a_fired_load_and_its_drop_offs_cannot_be_changed(staff: Console) -> None:
    staff.drop_off(1)
    staff.drop_off(2)
    start(staff)
    add(staff, "AC-1")
    fire(staff)

    edit = staff.post("/console/loads/L-1/edit", edit_fields(staff, "helios", "bisque", "2026-11-14"))
    assert "Load L-1 is fired: nothing can be added or removed." in text(edit)
    assert "Load L-1 is fired" in text(add(staff, "AC-2"))
    assert "Load L-1 is fired" in text(staff.post("/console/loads/L-1/remove", {"drop_off": "AC-1"}))
    reject = staff.post(
        "/console/drop-offs/AC-1/reject",
        {"reason": "other", "message": "x", "version": staff.version(DropOffId(1))},
    )
    assert "AC-1 isn&#39;t waiting: it is fired." in reject.text
    assert load_of(staff).members == (DropOffId(1),)
    assert load_of(staff).kiln == ATHENA
    assert state(staff, DropOffId(1)) is DropOffState.FIRED


def test_a_failed_email_is_shown_by_id_and_retry_clears_it(staff: Console) -> None:
    world = staff.world
    for n in range(1, 13):
        staff.drop_off(n)
    send_all(world)  # the received emails
    start(staff)
    for n in range(1, 13):
        add(staff, f"AC-{n}")
    fire(staff)
    world.mailer.fail_with = "MessageRejected"
    world.send_email(DropOffId(5), EmailKind.READY, "")
    world.mailer.fail_with = None
    send_all(world)

    page = text(staff.get("/console/loads/L-1"))

    assert "11 of 12 emails sent" in page
    assert "AC-5: Sending failed (MessageRejected)" in " ".join(re.sub(r"<[^>]+>", "", page).split())
    assert page.count("Try sending again") == 1

    answer = staff.post("/console/loads/L-1/emails/AC-5/retry")
    assert answer.status_code == 303
    assert "The email to AC-5 will be sent again." in staff.get(answer.headers["location"]).text
    send_all(world)
    page = text(staff.get("/console/loads/L-1"))
    assert "12 of 12 emails sent" in page
    assert "Try sending again" not in page


def test_retry_from_the_load_sends_only_to_that_drop_off(staff: Console) -> None:
    world = staff.world
    staff.drop_off(1)
    staff.drop_off(2)
    send_all(world)
    start(staff)
    add(staff, "AC-1")
    add(staff, "AC-2")
    fire(staff)
    world.mailer.fail_with = "MessageRejected"
    send_all(world)
    world.mailer.fail_with = None
    sent = len(world.mailer.sent)

    staff.post("/console/loads/L-1/emails/AC-1/retry")
    send_all(world)

    assert len(world.mailer.sent) == sent + 1
    other = world.records.email(DropOffId(2), EmailKind.READY)
    assert other is not None
    assert other.status is EmailStatus.FAILED
    assert staff.post("/console/loads/L-1/emails/AC-9/retry").status_code == 404  # not in this load


def test_past_loads_stay_viewable_with_their_contents(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    fire(staff)
    listed = text(staff.get("/console/loads"))
    assert "Past loads" in listed
    assert "Athena · Bisque · Fri Nov 13" in listed.split("Past loads")[1]
    page = text(staff.get("/console/loads/L-1"))
    assert "AC-1" in page
    assert TEST_NAME in page
    assert "Fired" in page
    assert re.search(r'<li aria-current="step">\s*<span class="step-label">3 Fired</span>', page)


def test_a_past_load_whose_drop_offs_closed_shows_them_closed(staff: Console) -> None:
    world = staff.world
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    fire(staff)
    send_all(world)
    world.clock.advance(timedelta(days=40))
    assert world.close().closed == (DropOffId(1),)

    page = text(staff.get("/console/loads/L-1"))

    assert page.count("Closed") >= 1
    assert TEST_NAME not in page
    assert "/photos/1/thumb" not in page


def test_a_conflicting_change_is_reported_and_nothing_is_stored(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    before = load_of(staff)

    staff.world.records.fail_next_commit_with = Conflict(["L-1"])

    answer = add(staff, "AC-1")

    assert answer.status_code == 409
    assert "L-1 changed while you were working. Here it is now; try again." in answer.text
    assert load_of(staff) == before

    fields = {"kiln": "helios", "firing_type": "bisque", "date": "2026-11-14", "version": "99"}
    stale = staff.post("/console/loads/L-1/edit", fields)  # an older page's version
    assert stale.status_code == 409
    assert "L-1 changed while you were working." in stale.text
    assert load_of(staff).kiln == ATHENA


def test_an_unknown_load_or_a_malformed_id_is_404(staff: Console) -> None:
    assert staff.get("/console/loads/L-9").status_code == 404
    assert staff.get("/console/loads/L-0").status_code == 404
    assert staff.get("/console/loads/x").status_code == 404
    assert add(staff, "AC-1", load=LoadId(9)).status_code == 404
    assert staff.post("/console/loads/L-1/start-firing", {"version": "x"}).status_code in (400, 404)


def test_load_pages_log_ids_and_the_username_only(staff: Console, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.INFO)
    staff.drop_off(1)
    caplog.clear()
    start(staff)
    add(staff, "Test")  # a name search: never logged
    add(staff, "AC-1")
    fire(staff)

    assert ("load_started", STAFF) in events(caplog)
    assert ("added_to_load", STAFF) in events(caplog)
    assert ("load_fired", STAFF) in events(caplog)
    for record in caplog.records:
        line = repr(vars(record))
        for detail in (TEST_NAME, TEST_EMAIL, TEST_PHONE, "Test"):
            assert detail not in line


def test_markup_in_a_name_or_the_add_field_is_escaped(staff: Console) -> None:
    hostile = 'Robin "><script>x()</script>'
    staff.drop_off(1, name=hostile)
    start(staff)

    found = add(staff, '"><script>')
    page = staff.get("/console/loads/L-1")
    add(staff, "AC-1")
    loaded_page = staff.get("/console/loads/L-1")

    for answer in (found, page, loaded_page):
        assert "<script>" not in answer.text
        assert "&lt;script&gt;" in answer.text


def test_a_fire_whose_outcome_is_unknown_says_to_check_and_a_retry_sends_nothing_twice(
    staff: Console,
) -> None:
    from asmbly_ceramics.ports.records import CommitOutcomeUnknown

    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    staff.post("/console/loads/L-1/start-firing", {"version": str(load_of(staff).version)})
    version = str(load_of(staff).version)
    staff.world.records.fail_next_commit_with = CommitOutcomeUnknown("RequestTimeout")

    answer = staff.post("/console/loads/L-1/fire", {"version": version, "confirm": "1"})

    assert answer.status_code == 503
    assert "That may or may not have been saved. Reload the load to check before trying again." in text(
        answer
    )
    fire_again = staff.post("/console/loads/L-1/fire", {"version": version, "confirm": "1"})
    assert fire_again.status_code == 303  # nothing had landed: this one fires it
    again = staff.post("/console/loads/L-1/fire", {"version": version, "confirm": "1"})
    assert "Load L-1 is already fired; nothing was sent again." in again.text
    ready = [e for e in staff.world.records.emails_for(DropOffId(1)) if e.kind is EmailKind.READY]
    assert len(ready) == 1


def test_a_stale_page_s_name_search_or_fire_says_why_nothing_happened(staff: Console) -> None:
    staff.drop_off(1, name="Robin Example")
    staff.drop_off(2, name="Robin Sample")
    start(staff)
    early = staff.post("/console/loads/L-1/fire", {"version": str(load_of(staff).version)})
    assert "Load L-1 is loading, not firing." in early.text
    add(staff, "AC-1")
    staff.post("/console/loads/L-1/start-firing", {"version": str(load_of(staff).version)})

    answer = add(staff, "robin")

    assert "Load L-1 is firing: nothing can be added or removed." in text(answer)
    assert load_of(staff).members == (DropOffId(1),)


def test_the_load_pages_build_no_refusal_of_their_own() -> None:
    """#4's status rules live in `domain/load.py` (`require_loading`, `require_firing`):
    the pages ask them, and never construct the domain's errors themselves."""
    import inspect

    from asmbly_ceramics.web.console import loads as page

    source = inspect.getsource(page)
    for error in (
        "LoadNotLoading(",
        "AlreadyFired(",
        "WrongLoadStatus(",
        "NotWaiting(",
        "EmptyLoad(",
        "FiredLoadNotDeletable(",
    ):
        assert error not in source, error


# --- deleting a load started by mistake ----------------------------------------------------


def delete(console: Console, typed: str | None = None, *, version: int | None = None) -> httpx2.Response:
    fields = {"version": str(load_of(console).version if version is None else version)}
    if typed is not None:
        fields |= {"confirm": "1", "typed_id": typed}
    return console.post("/console/loads/L-1/delete", fields)


def test_a_loading_load_offers_delete_behind_a_closed_panel(staff: Console) -> None:
    start(staff)
    page = text(staff.get("/console/loads/L-1"))
    assert "<summary>Delete this load</summary>" in page
    assert 'action="/console/loads/L-1/delete"' in page
    assert "Delete L-1…" in page
    assert 'name="typed_id"' not in page  # the confirmation comes only after asking


def test_delete_asks_first_and_names_what_goes_back_to_waiting(staff: Console) -> None:
    staff.drop_off(1)
    staff.drop_off(2)
    start(staff)
    add(staff, "AC-1")
    add(staff, "AC-2")

    asked = delete(staff)

    assert asked.status_code == 200
    page = text(asked)
    assert "Delete load L-1?" in page
    assert "This can't be undone." in page
    assert "its notes are removed with it" in page
    assert "2 drop-offs in it go back to the waiting list" in page
    assert "AC-1, AC-2" in page
    assert 'name="typed_id"' in page
    assert "Delete L-1 for good" in page
    assert "<summary>Delete this load</summary>" not in page
    assert load_of(staff).status is LoadStatus.LOADING
    assert state(staff, DropOffId(1)) is DropOffState.IN_LOAD


@pytest.mark.parametrize("typed", ["", "L-2", "AC-1", "yes", "L-11"])
def test_delete_refuses_unless_the_load_id_is_typed_exactly(staff: Console, typed: str) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")

    refused = delete(staff, typed)

    assert refused.status_code == 400
    assert "Type L-1 exactly to delete this load." in text(refused)
    assert "Delete load L-1?" in text(refused)  # still asking
    assert load_of(staff).status is LoadStatus.LOADING
    assert state(staff, DropOffId(1)) is DropOffState.IN_LOAD


@pytest.mark.parametrize("typed", ["L-1", " l-1 "])
def test_delete_with_the_id_typed_deletes_and_returns_to_the_list(
    staff: Console, typed: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")

    done = delete(staff, typed)

    assert done.status_code == 303
    assert done.headers["location"] == "/console/loads?done=deleted&load=L-1"
    assert load_of(staff).status is LoadStatus.DELETED
    assert state(staff, DropOffId(1)) is DropOffState.WAITING
    listed = text(staff.get(done.headers["location"]))
    assert "Load L-1 deleted. Its drop-offs are back in the waiting list." in listed
    assert "/console/loads/L-1" not in listed
    assert staff.get("/console/loads/L-1").status_code == 404
    assert delete(staff, "L-1").status_code == 404
    assert ("load_deleted", STAFF) in events(caplog)


def test_a_firing_load_can_be_deleted_with_a_warning(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    staff.post("/console/loads/L-1/start-firing", {"version": str(load_of(staff).version)})

    asked = text(delete(staff))
    assert "This load is firing. Delete it only if it was never really put in the kiln." in re.sub(
        r"</?strong>", "", asked
    )
    assert delete(staff, "L-1").status_code == 303
    assert state(staff, DropOffId(1)) is DropOffState.WAITING


def test_a_fired_load_cannot_be_deleted(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    fire(staff)
    assert "Delete this load" not in text(staff.get("/console/loads/L-1"))

    for answer in (delete(staff), delete(staff, "L-1")):
        assert answer.status_code == 400
        assert "Load L-1 is fired: a fired load can't be deleted." in text(answer)
    assert load_of(staff).status is LoadStatus.FIRED


def test_delete_from_a_stale_page_is_a_conflict(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    shown = load_of(staff).version
    add(staff, "AC-1")

    answer = delete(staff, "L-1", version=shown)

    assert answer.status_code == 409
    assert "L-1 changed while you were working" in text(answer)
    assert load_of(staff).status is LoadStatus.LOADING


def test_a_delete_with_too_many_notes_is_refused_not_a_500(staff: Console) -> None:
    start(staff)
    load = load_of(staff)
    studio = staff.world.studio()
    notes = [a_note(number, load, glaze_types=(), clay_bodies=(), studio=studio) for number in range(1, 100)]
    staff.world.records.commit([Put(note) for note in notes])

    answer = delete(staff, "L-1")

    assert answer.status_code == 400
    assert "Load L-1 has more than 98 notes, so it can't be deleted. Remove some of its notes first." in text(
        answer
    )
    assert load_of(staff).status is LoadStatus.LOADING


def test_the_deleted_notice_never_echoes_what_is_in_the_address(staff: Console) -> None:
    page = text(staff.get("/console/loads?done=deleted&load=<b>hi</b>"))
    assert "deleted" not in page.split("<h2>Loads</h2>", 1)[1].split("Start a load", 1)[0]
    assert "<b>hi</b>" not in page


def test_a_delete_that_may_not_have_landed_says_so(staff: Console) -> None:
    from asmbly_ceramics.ports.records import CommitOutcomeUnknown

    start(staff)
    staff.world.records.fail_next_commit_with = CommitOutcomeUnknown("RequestTimeout")

    answer = delete(staff, "L-1")

    assert answer.status_code == 503
    assert "That may or may not have been saved." in text(answer)


# --- test firings (#42) ----------------------------------------------------------------------


def test_start_test_load(staff: Console) -> None:
    form = text(staff.get("/console/loads"))
    assert 'name="test" value="1"' in form
    assert "This is a test firing" in form

    answer = staff.post(
        "/console/loads", {"kiln": "athena", "firing_type": "bisque", "date": "2026-11-13", "test": "1"}
    )

    assert answer.status_code == 303
    assert load_of(staff).test is True


@pytest.mark.parametrize("value", ["on", "true", "yes", "0", "", "1 "])
def test_test_checkbox_other_value_is_false(staff: Console, value: str) -> None:
    fields = {"kiln": "athena", "firing_type": "bisque", "date": "2026-11-13", "test": value}
    assert staff.post("/console/loads", fields).status_code == 303
    assert load_of(staff).test is False


def test_a_refused_start_keeps_the_test_box_ticked(staff: Console) -> None:
    answer = staff.post(
        "/console/loads", {"kiln": "athena", "firing_type": "bisque", "date": "x", "test": "1"}
    )
    assert answer.status_code == 400
    assert 'name="test" value="1" checked' in answer.text


def test_empty_test_load_can_start_firing(staff: Console) -> None:
    staff.post(
        "/console/loads", {"kiln": "athena", "firing_type": "bisque", "date": "2026-11-13", "test": "1"}
    )
    page = text(staff.get("/console/loads/L-1"))
    assert "disabled" not in page.split("Start firing")[0].rsplit("<button", 1)[1]
    assert "Add a drop-off first." not in page

    fire(staff)

    assert load_of(staff).status is LoadStatus.FIRED
    assert send_all(staff.world) == []  # no one is emailed


def test_empty_test_load_fire_confirm_says_no_one_emailed(staff: Console) -> None:
    staff.post(
        "/console/loads", {"kiln": "athena", "firing_type": "bisque", "date": "2026-11-13", "test": "1"}
    )
    v = str(load_of(staff).version)
    assert staff.post("/console/loads/L-1/start-firing", {"version": v}).status_code == 303
    asked = staff.post("/console/loads/L-1/fire", {"version": str(load_of(staff).version)})
    assert asked.status_code == 200
    assert "The load is empty. No one is emailed." in text(asked)
    assert "This emails" not in text(asked)


def test_test_tag_on_lists_and_page(staff: Console) -> None:
    staff.post(
        "/console/loads", {"kiln": "athena", "firing_type": "bisque", "date": "2026-11-13", "test": "1"}
    )
    start(staff)  # L-2, not a test
    listed = text(staff.get("/console/loads"))
    assert listed.count('<span class="tag">Test</span>') == 1
    assert 'L-1</span> <span class="tag">Test</span>' in listed
    assert '<span class="tag">Test</span>' in text(staff.get("/console/loads/L-1"))
    assert '<span class="tag">Test</span>' not in text(staff.get("/console/loads/L-2"))

    fire(staff)  # the fired list tags it too
    fired_list = text(staff.get("/console/loads")).split("Past loads")[1]
    assert 'L-1</span> <span class="tag">Test</span>' in fired_list


def test_change_load_marks_test(staff: Console) -> None:
    start(staff)
    page = text(staff.get("/console/loads/L-1"))
    assert 'id="edit-test" name="test" value="1"' in page

    fields = edit_fields(staff, "athena", "bisque", "2026-11-13") | {"test": "1"}
    assert staff.post("/console/loads/L-1/edit", fields).status_code == 303
    assert load_of(staff).test is True
    assert 'id="edit-test" name="test" value="1" checked' in text(staff.get("/console/loads/L-1"))

    fields = edit_fields(staff, "athena", "bisque", "2026-11-13")  # the box left unticked
    assert staff.post("/console/loads/L-1/edit", fields).status_code == 303
    assert load_of(staff).test is False


# --- the firing record (#42) ---------------------------------------------------------------

CONE_6 = STARTING_CONES[2].id


def save_record(
    console: Console, fields: dict[str, str], *, load: LoadId = L_1, version: str = ""
) -> httpx2.Response:
    """As the form posts it: every field, the stored ones kept unless `fields` changes them."""
    stored = console.world.records.load(load)
    kept = record_values(stored.record) if stored is not None else {}
    kept = {name: value for name, value in kept.items() if value != "none"}  # sent by a box
    v = version or str(load_of(console, load).version)
    return console.post(f"/console/loads/{load}/record", {"version": v} | kept | fields)


def test_record_saved_redirects_and_shows(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    fields = {
        "percent_full": "80",
        "cone": CONE_6,
        "speed": "slow",
        "firing_time": "11:38",
        "max_temp_f": "2236",
        "cost": "8.19",
    }

    answer = save_record(staff, fields)

    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/loads/L-1?done=record"
    record = load_of(staff).record
    assert (record.percent_full, record.max_temp_f, record.cost_cents, record.firing_minutes) == (
        80,
        2236,
        819,
        698,
    )
    assert load_of(staff).members == (DropOffId(1),)  # nothing else changed
    page = text(staff.get(answer.headers["location"]))
    assert "Firing record saved." in page
    assert 'name="percent_full" value="80"' in page
    assert 'name="cost" value="8.19"' in page
    assert f'<option value="{CONE_6}" selected>^6</option>' in page
    assert "Firing record: % full: 80%" in page  # the history line


def test_record_invalid_fields_shown_and_kept(staff: Console) -> None:
    start(staff)
    before = load_of(staff)

    answer = save_record(staff, {"percent_full": "101", "cost": "lots", "max_temp_f": "2236"})

    assert answer.status_code == 422
    page = text(answer)
    assert "Check the firing record: 2 fields need fixing." in page
    assert "Enter a whole number from 0 to 100." in page
    assert "Enter the cost in dollars, like 8.19, up to $100.00." in page
    assert 'name="max_temp_f" value="2236"' in page  # what was typed stays
    assert 'name="cost" value="lots"' in page
    assert 'aria-describedby="rec-cost-error"' in page
    assert '<a href="#rec-percent_full">% full: ' in page
    assert load_of(staff) == before


def test_markup_typed_in_the_record_or_a_step_time_is_escaped(staff: Console) -> None:
    start(staff)
    markup = '"><script>x()</script>'

    record = save_record(staff, {"cost": markup})
    step = correct(staff, "started", markup)

    for answer in (record, step):
        assert answer.status_code == 422
        assert "<script>" not in answer.text
        assert "&lt;script&gt;" in answer.text
    assert 'name="cost" value="&#34;&gt;&lt;script&gt;' in record.text
    assert 'name="at" value="&#34;&gt;&lt;script&gt;' in step.text


def test_a_refused_record_takes_the_focus_from_the_add_field(staff: Console) -> None:
    start(staff)  # loading: the add field has the focus on an ordinary page
    assert re.search(r'<input type="text" id="drop_off"[^>]* autofocus', staff.get("/console/loads/L-1").text)

    for answer in (save_record(staff, {"cost": "lots"}), save_record(staff, {"cost": "1"}, version="99")):
        page = answer.text
        assert answer.status_code in (409, 422)
        assert 'id="record-summary" autofocus' in page
        assert page.count("autofocus") == 1


def test_record_conflict_message(staff: Console) -> None:
    start(staff)
    before = load_of(staff)
    answer = save_record(staff, {"percent_full": "70"}, version="99")
    assert answer.status_code == 409
    assert "Someone else changed this load. Check it and save again." in text(answer)
    assert 'name="percent_full" value="70"' in answer.text
    assert load_of(staff) == before


def test_record_on_fired_load(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    fire(staff)
    send_all(staff.world)  # the received and ready emails

    answer = save_record(staff, {"board_temp_f": "212"})

    assert answer.status_code == 303
    assert load_of(staff).status is LoadStatus.FIRED
    assert load_of(staff).record.board_temp_f == 212
    assert send_all(staff.world) == []  # no email queued by the save
    assert 'id="record"' in text(staff.get("/console/loads/L-1"))


def test_record_needs_csrf(staff: Console) -> None:
    start(staff)
    before = load_of(staff)
    v = str(before.version)
    answer = staff.post("/console/loads/L-1/record", {"version": v, "percent_full": "50"}, csrf=False)
    assert answer.status_code == 403
    assert load_of(staff) == before


def test_record_not_in_group_not_allowed(console: Console) -> None:
    console.world.start_load(ATHENA, ItemId("bisque"), None, STAFF_MEMBER)
    console.sign_in(groups=("front-desk",), username=OUTSIDER)
    answer = console.post("/console/loads/L-1/record", {"version": "1", "percent_full": "50"})
    assert answer.status_code == 403
    assert "You don't have access to the ceramics console." in text(answer)
    assert load_of(console).record.percent_full is None


def test_record_signed_out_says_to_sign_in(console: Console) -> None:
    console.world.start_load(ATHENA, ItemId("bisque"), None, STAFF_MEMBER)
    answer = console.post("/console/loads/L-1/record", {"version": "1", "percent_full": "50"}, csrf=False)
    assert answer.status_code == 401
    assert "Sign in and try again." in text(answer)
    assert load_of(console).record.percent_full is None


def test_record_unknown_load_404(staff: Console) -> None:
    assert save_record(staff, {"percent_full": "50"}, load=LoadId(9), version="1").status_code == 404
    assert staff.post("/console/loads/x/record", {"version": "1"}).status_code == 404


def test_record_full_form_accepted(staff: Console) -> None:
    start(staff)
    fields = dict.fromkeys(RECORD_FIELDS, "") | {
        "percent_full": "90",
        "cone_top": "100",
        "cone_top_none": "1",
        "cone_center_none": "1",
        "cone_bottom_none": "1",
    }
    assert len(fields) + 2 == 19  # with version and csrf

    answer = save_record(staff, fields)

    assert answer.status_code == 303
    record = load_of(staff).record
    assert record.percent_full == 90
    assert (record.cone_top, record.cone_center, record.cone_bottom) == (NO_CONE, NO_CONE, NO_CONE)


def test_record_no_cone_checkbox(staff: Console) -> None:
    start(staff)
    assert save_record(staff, {"cone_top": "", "cone_top_none": "1", "cone_center": "75"}).status_code == 303
    record = load_of(staff).record
    assert (record.cone_top, record.cone_center, record.cone_bottom) == (NO_CONE, 75, None)
    page = staff.get("/console/loads/L-1").text
    assert 'id="rec-cone_top-none" name="cone_top_none" value="1" checked' in page
    assert 'name="cone_top" value=""' in page
    assert 'id="rec-cone_center-none" name="cone_center_none" value="1">' in page
    assert save_record(staff, {"cone_top_none": "yes"}).status_code == 303  # not "1": not ticked
    assert load_of(staff).record.cone_top is None


def test_record_limits_match_domain(staff: Console) -> None:
    start(staff)
    page = staff.get("/console/loads/L-1").text
    for name, (low, high) in WHOLE_RANGES.items():
        tag = re.search(rf'<input type="number" id="rec-{name}"[^>]*>', page)
        assert tag is not None, name
        assert f'min="{low}" max="{high}"' in tag.group(0), name
        assert "maxlength" not in tag.group(0), name  # does nothing on a number field
        assert 'inputmode="numeric"' in tag.group(0), name
    for name in WITNESS_CONES:  # text: a stray number never blocks a ticked "No cone"
        tag = re.search(rf'<input type="text" id="rec-{name}"[^>]*>', page)
        assert tag is not None, name
        assert f'maxlength="{CONE_READING_TEXT_MAX}"' in tag.group(0), name
        assert 'inputmode="numeric"' in tag.group(0), name
        assert " max=" not in tag.group(0), name
    firing_time = re.search(r'<input type="text" id="rec-firing_time"[^>]*>', page)
    cost = re.search(r'<input type="text" id="rec-cost"[^>]*>', page)
    assert firing_time is not None
    assert cost is not None
    assert f'maxlength="{FIRING_TIME_TEXT_MAX}"' in firing_time.group(0)
    assert len(f"{FIRING_MINUTES_MAX // 60}:00") == FIRING_TIME_TEXT_MAX
    assert f'maxlength="{COST_TEXT_MAX}"' in cost.group(0)
    assert 'inputmode="decimal"' in cost.group(0)
    assert len(f"${COST_CENTS_MAX // 100}.00") == COST_TEXT_MAX


def test_record_suggests_firing_numbers(staff: Console) -> None:
    start(staff)
    fire_empty = staff.post(
        "/console/loads/L-1/edit", edit_fields(staff, "athena", "bisque", "2026-11-13") | {"test": "1"}
    )
    assert fire_empty.status_code == 303
    assert save_record(staff, {"firing_number": "41", "all_time_number": "300"}).status_code == 303
    fire(staff)
    start(staff)  # L-2 on the same kiln

    page = text(staff.get("/console/loads/L-2"))

    assert 'name="firing_number" value="42"' in page
    assert 'name="all_time_number" value="301"' in page
    assert "Suggested from Athena's firing count." in page
    assert load_of(staff, LoadId(2)).record.firing_number is None  # only a suggestion


# --- the steps and correcting their times (#42) ----------------------------------------------


def correct(console: Console, step: str, at: str, *, version: str = "") -> httpx2.Response:
    v = version or str(load_of(console).version)
    return console.post(f"/console/loads/L-1/steps/{step}/time", {"version": v, "at": at})


def empty_test_fired(console: Console) -> None:
    console.post(
        "/console/loads", {"kiln": "athena", "firing_type": "bisque", "date": "2026-11-13", "test": "1"}
    )
    fire(console)


def test_steps_show_who_and_when(staff: Console) -> None:
    start(staff)
    page = text(staff.get("/console/loads/L-1"))
    assert f"by {STAFF}</span>" in page
    assert austin_time(NOW) in page
    assert page.count("Correct time") == 1  # only the step reached
    assert 'aria-hidden="true"' in page.split("step-who")[1]

    staff.world.clock.advance(timedelta(minutes=5))
    empty = staff.post(
        "/console/loads/L-1/edit", edit_fields(staff, "athena", "bisque", "2026-11-13") | {"test": "1"}
    )
    assert empty.status_code == 303
    fire(staff)
    page = text(staff.get("/console/loads/L-1"))
    assert page.count(f"by {STAFF}</span>") == 3
    assert page.count("Correct time") == 3
    assert "When it started firing, Austin time" in page
    assert "Changes the load's time only. Its drop-offs keep theirs." in page
    assert re.search(r'<li aria-current="step">\s*<span class="step-label">3 Fired</span>', page)


def test_old_load_firing_not_recorded(staff: Console) -> None:
    staff.drop_off(1)
    start(staff)
    add(staff, "AC-1")
    fire(staff)
    old = replace(load_of(staff), fired_by=None, firing_started_by=None, firing_started_at=None)
    staff.world.records.commit([Update(old)])  # a load made before #42

    page = text(staff.get("/console/loads/L-1"))

    assert page.count("by not recorded") == 2
    assert page.count("Correct time") == 2  # started and fired; firing has no time to correct
    assert 'action="/console/loads/L-1/steps/firing/time"' not in page


def test_step_time_corrected(staff: Console) -> None:
    empty_test_fired(staff)
    staff.world.clock.advance(timedelta(hours=3))
    fired_at = load_of(staff).fired_at
    assert fired_at is not None
    local = (fired_at + timedelta(hours=1)).astimezone(STUDIO_TZ).strftime("%Y-%m-%dT%H:%M")

    answer = correct(staff, "fired", local)

    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/loads/L-1?done=time"
    assert load_of(staff).fired_at == fired_at + timedelta(hours=1)
    assert load_of(staff).fired_by == STAFF  # who never changes
    page = text(staff.get(answer.headers["location"]))
    assert "Time corrected." in page
    assert "Corrected when it was fired:" in page  # the history keeps the old time
    assert f'value="{local}"' in page


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "yesterday",
        "2026-11-13 12:30",
        "2026-13-40T25:00",
        "9999-12-31T23:59",
        "x" * 40,
    ],
)
def test_step_time_malformed(staff: Console, typed: str) -> None:
    start(staff)
    before = load_of(staff)
    answer = correct(staff, "started", typed)
    assert answer.status_code == 422
    page = text(answer)
    assert "Enter a date and time." in page
    assert 'aria-describedby="step-started-error"' in page
    assert '<details class="step-correct" open>' in page
    assert load_of(staff) == before


@pytest.mark.parametrize("typed", ["0001-01-01T00:00", f"{STEP_TIME_YEAR_MIN - 1}-12-31T23:59"])
def test_step_time_before_the_earliest_year_is_refused_by_the_domain(staff: Console, typed: str) -> None:
    start(staff)
    before = load_of(staff)
    answer = correct(staff, "started", typed)
    assert answer.status_code == 422
    assert f"Enter a time from {STEP_TIME_YEAR_MIN} on." in text(answer)
    assert f'value="{typed}"' in answer.text  # kept
    assert load_of(staff) == before


def test_a_malformed_time_for_a_step_with_no_form_says_why_above(staff: Console) -> None:
    start(staff)  # loading: "fired" has no "Correct time" field to show a refusal by
    before = load_of(staff)
    answer = correct(staff, "fired", "yesterday")
    assert answer.status_code == 422
    page = text(answer)
    assert "hasn't reached fired" in page
    assert 'class="notice notice-error" role="alert"' in page
    assert "Enter a date and time." not in page
    assert load_of(staff) == before


def _stored_at(console: Console, at: datetime) -> None:
    load = load_of(console)
    console.world.records.commit([Update(replace(load, started_at=at))])


def test_saving_an_unchanged_time_in_the_repeated_hour_keeps_the_stored_one(staff: Console) -> None:
    start(staff)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=STUDIO_TZ, fold=1)  # 1:30 am CST, the second time
    _stored_at(staff, second)
    before = load_of(staff)
    shown = re.search(r'id="step-started-at" name="at" value="([^"]*)"', staff.get("/console/loads/L-1").text)
    assert shown is not None
    assert shown.group(1) == "2026-11-01T01:30"

    answer = correct(staff, "started", shown.group(1))

    assert answer.status_code == 303
    assert load_of(staff) == before  # not moved an hour earlier, and no history line
    assert load_of(staff).started_at == second


def test_a_changed_time_in_the_repeated_hour_is_read_as_the_first(staff: Console) -> None:
    start(staff)
    _stored_at(staff, datetime(2026, 11, 1, 0, 30, tzinfo=STUDIO_TZ))
    answer = correct(staff, "started", "2026-11-01T01:15")
    assert answer.status_code == 303
    assert load_of(staff).started_at == datetime(2026, 11, 1, 6, 15, tzinfo=UTC)  # 1:15 am CDT


def test_a_time_the_clocks_skip_is_refused(staff: Console) -> None:
    start(staff)
    _stored_at(staff, datetime(2026, 3, 8, 1, 0, tzinfo=STUDIO_TZ))
    before = load_of(staff)
    answer = correct(staff, "started", "2026-03-08T02:30")
    assert answer.status_code == 422
    assert "The clocks went forward an hour then, so that time didn't happen." in text(answer)
    assert 'value="2026-03-08T02:30"' in answer.text  # kept
    assert load_of(staff) == before
    assert correct(staff, "started", "2026-03-08T03:30").status_code == 303


def test_step_time_in_future(staff: Console) -> None:
    start(staff)
    before = load_of(staff)
    later = (NOW + timedelta(days=1)).astimezone(STUDIO_TZ).strftime("%Y-%m-%dT%H:%M")
    answer = correct(staff, "started", later)
    assert answer.status_code == 422
    assert "That time is in the future." in text(answer)
    assert f'value="{later}"' in answer.text  # kept
    assert load_of(staff) == before


def test_step_time_out_of_order(staff: Console) -> None:
    empty_test_fired(staff)
    before = load_of(staff)
    earlier = (NOW - timedelta(days=1)).astimezone(STUDIO_TZ).strftime("%Y-%m-%dT%H:%M")
    answer = correct(staff, "fired", earlier)
    assert answer.status_code == 422
    assert "can't have started firing before it was started" in text(answer)
    assert load_of(staff) == before


def test_step_not_reached_is_refused(staff: Console) -> None:
    start(staff)
    answer = correct(staff, "fired", "2026-11-13T10:00")
    assert answer.status_code == 422
    assert "hasn't reached fired" in text(answer)


def test_step_time_conflict(staff: Console) -> None:
    start(staff)
    answer = correct(staff, "started", "2026-11-13T10:00", version="99")
    assert answer.status_code == 409
    assert "Someone else changed this load. Check it and save again." in text(answer)


def test_step_unknown_404(staff: Console) -> None:
    start(staff)
    assert correct(staff, "loading", "2026-11-13T10:00").status_code == 404
    assert correct(staff, "STARTED", "2026-11-13T10:00").status_code == 404


def test_step_needs_csrf(staff: Console) -> None:
    start(staff)
    before = load_of(staff)
    fields = {"version": str(before.version), "at": "2026-11-13T10:00"}
    assert staff.post("/console/loads/L-1/steps/started/time", fields, csrf=False).status_code == 403
    assert load_of(staff) == before


def test_step_not_in_group_not_allowed(console: Console) -> None:
    console.world.start_load(ATHENA, ItemId("bisque"), None, STAFF_MEMBER)
    before = load_of(console)
    console.sign_in(groups=("front-desk",), username=OUTSIDER)
    answer = console.post("/console/loads/L-1/steps/started/time", {"version": "1", "at": "2026-11-13T10:00"})
    assert answer.status_code == 403
    assert load_of(console) == before


# --- the history (#42) -----------------------------------------------------------------------


def test_history_listed_and_escaped(staff: Console) -> None:
    world = staff.world
    world.add_item(
        CatalogList.KILNS,
        "<b>Hot</b>",
        needs_glaze_type=False,
        needs_message=False,
        version=world.studio().version,
        staff=STAFF_MEMBER,
    )
    hot = next(item.id for item in world.studio().kilns if item.name == "<b>Hot</b>")
    start(staff)
    world.clock.advance(timedelta(minutes=10))
    assert (
        staff.post("/console/loads/L-1/edit", edit_fields(staff, hot, "bisque", "2026-11-13")).status_code
        == 303
    )
    world.clock.advance(timedelta(minutes=10))
    assert save_record(staff, {"percent_full": "60"}).status_code == 303

    page = staff.get("/console/loads/L-1").text

    history = page.split('id="history"')[1]
    assert "History · 3" in history
    assert "<b>Hot</b>" not in page
    assert "&lt;b&gt;Hot&lt;/b&gt;" in history
    assert "No history recorded." not in page
    lines = re.findall(r"<li>(.*?)</li>", history.split("</ul>")[0], flags=re.DOTALL)
    assert [line.split(" · ")[-1] for line in html.unescape("\n".join(lines)).split("\n")] == [
        "Started the load",
        "Kiln: Athena → <b>Hot</b>",
        "Firing record: % full: 60%",
    ]
    assert f" · {STAFF} · " in lines[0]


def test_a_load_from_before_the_history_says_none_was_recorded(staff: Console) -> None:
    staff.world.records.commit([Put(a_load(status=LoadStatus.FIRED, before_42=True))])  # no events

    page = text(staff.get("/console/loads/L-1"))

    assert '<span id="history-title">History</span>' in page
    assert "No history recorded." in page
