"""Every email needing attention, studio-wide (#4, #7), through `/console/emails`."""

from dataclasses import replace
from datetime import timedelta

import pytest

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.ports.records import Update
from asmbly_ceramics.use_cases.reject import UndoRequest
from tests.domain.builders import TEST_EMAIL, TEST_MESSAGE, TEST_NAME
from tests.use_cases.flows import STAFF_MEMBER, email_of, fired, send_all
from tests.web.console.conftest import OUTSIDER, Console

AC_1, AC_2 = DropOffId(1), DropOffId(2)


@pytest.fixture
def ready(console: Console) -> Console:
    console.drop_off(1)
    console.sign_in()
    return console


def failing(console: Console) -> None:
    console.world.mailer.fail_with = "MessageRejected"
    send_all(console.world)
    console.world.mailer.fail_with = None


def test_a_failed_ready_email_of_a_fired_drop_off_is_listed_after_its_load_leaves_the_loads_list(
    ready: Console,
) -> None:
    send_all(ready.world)
    fired(ready.world, AC_1)
    failing(ready)
    ready.world.clock.advance(timedelta(weeks=9))
    assert ready.world.list_loads()[1] == []
    page = ready.get("/console/emails")
    assert page.status_code == 200
    assert '<a class="row-link" href="/console/drop-offs/AC-1">AC-1</a>' in page.text
    assert "Ready for pickup" in page.text
    assert "Sending failed (MessageRejected)" in page.text


def test_the_band_links_to_the_list_only_when_an_email_needs_attention(ready: Console) -> None:
    for path in ("/console", "/console/drop-offs/AC-1"):
        assert "Emails need attention" not in ready.get(path).text
    failing(ready)
    for path in ("/console", "/console/drop-offs/AC-1", "/console/emails"):
        assert '<a href="/console/emails">Emails need attention (1)</a>' in ready.get(path).text


def test_each_row_retries_its_own_email(ready: Console) -> None:
    ready.drop_off(2)
    send_all(ready.world)
    ready.post(
        "/console/drop-offs/AC-2/reject",
        {"reason": "other", "message": TEST_MESSAGE, "version": ready.version(AC_2)},
    )
    failing(ready)
    page = ready.get("/console/emails").text
    rejected = next(e for e in ready.world.records.emails_for(AC_2) if e.kind is EmailKind.REJECTED)
    form = page.split('action="/console/drop-offs/AC-2/emails/rejected/retry"')[1].split("</form>")[0]
    assert f'name="occasion" value="{rejected.occasion}"' in form
    assert 'name="back" value="emails"' in form
    answer = ready.post(
        "/console/drop-offs/AC-2/emails/rejected/retry", {"occasion": rejected.occasion, "back": "emails"}
    )
    assert answer.headers["location"] == "/console/emails?done=retried&id=AC-2"
    assert (
        next(e for e in ready.world.records.emails_for(AC_2) if e.kind is EmailKind.REJECTED).status
        is EmailStatus.PENDING
    )
    assert email_of(ready.world, AC_1, EmailKind.RECEIVED).status is EmailStatus.SENT
    assert "The email to AC-2 will be sent again." in ready.get(answer.headers["location"]).text


def test_history_emails_are_not_listed(ready: Console) -> None:
    send_all(ready.world)  # AC-1's received email goes
    ready.drop_off(2)
    ready.post(
        "/console/drop-offs/AC-1/reject",
        {"reason": "other", "message": TEST_MESSAGE, "version": ready.version(AC_1)},
    )
    failing(ready)  # AC-1's rejection email and AC-2's received email fail
    ready.world.undo(UndoRequest(AC_1, int(ready.version(AC_1)), STAFF_MEMBER))
    drop_off = ready.world.records.drop_off(AC_2)
    assert drop_off is not None
    assert "AC-2" in ready.get("/console/emails").text
    closed = replace(drop_off, state=DropOffState.CLOSED, contact=None, photos=())
    ready.world.records.commit([Update(closed)])  # a closed drop-off's emails are history
    assert "No email needs attention." in ready.get("/console/emails").text


def test_a_stuck_email_shows_since_when(ready: Console) -> None:
    from asmbly_ceramics.domain.email import claim
    from asmbly_ceramics.domain.limits import STALE_SENDING_AFTER

    email = email_of(ready.world, AC_1, EmailKind.RECEIVED)
    ready.world.records.commit([Update(claim(email, ready.world.clock.now()))])
    ready.world.clock.advance(STALE_SENDING_AFTER + timedelta(minutes=1))
    assert "Stuck sending since" in ready.get("/console/emails").text


def test_a_row_whose_drop_off_is_missing_shows_without_a_link(
    ready: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing(ready)
    monkeypatch.setattr(ready.world.records, "drop_off", lambda id: None)
    page = ready.get("/console/emails").text
    assert '<td class="mono">AC-1</td>' in page
    assert 'href="/console/drop-offs/AC-1"' not in page


def test_the_list_shows_no_name_address_or_message(ready: Console) -> None:
    send_all(ready.world)
    ready.post(
        "/console/drop-offs/AC-1/reject",
        {"reason": "other", "message": TEST_MESSAGE, "version": ready.version(AC_1)},
    )
    failing(ready)
    page = ready.get("/console/emails").text
    for text in (TEST_NAME, TEST_EMAIL, TEST_MESSAGE):
        assert text not in page, text


def test_the_list_needs_the_ceramics_group(console: Console) -> None:
    console.drop_off(1)
    failing(console)
    assert console.get("/console/emails").status_code == 302
    console.sign_in(groups=("front-desk",), username=OUTSIDER)
    answer = console.get("/console/emails")
    assert answer.status_code == 403
    assert "AC-1" not in answer.text


def test_an_empty_list_says_so(ready: Console) -> None:
    assert "No email needs attention." in ready.get("/console/emails").text
