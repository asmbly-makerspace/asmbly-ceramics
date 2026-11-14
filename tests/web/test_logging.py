"""Nothing personal in any log line of a whole drop-off through the pages (CLAUDE.md)."""

import logging

import pytest

from asmbly_ceramics.domain.limits import DEVICE_LIMIT
from asmbly_ceramics.ports.errors import PhotosUnavailable, RecordsUnavailable
from asmbly_ceramics.web.security import DEVICE_COOKIE, RECEIVED_COOKIE
from tests.domain.builders import TEST_EMAIL, TEST_NAME, TEST_PHONE, TEST_PHONE_DIGITS
from tests.web.conftest import ADDRESS, SAME_ORIGIN, Site


def record_text(record: logging.LogRecord) -> str:
    return " ".join([record.getMessage(), *(str(value) for value in record.__dict__.values())])


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

    secrets = {TEST_NAME, TEST_EMAIL, TEST_PHONE, TEST_PHONE_DIGITS, device, ADDRESS, *tokens}
    secrets |= {refused_email, refused_name, refused_phone}
    assert received_cookie is not None
    secrets.add(received_cookie.split(".")[0])
    secrets.add(received_cookie.split(".")[0].removeprefix("submission#"))
    texts = [record_text(record) for record in caplog.records]
    page_lines = [r for r in caplog.records if r.getMessage() == "drop_off_page"]
    assert {r.__dict__["outcome"] for r in page_lines} >= {
        "shown",
        "refused",
        "submitted",
        "rate_limited",
        "expired",
    }
    events = {r.getMessage() for r in caplog.records}
    assert {"drop_off_unavailable", "upload_slots_unavailable", "upload_slots"} <= events
    assert any(r.__dict__.get("fields") == "email,phone" for r in page_lines)
    assert any(r.__dict__.get("drop_off_id") == "AC-1" for r in page_lines)
    for secret in secrets:
        assert not any(secret in text for text in texts), "a log line holds a personal detail or token"
