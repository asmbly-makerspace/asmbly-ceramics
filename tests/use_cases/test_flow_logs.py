"""No log record from a whole flow holds a person's details or a token (CLAUDE.md).

Next to phase 2's `test_no_personal_details_logged.py` (the form and rejection alone):
this runs a drop-off from submit through rejection and undo, a load fired, every email
sent (one failing) and retried, a settings change, a test email and the close, with
made-up details, and checks every captured record's message and every attribute on it.
"""

import logging
from datetime import timedelta

import pytest

from asmbly_ceramics.domain.email import EmailKind, EmailStatus
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.use_cases.reject import RejectRequest, UndoRequest
from tests.domain.builders import (
    TEST_EMAIL,
    TEST_MESSAGE,
    TEST_NAME,
    TEST_PHONE,
    TEST_PHONE_DIGITS,
    a_sending_address,
)
from tests.use_cases.conftest import DEVICE, SOURCE_ADDRESS, World
from tests.use_cases.flows import STAFF_EMAIL, STAFF_MEMBER, dropped_off, fired, send_all
from tests.use_cases.test_submit import a_device, a_token


def test_a_whole_flow_logs_no_personal_details(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    first = dropped_off(world, 1)
    second = dropped_off(world, 2)
    world.reject(RejectRequest(first, ItemId("other"), TEST_MESSAGE, version=1, staff=STAFF_MEMBER))
    world.undo(UndoRequest(first, version=2, staff=STAFF_MEMBER))
    load = fired(world, first, second)
    world.view_load(load)
    world.mailer.fail_with = "MessageRejected"
    world.send_email(first, EmailKind.RECEIVED, "")
    world.mailer.fail_with = None
    assert set(send_all(world)) == {EmailStatus.SENT}
    world.retry_email(first, EmailKind.RECEIVED, "", STAFF_MEMBER)
    send_all(world)
    studio = world.studio()
    world.change_email_settings(
        sending_address=a_sending_address("kilnops"),
        pickup_window_days="10",
        pickup_hours_text=studio.pickup_hours_text,
        version=studio.version,
        staff=STAFF_MEMBER,
    )
    world.send_test_email(sending_address=a_sending_address("kilnops"), staff=STAFF_MEMBER)
    world.clock.advance(timedelta(days=30))
    assert world.close().closed == (first, second)
    world.counts()

    secrets = {
        TEST_NAME,
        TEST_EMAIL,
        TEST_PHONE,
        TEST_PHONE_DIGITS,
        TEST_MESSAGE,
        STAFF_EMAIL,
        a_sending_address("kilnops"),
        a_token(1),
        a_token(2),
        a_device(1),
        DEVICE,
        SOURCE_ADDRESS,
    }
    events = {record.getMessage() for record in caplog.records}
    assert {
        "drop_off_submitted",
        "drop_off_rejected",
        "rejection_undone",
        "load_started",
        "added_to_load",
        "load_firing",
        "load_fired",
        "email_failed",
        "email_sent",
        "email_retried",
        "settings_changed",
        "test_email",
        "drop_off_closed",
        "close_run",
    } <= events
    for record in caplog.records:
        assert record.exc_info is None, f"{record.getMessage()} carries an exception's text"
        logged = [record.getMessage(), *(repr(value) for value in vars(record).values())]
        for secret in secrets:
            assert not any(secret.casefold() in text.casefold() for text in logged), (
                f"{record.getMessage()} holds a personal detail or a token"
            )
