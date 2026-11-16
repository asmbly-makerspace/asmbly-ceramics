"""Contact details only on console pages, never on a public page, in a URL or in a log
(#3, CLAUDE.md). The person is made up, with details unique enough to search for."""

import logging

import pytest

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.ports.staff import StaffMember
from tests.use_cases.flows import STAFF_EMAIL
from tests.web.conftest import Site
from tests.web.console.conftest import OUTSIDER, Console
from tests.web.test_logging import holds

NAME = "Quillon Vantreese"
SEARCH = "Vantree"
MESSAGE = "Zephyrine glaze pooled at the foot ring"
AC_1 = DropOffId(1)


def details_in(text: str) -> list[str]:
    from tests.domain.builders import TEST_EMAIL, TEST_PHONE_DIGITS

    return [
        secret
        for secret in (NAME, TEST_EMAIL, TEST_PHONE_DIGITS, TEST_PHONE_DIGITS[-4:], MESSAGE)
        if secret in text
    ]


def test_no_public_page_shows_contact_details(console: Console, site: Site) -> None:
    console.drop_off(1, name=NAME)
    console.sign_in()
    console.post(
        "/console/drop-offs/AC-1/reject",
        {"reason": "other", "message": MESSAGE, "version": console.version(AC_1)},
    )
    console.client.cookies.clear()
    pages = [
        console.get("/console/signed-out"),
        console.get("/console"),  # the sign-in redirect
        console.get("/console/auth/sign-in"),
        console.get("/console/drop-offs/AC-1"),
        console.get("/console/drop-offs/AC-1/photos/1"),
        console.get("/console/nowhere"),
        console.client.get(
            "/console/auth/callback", params={"code": "x", "state": "y"}, follow_redirects=False
        ),
    ]
    console.sign_in(groups=("front-desk",), username=OUTSIDER)
    pages.append(console.get("/console/drop-offs/AC-1"))
    pages.append(site.client.get("/"))
    for page in pages:
        assert details_in(page.text) == [], page.url
        assert details_in(page.headers.get("location", "")) == [], page.url


def test_nothing_logged_holds_a_name_email_phone_message_or_token(
    console: Console, caplog: pytest.LogCaptureFixture
) -> None:
    from tests.domain.builders import TEST_EMAIL, TEST_PHONE, TEST_PHONE_DIGITS

    caplog.set_level(logging.DEBUG)
    console.drop_off(1, name=NAME)
    console.tokens.members["made-up-secret-token"] = StaffMember("kiln-tech", STAFF_EMAIL)
    console.get("/console/auth/sign-in")
    console.tokens.approve("made-up-secret-code", "made-up-secret-token")
    from tests.web.console.test_auth import started_state

    signed = console.client.get(
        "/console/auth/callback",
        params={"code": "made-up-secret-code", "state": started_state(console)},
        follow_redirects=False,
    )
    assert signed.status_code == 303
    version = console.version(AC_1)
    steps = [
        console.get("/console"),
        console.post("/console/search", {"q": SEARCH}),
        console.get("/console/drop-offs/AC-1"),
        console.get("/console/drop-offs/AC-1/photos/1"),
        console.post(
            "/console/drop-offs/AC-1/reject/preview",
            {"reason": "other", "message": MESSAGE, "version": version},
        ),
        console.post(
            "/console/drop-offs/AC-1/reject", {"reason": "other", "message": "", "version": version}
        ),
        console.post(
            "/console/drop-offs/AC-1/reject", {"reason": "other", "message": MESSAGE, "version": version}
        ),
        console.post("/console/drop-offs/AC-1/undo-reject", {"version": console.version(AC_1)}),
        console.post("/console/sign-out"),
    ]
    assert [s.status_code for s in steps] == [200, 200, 200, 200, 200, 400, 303, 303, 200]
    # The test client's own `httpx2` lines (its request URLs) are the test's, not the app's.
    records = [r for r in caplog.records if not r.name.startswith("httpx")]
    assert records
    secrets = [
        NAME,
        SEARCH,
        TEST_EMAIL,
        TEST_PHONE,
        TEST_PHONE_DIGITS,
        MESSAGE,
        "made-up-secret-token",
        "made-up-secret-code",
        "kiln.tech@",
    ]
    for record in records:
        for secret in secrets:
            assert not holds(record, secret), (record.getMessage(), secret)
    events = [r.message for r in caplog.records if r.name == "asmbly_ceramics"]
    assert {"signed_in", "drop_off_rejected", "rejection_undone", "signed_out"} <= set(events)


def test_the_record_steps_and_history_hold_no_contact_details_and_echo_nothing_typed(
    console: Console, caplog: pytest.LogCaptureFixture
) -> None:
    """#42: the firing record, the steps and the history show staff usernames, studio items
    and numbers only; a redirect after a save holds a fixed word, never a value typed."""
    from asmbly_ceramics.domain.ids import LoadId

    caplog.set_level(logging.DEBUG)
    console.drop_off(1, name=NAME)
    console.sign_in()
    started = console.post(
        "/console/loads", {"kiln": "athena", "firing_type": "bisque", "date": "2026-11-13"}
    )
    assert started.status_code == 303
    assert console.post("/console/loads/L-1/add", {"drop_off": "AC-1"}).status_code == 303

    def version() -> str:
        load = console.world.records.load(LoadId(1))
        assert load is not None
        return str(load.version)

    saved = console.post("/console/loads/L-1/record", {"version": version(), "max_temp_f": "2236"})
    corrected = console.post(
        "/console/loads/L-1/steps/started/time", {"version": version(), "at": "2026-11-13T11:17"}
    )
    page = console.get("/console/loads/L-1").text

    for answer in (started, saved, corrected):
        location = answer.headers.get("location", "")
        assert "2236" not in location
        assert "11:17" not in location
        assert "11%3A17" not in location
        assert details_in(location) == []
    after_members = page.split('id="record"')[1]  # the record, the emails and the history
    assert details_in(after_members) == []
    assert "Max temp: 2,236 °F" in after_members
    for record in caplog.records:
        assert not holds(record, "2236"), record.getMessage()
        assert not holds(record, NAME), record.getMessage()
