"""Nothing personal in any log line of a whole drop-off through the pages (CLAUDE.md)."""

import logging

import pytest

from asmbly_ceramics.domain.limits import DEVICE_LIMIT
from asmbly_ceramics.ports.errors import PhotosUnavailable, RecordsUnavailable
from asmbly_ceramics.web.security import DEVICE_COOKIE, RECEIVED_COOKIE
from tests.domain.builders import TEST_EMAIL, TEST_NAME, TEST_PHONE, TEST_PHONE_DIGITS
from tests.web.conftest import ADDRESS, SAME_ORIGIN, Site, set_cap


def record_values(record: logging.LogRecord) -> list[str]:
    """A record's message and each attribute's value (extras included), one text each.

    Checked one by one, never joined: joining puts `created` next to `msecs`, and a
    timestamp ending in `12` before `34.0` reads as the refused phone `12 34` (#26).
    """
    return [record.getMessage(), *(str(value) for value in vars(record).values())]


def holds(record: logging.LogRecord, secret: str) -> bool:
    return any(secret in value for value in record_values(record))


def test_a_detail_in_one_field_is_found() -> None:
    record = logging.LogRecord("asmbly_ceramics", logging.INFO, __file__, 1, "drop_off_page", (), None)
    record.outcome = "refused 12 34"
    assert holds(record, "12 34")


def test_neighboring_fields_never_make_a_detail() -> None:
    record = logging.LogRecord("asmbly_ceramics", logging.INFO, __file__, 1, "drop_off_page", (), None)
    record.created, record.msecs = 1794699025.034212, 34.0  # " ".join would read "12 34"
    assert not holds(record, "12 34")


def test_a_whole_drop_off_logs_nothing_personal(site: Site, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    tokens = []

    refused_email, refused_name, refused_phone = "not an address", "Refused Made-Up Name", "12 34"
    refused = site.details(email=refused_email, name=refused_name, phone=refused_phone)
    tokens.append(str(refused["submission"]))
    assert site.submit(refused).status_code == 400

    accepted = site.details()
    tokens.append(str(accepted["submission"]))
    assert site.submit(accepted).status_code == 303
    received_cookie = site.client.cookies.get(RECEIVED_COOKIE)
    assert site.client.get("/drop-off/received").status_code == 200

    # Upload slots: issued, then refused without the device cookie.
    slot_token = str(site.details()["submission"])
    tokens.append(slot_token)
    issued = site.client.post(
        "/drop-off/uploads", json={"count": 1, "submission": slot_token}, headers=SAME_ORIGIN
    )
    assert issued.status_code == 200
    device_before = site.device()
    site.client.cookies.clear()
    expired = site.client.post(
        "/drop-off/uploads", json={"count": 1, "submission": slot_token}, headers=SAME_ORIGIN
    )
    assert expired.json() == {"error": "expired"}
    site.client.cookies.set(DEVICE_COOKIE, device_before)

    # A failed commit, shown again with the same token.
    failing = site.details()
    tokens.append(str(failing["submission"]))
    site.world.records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
    assert site.submit(failing).status_code == 503
    site.world.photos.fail_with = PhotosUnavailable("SlowDown")
    unavailable = site.client.post(
        "/drop-off/uploads", json={"count": 1, "submission": slot_token}, headers=SAME_ORIGIN
    )
    assert unavailable.status_code == 503
    site.world.photos.fail_with = None

    for _ in range(DEVICE_LIMIT.limit):
        fields = site.details()
        tokens.append(str(fields["submission"]))
        site.submit(fields)
    assert site.submit(site.details()).status_code == 429
    device = site.device()

    # The daily cap on received emails (#30), from a new device: turned away, not taken.
    site.client.cookies.clear()
    set_cap(site, 1)
    capped = site.details()
    tokens.append(str(capped["submission"]))
    assert site.submit(capped).status_code == 429
    capped_device = site.device()

    secrets = {TEST_NAME, TEST_EMAIL, TEST_PHONE, TEST_PHONE_DIGITS, device, capped_device, ADDRESS, *tokens}
    secrets |= {refused_email, refused_name, refused_phone}
    assert received_cookie is not None
    secrets.add(received_cookie.split(".")[0])
    secrets.add(received_cookie.split(".")[0].removeprefix("submission#"))
    page_lines = [r for r in caplog.records if r.getMessage() == "drop_off_page"]
    assert {r.__dict__["outcome"] for r in page_lines} >= {
        "shown",
        "refused",
        "submitted",
        "rate_limited",
        "not_taken",
        "expired",
    }
    # The cap's refusal is below ERROR, so it stays out of the logged-errors alarm.
    [capped_line] = [r for r in caplog.records if r.__dict__.get("reason") == "daily_cap"]
    assert capped_line.levelno == logging.WARNING
    events = {r.getMessage() for r in caplog.records}
    assert {"drop_off_unavailable", "upload_slots_unavailable", "upload_slots"} <= events
    assert any(r.__dict__.get("fields") == "email,phone" for r in page_lines)
    assert any(r.__dict__.get("drop_off_id") == "AC-1" for r in page_lines)
    for secret in secrets:
        leaked = any(holds(record, secret) for record in caplog.records)
        assert not leaked, "a log line holds a personal detail or token"
