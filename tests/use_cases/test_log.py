"""`log_event`: fixed field names, and only the event name in a record's message."""

import logging

import pytest

from asmbly_ceramics.domain.ids import DropOffId, LoadId, new_item_id
from asmbly_ceramics.use_cases.log import LOG_FIELDS, log_event


def test_unknown_log_field_raises(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ValueError, match="unknown log fields: email"):
        log_event("drop_off_received", drop_off_id="AC-12", email="someone")
    with pytest.raises(ValueError, match="snake_case"):
        log_event("received %s")
    with pytest.raises(TypeError):
        log_event("drop_off_received", count=True)
    assert caplog.records == []


def test_log_event_puts_the_fields_in_extra_and_only_the_event_in_the_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    log_event("upload_slots_refused", level=logging.WARNING, reason="device_limit", count=3)
    [record] = caplog.records
    assert record.name == "asmbly_ceramics"
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "upload_slots_refused"
    assert record.args == ()
    assert vars(record)["event"] == "upload_slots_refused"
    assert vars(record)["reason"] == "device_limit"
    assert vars(record)["count"] == 3


def test_a_value_that_isnt_an_id_or_a_word_is_logged_as_invalid(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    address = "test.person" + "@" + "example.org"
    log_event("drop_off_received", drop_off_id="AC-12", user=address, reason="two words", count=0)
    [record] = caplog.records
    assert vars(record)["drop_off_id"] == "AC-12"
    assert vars(record)["user"] == "invalid"
    assert vars(record)["reason"] == "invalid"
    assert vars(record)["count"] == 0
    assert address not in str(vars(record))
    log_event("x", fields="name,email,photos", error_code="ThrottlingException", load_id="L-4")
    assert vars(caplog.records[-1])["fields"] == "name,email,photos"
    assert vars(caplog.records[-1])["error_code"] == "ThrottlingException"


VALID = {
    "drop_off_id": "AC-12",
    "load_id": "L-4",
    "user": "kiln.tech-2",
    "kind": "received",
    "outcome": "ok",
    "reason": "not-dry",
    "error_code": "ThrottlingException",
    "count": 0,
    "fields": "name,firing_type,photo.2",
    "list": "glaze_types",
    "item": "cone-6",
}


def test_every_log_field_is_accepted(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    assert set(VALID) == LOG_FIELDS - {"event"}
    # mypy can't tell the dict holds no `level` key.
    log_event("everything", **VALID)  # type: ignore[arg-type]
    [record] = caplog.records
    assert {name: vars(record)[name] for name in LOG_FIELDS} == {**VALID, "event": "everything"}


# Made-up values with the shape of what must never be logged: a 555-01xx phone number,
# TEST-NET and documentation IP addresses, a random-looking token like the device cookie
# or the submission token, the keyed hashes, and a bare 64-character digest.
PHONE = "512-555-" + "0142"  # built in code, so the repository holds no phone number
PHONE_DIGITS = "512555" + "0142"
IPV4 = "192.0.2.10"
IPV6 = "2001:db8::1"
TOKEN = "Zq7_Kx2-Mn9pLv4Rt8Yw3Bc6"
LETTERS_TOKEN = "Q" + "r" * 21  # a token can be letters only: see `test_a_shape_cant_refuse_every_token`
DIGEST = "a1" * 32
HASHES = ("device#" + DIGEST, "submission#" + DIGEST, "address#" + DIGEST)
DISALLOWED = (PHONE, PHONE_DIGITS, IPV4, IPV6, TOKEN, DIGEST, *HASHES)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (name, value)
        for name in sorted(LOG_FIELDS - {"event"})
        for value in DISALLOWED
        # A username may be any handle: see `test_a_shape_cant_refuse_every_token`.
        if (name, value) != ("user", TOKEN)
    ],
)
def test_a_phone_an_address_or_a_token_is_logged_as_invalid_in_every_field(
    caplog: pytest.LogCaptureFixture, name: str, value: str
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    # mypy reads `**{name: value}` as possibly filling `level`, an int; `name` never is.
    log_event("x", **{name: value})  # type: ignore[arg-type]
    [record] = caplog.records
    assert vars(record)[name] == "invalid"
    assert value not in str(vars(record))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("drop_off_id", 12),
        ("drop_off_id", "ac-12"),
        ("drop_off_id", "AC-012"),
        ("drop_off_id", "L-4"),
        ("load_id", 4),
        ("load_id", "AC-12"),
        ("count", "abc"),
        ("count", "3"),
        ("kind", "Received"),
        ("outcome", "two words"),
        ("list", "glaze-types"),
        ("reason", "x:y"),
        ("item", "Cone 6"),
        ("error_code", "Error 500"),
        ("error_code", "x" * 65),
        ("error_code", "x" * 64),
        ("error_code", "1234"),
        ("error_code", "Error-500"),
        ("item", "06"),
        ("reason", "512-555-01"),
        ("fields", "name,"),
        ("fields", "Name"),
        ("user", 7),
        ("user", "kiln:tech"),
        ("kind", "x" * 41),
    ],
)
def test_a_value_without_its_fields_shape_is_logged_as_invalid(
    caplog: pytest.LogCaptureFixture, name: str, value: str | int
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    # mypy reads `**{name: value}` as possibly filling `level`, an int; `name` never is.
    log_event("x", **{name: value})  # type: ignore[arg-type]
    assert vars(caplog.records[-1])[name] == "invalid"


def test_a_shape_cant_refuse_every_token(caplog: pytest.LogCaptureFixture) -> None:
    """Why the docstring still tells callers what to pass: shapes narrow, they can't judge."""
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    log_event("x", error_code=LETTERS_TOKEN, user=TOKEN)
    assert vars(caplog.records[-1])["error_code"] == LETTERS_TOKEN
    assert vars(caplog.records[-1])["user"] == TOKEN


@pytest.mark.parametrize(
    "code",
    ["ThrottlingException", "EC2ThrottledException", "photo_missing", "404", "KeyError", "unknown", "x" * 63],
)
def test_every_planned_error_code_is_logged(caplog: pytest.LogCaptureFixture, code: str) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    log_event("email_failed", error_code=code)
    assert vars(caplog.records[-1])["error_code"] == code


def test_ids_and_slugs_are_checked_by_the_domain_that_makes_them(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    numbered = new_item_id("06", [])
    log_event(
        "x",
        drop_off_id=str(DropOffId(10**11)),
        load_id=str(LoadId(4)),
        item=numbered,
        reason=numbered,
    )
    record = vars(caplog.records[-1])
    assert record["drop_off_id"] == "AC-" + str(10**11)
    assert record["load_id"] == "L-4"
    assert record["item"] == record["reason"] == numbered
