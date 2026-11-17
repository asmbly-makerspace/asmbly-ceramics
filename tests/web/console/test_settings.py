"""The settings page (#6): the sending address and its test email, the pickup window and
hours, the studio's lists, and the change history."""

import html
import logging
import re
from datetime import timedelta

import httpx2
import pytest

from asmbly_ceramics.domain.email import EmailKind
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.studio import CatalogList, ItemStatus
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases import settings as use_case
from asmbly_ceramics.web.console import settings as page
from asmbly_ceramics.web.console.session import SESSION_COOKIE
from tests.domain.builders import STAFF, a_sending_address, an_address
from tests.use_cases.flows import ATHENA, STAFF_EMAIL, STAFF_MEMBER, fired, send_all
from tests.web.console.conftest import Console, events

SETTINGS = "/console/settings"


@pytest.fixture
def staff(console: Console) -> Console:
    console.sign_in()
    return console


def text(answer: httpx2.Response) -> str:
    return html.unescape(answer.text)


def version(console: Console) -> str:
    return str(console.world.studio().version)


def save(console: Console, **overrides: str) -> httpx2.Response:
    studio = console.world.studio()
    fields = {
        "sending_address": studio.sending_address,
        "pickup_window_days": str(studio.pickup_window_days),
        "pickup_hours_text": studio.pickup_hours_text,
        "received_emails_per_day": str(studio.received_emails_per_day),
        "version": version(console),
    } | overrides
    return console.post(f"{SETTINGS}/email", fields)


def list_post(console: Console, slug: str, action: str, **fields: str) -> httpx2.Response:
    return console.post(f"{SETTINGS}/{slug}/{action}", {"version": version(console)} | fields)


# --- the sending address -------------------------------------------------------------------


def test_the_settings_page_shows_the_emails_card_and_the_lists(staff: Console) -> None:
    answer = staff.get(SETTINGS)
    assert answer.status_code == 200
    shown = text(answer)
    assert 'aria-current="page">Settings' in answer.text
    assert "Every drop-off, fired and rejection email comes from this address. Replies go to it too." in shown
    assert "Sends to the address on your staff account. Save after it arrives." in shown
    for heading in ("Kilns", "Firing types", "Glaze types", "Rejection reasons", "Change history"):
        assert heading in shown
    assert "Starting settings" in shown


def test_an_address_outside_asmbly_org_is_refused_next_to_the_field(staff: Console) -> None:
    before = staff.world.studio()
    outside = an_address("kilnops")

    answer = save(staff, sending_address=outside)

    assert answer.status_code == 400
    error = re.search(r'id="sending_address-error">([^<]*)<', answer.text)
    assert error is not None
    assert error.group(1) == "Use an address at asmbly.org."
    assert "@" not in error.group(1)
    assert staff.world.studio() == before


@pytest.mark.parametrize(
    "address",
    [
        an_address("kilnops", "asmbly.org.example.net"),
        an_address("kilnops", "xasmbly.org"),
        an_address("kilnops", "asmbly.org."),
    ],
)
def test_a_lookalike_domain_is_refused(staff: Console, address: str) -> None:
    before = staff.world.studio()
    answer = save(staff, sending_address=address)
    assert answer.status_code == 400
    assert "Use an address at asmbly.org." in answer.text
    assert staff.world.studio() == before


def test_an_uppercase_domain_at_asmbly_org_is_fine(staff: Console) -> None:
    assert save(staff, sending_address=an_address("kilnops", "ASMBLY.ORG")).status_code == 303


def test_the_test_email_goes_from_the_unsaved_address_to_the_staff_member_and_saves_nothing(
    staff: Console,
) -> None:
    before = staff.world.studio()
    new = a_sending_address("kilnops")
    fields = {"sending_address": new, "pickup_window_days": "14", "pickup_hours_text": "x", "version": "1"}

    answer = staff.post(f"{SETTINGS}/test-email", fields)

    assert answer.status_code == 200
    assert "A test email is on its way to you from the new address." in answer.text
    assert f'value="{new}"' in answer.text  # kept in the field, to save after it arrives
    [sent] = staff.world.mailer.sent
    assert sent.to == STAFF_EMAIL
    assert sent.from_address == new
    assert staff.world.studio() == before


