"""The settings page (#6): the sending address and its test email, the pickup window and
hours, the studio's lists, and the change history."""

import html
import logging
import re

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
from tests.use_cases.flows import ATHENA, STAFF_EMAIL, fired, send_all
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
    assert "Athena is used by a drop-off or a load: retire it instead." in answer.text
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
