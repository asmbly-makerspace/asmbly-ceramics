"""No log record from the use cases holds a person's details or a token (CLAUDE.md).

Runs the form's submit (accepted and refused), the waiting list, a search by name, one
drop-off's view, a rejection's preview, the rejection and its undo with made-up details,
and checks every captured record's message and every attribute on it, extras included.
"""

import logging

import pytest

from asmbly_ceramics.domain.errors import InvalidDetails
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.reject import RejectRequest, UndoRequest
from tests.domain.builders import (
    STAFF,
    TEST_EMAIL,
    TEST_MESSAGE,
    TEST_NAME,
    TEST_PHONE,
    TEST_PHONE_DIGITS,
    an_address,
)
from tests.use_cases.conftest import DEVICE, SOURCE_ADDRESS, World
from tests.use_cases.test_submit import TOKEN, a_request, a_token

STAFF_EMAIL = an_address("kiln.tech")


def test_nothing_logged_holds_personal_details(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    staff = StaffMember(STAFF, STAFF_EMAIL)

    with pytest.raises(InvalidDetails):
        world.submit(a_request(world, token=a_token(2), email="not an address", phone="12"))
    submitted = world.submit(a_request(world))
    id = submitted.view.id
    assert id == DropOffId(1)

    world.waiting()
    world.find("test pers")
    world.find(str(id))
    world.view(id)
    request = RejectRequest(id, ItemId("other"), TEST_MESSAGE, version=1, staff=staff)
    world.preview(request, lambda ref: f"/console/drop-offs/{ref.drop_off_id}/photos/{ref.index}")
    world.reject(request)
    world.undo(UndoRequest(id, version=2, staff=staff))

    secrets = {
        TEST_NAME,
        TEST_EMAIL,
        TEST_PHONE,
        TEST_PHONE_DIGITS,
        TEST_MESSAGE,
        STAFF_EMAIL,
        TOKEN,
        a_token(2),
        DEVICE,
        SOURCE_ADDRESS,
        "test pers",
    }
    events = [record.getMessage() for record in caplog.records]
    assert {"drop_off_refused", "drop_off_submitted", "drop_off_rejected", "rejection_undone"} <= set(events)
    for record in caplog.records:
        logged = [record.getMessage(), *(repr(value) for value in vars(record).values())]
        for secret in secrets:
            assert not any(secret.casefold() in text.casefold() for text in logged), (
                f"{record.getMessage()} holds a personal detail or a token"
            )