def test_the_test_email_without_a_verified_staff_address_says_so(staff: Console) -> None:
    token = "made-up-token-no-email"
    staff.tokens.members[token] = StaffMember("no.email", None)
    staff.client.cookies.set(SESSION_COOKIE, staff.seal(token))
    fields = {"sending_address": a_sending_address("kilnops"), "version": "1"}

    answer = staff.post(f"{SETTINGS}/test-email", fields)

    assert answer.status_code == 400
    assert "Your sign-in has no email address, so a test email can't be sent." in text(answer)
    assert staff.world.mailer.sent == []


def test_a_refused_test_email_shows_the_code_and_saves_nothing(staff: Console) -> None:
    before = staff.world.studio()
    staff.world.mailer.fail_with = "MessageRejected"

    answer = staff.post(f"{SETTINGS}/test-email", {"sending_address": a_sending_address("kilnops")})

    assert answer.status_code == 400
    assert "The test email didn't send (MessageRejected). Nothing was saved." in text(answer)
    assert staff.world.studio() == before


def test_a_test_email_from_outside_asmbly_org_is_refused(staff: Console) -> None:
    answer = staff.post(f"{SETTINGS}/test-email", {"sending_address": an_address("kilnops")})
    assert answer.status_code == 400
    assert "Use an address at asmbly.org." in answer.text
    assert staff.world.mailer.sent == []


# --- saving and the history ----------------------------------------------------------------


