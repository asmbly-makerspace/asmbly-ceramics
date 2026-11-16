"""No log record from the use cases holds a person's details or a token (CLAUDE.md).

Runs the form's submit (accepted and refused), the waiting list, a search by name, one
drop-off's view, a rejection's preview, the rejection and its undo with made-up details,
and checks every captured record's message and every attribute on it, extras included.
"""

import logging
from datetime import timedelta

import pytest

from asmbly_ceramics.domain.errors import InvalidDetails
from asmbly_ceramics.domain.firing import record_values
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.load import Step
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.firing_log import FiringKind
from asmbly_ceramics.use_cases.reject import RejectRequest, UndoRequest
from tests.domain.builders import (
    NOW,
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


def test_the_firing_record_logs_field_names_never_values(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    staff = StaffMember(STAFF, STAFF_EMAIL)
    load = world.start_load(ItemId("athena"), ItemId("glaze"), None, staff, test=True)
    typed = {"max_temp_f": "2236", "board_temp_f": "157", "cost": "8.19", "firing_time": "11:38"}

    saved = world.save_firing_record(load.id, record_values(load.record) | typed, load.version, staff)
    world.clock.advance(timedelta(minutes=5))
    world.correct_step_time(load.id, Step.STARTED, NOW - timedelta(minutes=42), saved.version, staff)
    world.firing_log(None, None, None, FiringKind.ALL)
    world.view_load(load.id)

    [saved_line] = [vars(r) for r in caplog.records if r.getMessage() == "firing_record_saved"]
    assert saved_line["fields"] == "firing_time,max_temp_f,board_temp_f,cost"
    assert any(r.getMessage() == "step_time_corrected" for r in caplog.records)
    standard = set(vars(logging.makeLogRecord({})))  # a record's own attributes: times, paths
    values = {"2236", "2,236", "157", "8.19", "819", "11:38", "698", "12:30", "11:48", "Started", "Corrected"}
    for record in caplog.records:
        extras = [repr(value) for key, value in vars(record).items() if key not in standard]
        for text in (record.getMessage(), *extras):
            assert not any(value in text for value in values), (
                f"{record.getMessage()} holds a value staff typed"
            )