def test_saving_records_who_and_when_in_the_history(staff: Console, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    answer = save(staff, pickup_window_days="10")

    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/settings?done=email"
    assert staff.world.studio().pickup_window_days == 10
    shown = text(staff.get(answer.headers["location"]))
    assert "Email settings saved." in shown
    assert f"Pickup window: 14 → 10 days · {STAFF} · Fri Nov 13, 12:30 PM" in shown
    assert ("settings_changed", STAFF) in events(caplog)


def test_a_window_outside_1_to_90_is_refused(staff: Console) -> None:
    for days in ("0", "91", "ten"):
        answer = save(staff, pickup_window_days=days)
        assert answer.status_code == 400
        assert "Enter a number of days from 1 to 90." in answer.text
    assert staff.world.studio().pickup_window_days == 14


def test_the_emails_card_shows_the_received_emails_cap(staff: Console) -> None:
    answer = staff.get(SETTINGS)
    assert answer.status_code == 200
    assert '<label for="received_emails_per_day">Received emails a day, at most</label>' in answer.text
    assert 'name="received_emails_per_day" value="300" min="1" max="2000" inputmode="numeric"' in answer.text
    assert 'aria-describedby="cap-hint"' in answer.text
    assert "Past it, the form turns drop-offs away and asks people to see staff." in text(answer)
    assert (
        "Turned-away attempts count too, so they keep the form closed; raising this number reopens it."
        in (text(answer))
    )


def test_the_cap_hint_takes_its_window_from_the_domain(
    staff: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(page, "RECEIVED_CAP_WINDOW", timedelta(hours=12))
    assert "emails the form sends in any 12 hours." in text(staff.get(SETTINGS))


def test_saving_the_cap_records_it_in_the_history(staff: Console, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    answer = save(staff, received_emails_per_day="120")

    assert answer.status_code == 303
    assert staff.world.studio().received_emails_per_day == 120
    shown = text(staff.get(answer.headers["location"]))
    assert f"Received emails a day, at most: 300 → 120 · {STAFF}" in shown
    assert 'name="received_emails_per_day" value="120"' in staff.get(SETTINGS).text
    assert ("settings_changed", STAFF) in events(caplog)


@pytest.mark.parametrize("cap", ["0", "2001", "lots", "<b>9</b>"])
def test_a_cap_outside_1_to_2000_is_refused_next_to_the_field(staff: Console, cap: str) -> None:
    before = staff.world.studio()

    answer = save(staff, received_emails_per_day=cap, pickup_window_days="10")

    assert answer.status_code == 400
    assert '<p class="field-error" id="cap-error">Enter a number from 1 to 2,000.</p>' in answer.text
    assert 'aria-describedby="cap-hint cap-error"' in answer.text
    assert f'name="received_emails_per_day" value="{html.escape(cap)}"' in answer.text  # kept, escaped
    assert "<b>9</b>" not in answer.text
    assert staff.world.studio() == before


def test_a_signed_in_person_outside_the_group_can_t_change_the_cap(console: Console) -> None:
    console.sign_in(groups=("front-desk",), username="front.desk")
    before = console.world.studio()
    answer = save(console, received_emails_per_day="1")
    assert answer.status_code == 403
    assert console.world.studio() == before


def test_changing_the_cap_needs_csrf(staff: Console) -> None:
    before = staff.world.studio()
    studio = staff.world.studio()
    fields = {
        "sending_address": studio.sending_address,
        "pickup_window_days": str(studio.pickup_window_days),
        "pickup_hours_text": studio.pickup_hours_text,
        "received_emails_per_day": "1",
        "version": version(staff),
    }
    assert staff.post(f"{SETTINGS}/email", fields, csrf=False).status_code == 403
    assert staff.post(f"{SETTINGS}/email", fields | {"csrf": "forged"}, csrf=False).status_code == 403
    assert staff.world.studio() == before


def test_the_history_shows_no_address(staff: Console) -> None:
    old = staff.world.studio().sending_address
    new = a_sending_address("kilnops")
    save(staff, sending_address=new)
    staff.world.mailer.sent.clear()

    shown = text(staff.get(SETTINGS))
    history = shown.split("Change history")[1]

    assert "Changed the sending address" in history
    assert new not in history
    assert old not in shown
    assert shown.count(new) == 1  # in the field only
    assert new not in text(staff.get(f"{SETTINGS}/history"))


def test_every_email_after_a_change_uses_the_new_settings(staff: Console) -> None:
    world = staff.world
    id = staff.drop_off(1)
    send_all(world)
    fired(world, id)  # the ready email is queued with today's window
    new = a_sending_address("kilnops")
    save(staff, sending_address=new, pickup_hours_text="Tuesdays only, 6 to 9 PM")

    send_all(world)

    ready = world.mailer.sent[-1]
    assert ready.from_address == new
    assert "Tuesdays only, 6 to 9 PM" in ready.text
    assert world.records.email(id, EmailKind.READY) is not None


def test_markup_in_the_pickup_hours_is_escaped_on_the_page_and_in_the_email(staff: Console) -> None:
    world = staff.world
    hours = 'Open <script>alert("x")</script> & <b>late</b>'
    assert save(staff, pickup_hours_text=hours).status_code == 303

    page_html = staff.get(SETTINGS).text
    assert "<script>alert" not in page_html
    assert "&lt;script&gt;" in page_html

    id = staff.drop_off(1)
    send_all(world)
    fired(world, id)
    send_all(world)
    ready = world.mailer.sent[-1]
    assert "<script>" not in ready.html
    assert "&lt;script&gt;" in ready.html


def test_the_full_history_pages_with_an_opaque_cursor(
    staff: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(page, "HISTORY_PAGE", 2)
    save(
        staff, sending_address=a_sending_address("kilnops"), pickup_window_days="10", pickup_hours_text="New"
    )

    first = text(staff.get(f"{SETTINGS}/history"))
    cursor = re.search(r'href="/console/settings/history\?before=([^"]+)">Older changes', first)
    assert cursor is not None
    rest = text(staff.get(f"{SETTINGS}/history?before={cursor.group(1)}"))
    last = re.search(r'href="/console/settings/history\?before=([^"]+)">Older changes', rest)
    pages = first + rest
    if last is not None:
        pages += text(staff.get(f"{SETTINGS}/history?before={last.group(1)}"))
    for what in (
        "Changed the sending address",
        "Pickup window: 14 → 10 days",
        "Changed the pickup hours text",
    ):
        assert pages.count(what) == 1
    made_up = text(staff.get(f"{SETTINGS}/history?before=not-a-cursor"))
    assert (
        made_up.split("Settings history")[1].split("Older")[0]
        == first.split("Settings history")[1].split("Older")[0]
    )


# --- the studio's lists --------------------------------------------------------------------


def test_a_used_item_can_be_retired_not_deleted(staff: Console) -> None:
    id = staff.drop_off(1)
    fired(staff.world, id)  # Athena is used by a load
    assert "Used" in text(staff.get(SETTINGS)).split("Kilns")[1].split("Firing types")[0]

    assert list_post(staff, "kilns", "retire", item="athena").status_code == 303
    page_text = text(staff.get(SETTINGS)).split("Kilns")[1].split("Firing types")[0]
    assert "Retired" in page_text
    assert "Delete" not in page_text.split("Athena")[1].split("Helios")[0]

    answer = list_post(staff, "kilns", "delete", item="athena")
    assert answer.status_code == 400
    assert (
        "Athena is in use by a drop-off, a load, a default program or a note, so it stays retired."
        in answer.text
    )
    assert staff.world.studio().item(CatalogList.KILNS, ATHENA).status is ItemStatus.RETIRED


def test_an_active_item_must_be_retired_before_it_is_deleted(staff: Console) -> None:
    answer = list_post(staff, "kilns", "delete", item="vulcan")
    assert answer.status_code == 400
    assert "Retire Vulcan before deleting it." in answer.text
    assert staff.world.studio().item(CatalogList.KILNS, ItemId("vulcan")).name == "Vulcan"


def test_a_retired_unused_item_can_be_deleted(staff: Console) -> None:
    list_post(staff, "kilns", "retire", item="vulcan")
    answer = list_post(staff, "kilns", "delete", item="vulcan")
    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/settings?done=deleted#kilns"
    assert all(item.id != "vulcan" for item in staff.world.studio().kilns)
    assert "Deleted kiln Vulcan" in text(staff.get(SETTINGS))


def test_a_retired_item_can_be_brought_back(staff: Console) -> None:
    list_post(staff, "kilns", "retire", item="helios")
    assert "Bring back" in staff.get(SETTINGS).text
    assert list_post(staff, "kilns", "restore", item="helios").status_code == 303
    assert staff.world.studio().item(CatalogList.KILNS, ItemId("helios")).status is ItemStatus.ACTIVE


def test_a_retired_kiln_is_not_offered_for_a_new_load_but_stays_on_past_loads(staff: Console) -> None:
    id = staff.drop_off(1)
    fired(staff.world, id)  # L-1 in Athena
    list_post(staff, "kilns", "retire", item="athena")

    start_form = staff.get("/console/loads").text.split("Start a load")[1].split("Open loads")[0]
    assert 'value="athena"' not in start_form
    assert "Athena · Bisque" in text(staff.get("/console/loads/L-1"))


def test_adding_items_with_their_flags(staff: Console) -> None:
    assert list_post(staff, "kilns", "add", name="Hestia").status_code == 303
    list_post(staff, "firing-types", "add", name="Raku", needs_glaze_type="1")
    list_post(staff, "reasons", "add", name="Cracked", needs_message="1")
    list_post(
        staff, "glaze-types", "add", name="Celadon", needs_glaze_type="1"
    )  # ignored outside firing types
    studio = staff.world.studio()
    assert studio.kilns[-1].name == "Hestia"
    assert studio.firing_types[-1].needs_glaze_type
    assert studio.reasons[-1].needs_message
    assert not studio.glaze_types[-1].needs_glaze_type


def test_duplicate_names_are_refused_ignoring_case(staff: Console) -> None:
    answer = list_post(staff, "kilns", "add", name="athena")
    assert answer.status_code == 400
    assert "There is already a kiln called athena." in answer.text
    assert 'value="athena"' in answer.text  # the typed name is kept
    assert len(staff.world.studio().kilns) == 3


def test_the_last_active_kiln_cannot_be_retired(staff: Console) -> None:
    list_post(staff, "kilns", "retire", item="helios")
    list_post(staff, "kilns", "retire", item="vulcan")
    answer = list_post(staff, "kilns", "retire", item="athena")
    assert answer.status_code == 400
    assert "Athena is the last active kiln: add or restore another first." in answer.text


def test_an_unknown_list_is_404(staff: Console) -> None:
    assert list_post(staff, "colours", "add", name="Red").status_code == 404
    assert list_post(staff, "kilns", "retire", item="<b>").status_code == 400
    assert "doesn" in list_post(staff, "kilns", "retire", item="nope").text


def test_a_stale_settings_page_is_a_conflict_and_saves_nothing(staff: Console) -> None:
    answer = save(staff, pickup_window_days="10", version="0")
    assert answer.status_code == 409
    assert "The settings changed while you were working. Here they are now; try again." in answer.text
    assert staff.world.studio().pickup_window_days == 14
    assert list_post(staff, "kilns", "add", name="Hestia", version="0").status_code == 409
    assert list_post(staff, "kilns", "retire", item="helios", version="0").status_code == 409


def test_settings_changes_log_no_address_or_hours(staff: Console, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    new = a_sending_address("kilnops")
    save(staff, sending_address=new, pickup_hours_text="Secret-ish hours text")
    staff.post(f"{SETTINGS}/test-email", {"sending_address": new})
    for record in caplog.records:
        line = repr(vars(record))
        assert new not in line
        assert STAFF_EMAIL not in line
        assert "Secret-ish hours text" not in line


def test_a_save_whose_outcome_is_unknown_says_to_check(staff: Console) -> None:
    from asmbly_ceramics.ports.records import CommitOutcomeUnknown

    staff.world.studio()  # seeded first: the failure is the save's
    staff.world.records.fail_next_commit_with = CommitOutcomeUnknown("RequestTimeout")
    answer = save(staff, pickup_window_days="10")
    assert answer.status_code == 503
    assert "may or may not have been saved" in answer.text


def test_a_conflict_shows_the_stored_values_not_the_typed_ones(staff: Console) -> None:
    answer = save(staff, pickup_window_days="33", version="0")
    assert answer.status_code == 409
    assert 'value="14"' in answer.text
    assert 'value="33"' not in answer.text


def test_enter_in_the_emails_card_saves_and_the_window_limits_are_the_domain_s(staff: Console) -> None:
    from asmbly_ceramics.domain.limits import PICKUP_WINDOW_MAX, PICKUP_WINDOW_MIN

    card = staff.get(SETTINGS).text.split('action="/console/settings/email"')[1].split("</form>")[0]
    first_button = card.split("<button", 1)[1].split(">", 1)[0]
    assert "formaction" not in first_button  # the default button saves
    assert f'min="{PICKUP_WINDOW_MIN}" max="{PICKUP_WINDOW_MAX}"' in card


def test_the_history_page_skips_the_used_scan_and_pages_by_the_use_case_s_size(staff: Console) -> None:
    """It shows no list, so it asks no `is_item_used`; and "50 a page" is one constant."""
    assert page.HISTORY_PAGE is use_case.HISTORY_PAGE == 50
    staff.world.records.reads.clear()
    assert staff.get(f"{SETTINGS}/history").status_code == 200
    assert "is_item_used" not in staff.world.records.reads
    assert "history" in staff.world.records.reads


# --- cones and clay bodies (#42, #17) ---------------------------------------------------------


def test_cones_and_clay_bodies_listed(staff: Console) -> None:
    shown = text(staff.get(SETTINGS))
    cones = shown.split("Cones")[1].split("Clay bodies")[0]
    for name in ("^06", "^5", "^6"):
        assert name in cones
    clays = shown.split("Clay bodies")[1].split("Change history")[0]
    for name in ("Buffalo Wallow", "Cinco Blanco", "Cone 5 Porcelain"):
        assert name in clays
    # ^6 is named by Glaze's default program: used, so it can only be retired.
    assert "Used" in cones.split("^6")[-1]


def test_add_cone(staff: Console, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    answer = list_post(staff, "cones", "add", name="^04")
    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/settings?done=added#cones"
    assert staff.world.studio().item(CatalogList.CONES, ItemId("item-04")).name == "^04"
    assert "Added cone ^04" in text(staff.get(SETTINGS))
    [event] = [vars(r) for r in caplog.records if r.getMessage() == "settings_changed"]
    assert (event["list"], event["item"], event["user"]) == ("cones", "item-04", STAFF)


def test_add_retire_restore_delete_clay_body(staff: Console) -> None:
    assert list_post(staff, "clay-bodies", "add", name="Speckled Buff").status_code == 303
    clay = ItemId("speckled-buff")
    assert list_post(staff, "clay-bodies", "retire", item=clay).status_code == 303
    assert staff.world.studio().item(CatalogList.CLAY_BODIES, clay).status is ItemStatus.RETIRED
    assert list_post(staff, "clay-bodies", "restore", item=clay).status_code == 303
    list_post(staff, "clay-bodies", "retire", item=clay)
    answer = list_post(staff, "clay-bodies", "delete", item=clay)
    assert answer.headers["location"] == "/console/settings?done=deleted#clay-bodies"
    assert "Deleted clay body Speckled Buff" in text(staff.get(SETTINGS))
    assert list_post(staff, "clay-bodies", "add", name="").status_code == 400


def test_a_cone_named_by_a_default_program_cannot_be_deleted(staff: Console) -> None:
    assert list_post(staff, "cones", "retire", item="item-6").status_code == 303
    answer = list_post(staff, "cones", "delete", item="item-6")
    assert answer.status_code == 400
    assert "^6 is in use by" in text(answer)
    assert staff.world.studio().item(CatalogList.CONES, ItemId("item-6")).retired


def test_a_cone_used_by_a_load_cannot_be_deleted(staff: Console) -> None:
    fired(staff.world, staff.drop_off(1))  # a bisque load: its program names ^06
    staff.world.set_default_program(ItemId("bisque"), {}, staff.world.studio().version, STAFF_MEMBER)
    list_post(staff, "cones", "retire", item="item-06")
    answer = list_post(staff, "cones", "delete", item="item-06")
    assert answer.status_code == 400
    assert "^06 is in use by" in text(answer)


def test_the_cone_and_clay_lists_need_the_ceramics_group(console: Console) -> None:
    console.sign_in(groups=())
    answer = list_post(console, "cones", "add", name="^04")
    assert answer.status_code == 403
    assert all(item.name != "^04" for item in console.world.studio().cones)


# --- default programs, kiln counts and new elements (#42) ----------------------------------

PROGRAM = f"{SETTINGS}/firing-types/glaze/program"
COUNTS = f"{SETTINGS}/kilns/helios/counts"
ELEMENTS = f"{SETTINGS}/kilns/helios/new-elements"
HELIOS = ItemId("helios")


def program_post(console: Console, path: str = PROGRAM, **fields: str) -> httpx2.Response:
    blank = dict.fromkeys(("cone", "speed", "preheat_hours", "hold_minutes"), "")
    return console.post(path, {"version": version(console)} | blank | fields)


def counts_post(console: Console, path: str = COUNTS, **fields: str) -> httpx2.Response:
    return console.post(path, {"version": version(console)} | fields)


def test_settings_page_shows_programs_and_counts(staff: Console) -> None:
    shown = text(staff.get(SETTINGS))
    assert "Default program: ^6, medium, preheat 0 h, hold 7 min" in shown
    assert 'action="/console/settings/firing-types/glaze/program"' in shown
    assert "Firing counts: not set" in shown
    assert "Firing # for Helios restarts at 1 from its next firing. The all-time count carries on." in shown
    assert 'action="/console/settings/kilns/helios/new-elements"' in shown


def test_set_default_program(staff: Console, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    answer = program_post(staff, cone="item-5", speed="slow", preheat_hours="2", hold_minutes="15")
    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/settings?done=program#firing-types"
    program = staff.world.studio().item(CatalogList.FIRING_TYPES, ItemId("glaze")).default_program
    assert program is not None
    assert (program.cone, program.speed, program.preheat_hours, program.hold_minutes) == (
        "item-5",
        "slow",
        2,
        15,
    )
    shown = text(staff.get(answer.headers["location"]))
    assert "Default program saved." in shown
    assert "Default program for Glaze: ^5, slow, preheat 2 h, hold 15 min" in shown  # the history
    assert all(STAFF_EMAIL not in r.getMessage() for r in caplog.records)


def test_clear_default_program(staff: Console) -> None:
    answer = program_post(staff)
    assert answer.status_code == 303
    assert staff.world.studio().item(CatalogList.FIRING_TYPES, ItemId("glaze")).default_program is None
    shown = text(staff.get(SETTINGS))
    assert "Default program: none" in shown
    assert "Cleared the default program for Glaze" in shown


def test_default_program_invalid_fields(staff: Console) -> None:
    before = staff.world.studio()
    answer = program_post(staff, cone="no-such-cone", speed="warp", preheat_hours="99", hold_minutes="7")
    assert answer.status_code == 400
    assert staff.world.studio() == before
    shown = text(answer)
    assert "Check the default program: the fields marked need fixing." in shown
    for field in ("cone", "speed", "preheat_hours"):
        assert f'id="prog-glaze-{field}-error"' in answer.text
    assert 'id="prog-glaze-hold_minutes-error"' not in answer.text
    assert 'name="hold_minutes" value="7"' in answer.text  # the typed value kept
    assert "warp" not in shown  # never echoed back


def test_set_kiln_counts(staff: Console) -> None:
    answer = counts_post(staff, since_elements="40", all_time="1200")
    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/settings?done=counts#kilns"
    counts = staff.world.studio().item(CatalogList.KILNS, HELIOS).counts
    assert counts is not None
    assert (counts.since_elements, counts.all_time) == (40, 1200)
    shown = text(staff.get(answer.headers["location"]))
    assert "Firing counts saved." in shown
    assert "Firing counts: 40 since new elements, 1,200 all time, as of Fri Nov 13, 2026" in shown
    assert "Helios counts: 40 since elements, 1,200 all time" in shown  # the history


@pytest.mark.parametrize(
    ("since", "total", "field"),
    [("x", "10", "since_elements"), ("5", "-1", "all_time"), ("11", "10", "since_elements")],
)
def test_kiln_counts_invalid(staff: Console, since: str, total: str, field: str) -> None:
    answer = counts_post(staff, since_elements=since, all_time=total)
    assert answer.status_code == 400
    assert staff.world.studio().item(CatalogList.KILNS, HELIOS).counts is None
    assert f'id="counts-helios-{field}-error"' in answer.text


def test_new_elements_confirm_then_reset(staff: Console) -> None:
    counts_post(staff, since_elements="40", all_time="1200")
    confirm = text(staff.get(SETTINGS))
    assert "New elements…" in confirm
    assert "Yes, new elements" in confirm

    answer = counts_post(staff, ELEMENTS)

    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/settings?done=elements#kilns"
    counts = staff.world.studio().item(CatalogList.KILNS, HELIOS).counts
    assert counts is not None
    assert (counts.since_elements, counts.all_time) == (0, 1200)
    shown = text(staff.get(answer.headers["location"]))
    assert "New elements recorded. The next firing is number 1." in shown
    assert "New elements in Helios" in shown


@pytest.mark.parametrize("path", [PROGRAM, COUNTS, ELEMENTS])
def test_each_needs_csrf(staff: Console, path: str) -> None:
    before = staff.world.studio()
    fields = {"version": version(staff), "since_elements": "1", "all_time": "2"}
    assert staff.post(path, fields, csrf=False).status_code == 403
    assert staff.post(path, fields | {"csrf": "forged"}, csrf=False).status_code == 403
    assert staff.world.studio() == before


@pytest.mark.parametrize("path", [PROGRAM, COUNTS, ELEMENTS])
def test_each_conflict(staff: Console, path: str) -> None:
    before = staff.world.studio()
    answer = counts_post(staff, path, version="0", since_elements="1", all_time="2", cone="item-5")
    assert answer.status_code == 409
    assert "The settings changed while you were working. Here they are now; try again." in text(answer)
    assert staff.world.studio() == before


@pytest.mark.parametrize("path", [PROGRAM, COUNTS, ELEMENTS])
def test_each_outcome_unknown_says_to_check(staff: Console, path: str) -> None:
    from asmbly_ceramics.ports.records import CommitOutcomeUnknown

    staff.world.studio()
    staff.world.records.fail_next_commit_with = CommitOutcomeUnknown("RequestTimeout")
    answer = counts_post(staff, path, since_elements="1", all_time="2", cone="item-5")
    assert answer.status_code == 503
    assert "may or may not have been saved" in answer.text


@pytest.mark.parametrize(
    "path",
    [
        f"{SETTINGS}/firing-types/no-such-type/program",
        f"{SETTINGS}/firing-types/helios/program",  # a kiln isn't a firing type
        f"{SETTINGS}/kilns/no-such-kiln/counts",
        f"{SETTINGS}/kilns/glaze/new-elements",
        f"{SETTINGS}/kilns/NOT_AN_ID/counts",
    ],
)
def test_unknown_item_404(staff: Console, path: str) -> None:
    before = staff.world.studio()
    assert counts_post(staff, path, since_elements="1", all_time="2").status_code == 404
    assert staff.world.studio() == before


@pytest.mark.parametrize("path", [PROGRAM, COUNTS, ELEMENTS])
def test_new_settings_need_the_ceramics_group(console: Console, path: str) -> None:
    console.sign_in(groups=("front-desk",), username="front.desk")
    before = console.world.studio()
    answer = counts_post(console, path, since_elements="1", all_time="2")
    assert answer.status_code == 403
    assert console.world.studio() == before


def test_the_counts_form_starts_blank_so_saving_it_unchanged_cannot_redate_the_counts(staff: Console) -> None:
    """The stored counts are as of their own day: prefilled under "counts today" and saved
    unchanged, they would be dated now and lose the firings since. The fields start blank
    and the summary shows the counts with their day."""
    counts_post(staff, since_elements="40", all_time="1200")

    answer = staff.get(SETTINGS)

    assert 'id="counts-helios-since_elements" name="since_elements" value=""' in answer.text
    assert 'id="counts-helios-all_time" name="all_time" value=""' in answer.text
    assert "as of Fri Nov 13, 2026" in text(answer)
    before = staff.world.studio()
    blank = counts_post(staff, since_elements="", all_time="")  # "Save counts" untouched
    assert blank.status_code == 400
    assert staff.world.studio() == before


def test_a_refused_counts_save_has_the_top_banner(staff: Console) -> None:
    answer = counts_post(staff, since_elements="11", all_time="10")
    assert answer.status_code == 400
    assert "Check the firing counts: the form shows what needs fixing." in text(answer)
    assert 'role="alert"' in answer.text
    assert 'name="since_elements" value="11"' in answer.text  # the typed values kept, the form open


def test_a_conflict_keeps_the_typed_program_open(staff: Console) -> None:
    answer = program_post(
        staff, version="0", cone="item-5", speed="slow", preheat_hours="2", hold_minutes="15"
    )
    assert answer.status_code == 409
    assert "The settings changed while you were working." in text(answer)
    assert 'name="preheat_hours" value="2"' in answer.text
    assert 'name="hold_minutes" value="15"' in answer.text
    assert '<option value="slow" selected>' in answer.text
    assert '<option value="item-5" selected>' in answer.text
    assert f'name="version" value="{version(staff)}"' in answer.text  # resubmittable as is


def test_a_conflict_keeps_the_typed_counts_open(staff: Console) -> None:
    answer = counts_post(staff, version="0", since_elements="40", all_time="1200")
    assert answer.status_code == 409
    assert 'name="since_elements" value="40"' in answer.text
    assert 'name="all_time" value="1200"' in answer.text
    assert staff.world.studio().item(CatalogList.KILNS, HELIOS).counts is None


@pytest.mark.parametrize("field", ["preheat_hours", "hold_minutes"])
def test_markup_in_a_program_number_is_refused_and_escaped(staff: Console, field: str) -> None:
    sent = '"><script>alert(1)</script>'
    before = staff.world.studio()
    answer = program_post(staff, **{field: sent})
    assert answer.status_code == 400
    assert staff.world.studio() == before
    assert f'id="prog-glaze-{field}-error"' in answer.text
    assert "<script>alert(1)</script>" not in answer.text
    assert sent not in answer.text
    assert "&lt;script&gt;" in answer.text  # kept in the field, escaped


def cone_options(page: str, firing_type: str) -> str:
    """The cone select of one firing type's "Default program" form."""
    return page.split(f'id="prog-{firing_type}-cone"')[1].split("</select>")[0]


def test_the_program_form_offers_the_retired_cone_its_program_names(staff: Console) -> None:
    assert list_post(staff, "cones", "retire", item="item-6").status_code == 303
    page = staff.get(SETTINGS).text
    glaze = cone_options(page, "glaze")
    bisque = cone_options(page, "bisque")
    assert '<option value="item-6" selected>^6 (retired)</option>' in glaze
    assert 'value="item-6"' not in bisque
    answer = program_post(staff, cone="item-6", speed="medium", preheat_hours="0", hold_minutes="7")
    assert answer.status_code == 303
    program = staff.world.studio().item(CatalogList.FIRING_TYPES, ItemId("glaze")).default_program
    assert program is not None
    assert program.cone == "item-6"
