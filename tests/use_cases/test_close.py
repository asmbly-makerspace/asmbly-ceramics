"""`CloseFinished` (#7), against the fakes: what is deleted, what is kept, and when."""

import logging
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import EmailKind
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.ports.errors import PhotosUnavailable, RecordsUnavailable
from asmbly_ceramics.ports.records import Conflict, Update
from asmbly_ceramics.use_cases.close import CloseReport
from asmbly_ceramics.use_cases.reject import RejectRequest
from tests.domain.builders import NOW, STAFF, TEST_MESSAGE
from tests.use_cases.conftest import World
from tests.use_cases.flows import STAFF_MEMBER, dropped_off, email_of, fired, send_all

AC_1, AC_2 = DropOffId(1), DropOffId(2)
# NOW is 12:30 on Friday 13 November in Austin. A 14-day window from then names Friday
# 27 November as "Pick up by", so it ends at the start of 28 November, Austin time.
WINDOW_ENDS = datetime(2026, 11, 28, 6, tzinfo=UTC)
SECOND = timedelta(seconds=1)


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, object]]:
    return [vars(r) for r in caplog.records if r.getMessage() == name]


def at(world: World, when: datetime) -> None:
    world.clock.advance(when - world.clock.now())


def stored(world: World, id: DropOffId) -> DropOff:
    drop_off = world.records.drop_off(id)
    assert drop_off is not None
    return drop_off


def fired_and_emailed(world: World, *numbers: int) -> None:
    """These drop-offs made, fired in one load and every email sent, all at NOW."""
    ids = [dropped_off(world, number) for number in numbers]
    fired(world, *ids)
    send_all(world)


def rejected(world: World, number: int) -> None:
    id = dropped_off(world, number)
    world.reject(RejectRequest(id, ItemId("other"), TEST_MESSAGE, version=1, staff=STAFF_MEMBER))


def test_a_fired_drop_off_closes_once_the_window_has_passed_since_the_ready_email(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    fired_and_emailed(world, 1)
    assert email_of(world, AC_1, EmailKind.READY).pickup_window_days == 14

    at(world, WINDOW_ENDS - SECOND)  # the last second of the "Pick up by" day
    assert world.close().closed == ()
    assert stored(world, AC_1).state is DropOffState.FIRED

    at(world, WINDOW_ENDS)
    report = world.close()

    assert (report.closed, report.failed) == ((AC_1,), 0)
    assert stored(world, AC_1).state is DropOffState.CLOSED
    assert [e["drop_off_id"] for e in events(caplog, "drop_off_closed")] == ["AC-1"]
    assert [e["count"] for e in events(caplog, "close_run")] == [0, 1]


def test_a_shorter_window_set_after_the_ready_email_doesnt_close_early(world: World) -> None:
    fired_and_emailed(world, 1)
    studio = world.studio()
    world.change_email_settings(
        sending_address=studio.sending_address,
        pickup_window_days="1",
        pickup_hours_text=studio.pickup_hours_text,
        version=studio.version,
        staff=STAFF_MEMBER,
    )

    at(world, NOW + timedelta(days=3))
    assert world.close().closed == ()
    at(world, WINDOW_ENDS)
    assert world.close().closed == (AC_1,)


def test_a_rejected_drop_off_closes_once_the_window_has_passed_since_the_rejection(world: World) -> None:
    rejected(world, 1)

    at(world, WINDOW_ENDS - SECOND)
    assert world.close().closed == ()
    at(world, WINDOW_ENDS)
    assert world.close().closed == (AC_1,)


def test_closing_deletes_name_email_phone_message_and_photos_and_keeps_the_rest(world: World) -> None:
    fired_and_emailed(world, 1)
    rejected(world, 2)
    before = {id: stored(world, id) for id in (AC_1, AC_2)}
    assert world.photos.kept_count(AC_1) == world.photos.kept_count(AC_2) == 4

    at(world, WINDOW_ENDS)
    assert world.close().closed == (AC_1, AC_2)

    for id, was in before.items():
        closed = stored(world, id)
        assert (closed.contact, closed.photos, closed.closed_at) == (None, (), WINDOW_ENDS)
        assert world.photos.kept_count(id) == 0
        # Kept: the ID, dates, firing type, glaze type, pieces, load and reason.
        assert (closed.id, closed.created_at, closed.firing_type, closed.glaze_type, closed.pieces) == (
            was.id,
            was.created_at,
            was.firing_type,
            was.glaze_type,
            was.pieces,
        )
        assert (closed.load_id, closed.fired_at) == (was.load_id, was.fired_at)
    rejection = stored(world, AC_2).rejection
    assert rejection is not None
    assert (rejection.reason, rejection.message, rejection.by) == (ItemId("other"), None, STAFF)


def test_a_fired_drop_off_whose_ready_email_failed_doesnt_close(world: World) -> None:
    id = dropped_off(world, 1)
    send_all(world)
    fired(world, id)
    world.mailer.fail_with = "MessageRejected"
    send_all(world)

    at(world, NOW + timedelta(days=365))
    assert world.close().closed == ()
    assert stored(world, AC_1).contact is not None
    # Once it is sent, the window starts.
    world.mailer.fail_with = None
    world.retry_email(AC_1, EmailKind.READY, "", STAFF_MEMBER)
    send_all(world)
    assert world.close().closed == ()
    at(world, world.clock.now() + timedelta(days=15))
    assert world.close().closed == (AC_1,)


def test_a_waiting_drop_off_never_closes(world: World) -> None:
    dropped_off(world, 1)
    at(world, NOW + timedelta(days=365))
    assert world.close().closed == ()
    assert stored(world, AC_1).state is DropOffState.WAITING


def test_photos_are_deleted_before_the_record_is_closed(world: World) -> None:
    fired_and_emailed(world, 1)
    at(world, WINDOW_ENDS)
    world.photos.fail_with = PhotosUnavailable("SlowDown")

    report = world.close()

    assert (report.closed, report.failed) == ((), 1)
    assert stored(world, AC_1).state is DropOffState.FIRED  # never closed with its photos left


def test_a_failed_commit_leaves_it_for_the_next_run(world: World, caplog: pytest.LogCaptureFixture) -> None:
    fired_and_emailed(world, 1)
    at(world, WINDOW_ENDS)
    world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")

    assert world.close().failed == 1
    assert world.photos.kept_count(AC_1) == 0  # photos first
    assert stored(world, AC_1).state is DropOffState.FIRED
    [record] = [r for r in caplog.records if r.getMessage() == "close_failed"]
    assert record.levelno == logging.ERROR
    assert (vars(record)["drop_off_id"], vars(record)["error_code"]) == ("AC-1", "InternalServerError")

    assert world.close().closed == (AC_1,)


def test_running_twice_closes_nothing_the_second_time(world: World) -> None:
    fired_and_emailed(world, 1)
    at(world, WINDOW_ENDS)
    assert world.close().closed == (AC_1,)
    commits = len(world.records.commits)

    assert world.close() == CloseReport((), 0)
    assert len(world.records.commits) == commits


def test_one_failure_doesnt_stop_the_run(world: World, caplog: pytest.LogCaptureFixture) -> None:
    fired_and_emailed(world, 1, 2)
    at(world, WINDOW_ENDS)
    world.records.fail_next_commit_with = ValueError("a bug")

    report = world.close()

    assert (report.closed, report.failed) == ((AC_2,), 1)
    [event] = events(caplog, "close_failed")
    assert (event["drop_off_id"], event["error_code"], event["reason"]) == (
        "AC-1",
        "ValueError",
        "unexpected",
    )


def test_a_drop_off_an_overlapping_run_closed_first_isnt_a_failure(world: World) -> None:
    fired_and_emailed(world, 1)
    at(world, WINDOW_ENDS)
    stale = world.records.drop_offs_in({DropOffState.FIRED})
    world.close()

    def stale_list(states: Collection[DropOffState]) -> list[DropOff]:
        return stale  # an eventually consistent list read before the other run's commit

    world.records.drop_offs_in = stale_list  # type: ignore[method-assign]  # the fake list replaced to stage a race
    report = world.close()

    assert (report.closed, report.failed) == ((), 0)


def test_a_conflict_on_a_drop_off_still_open_is_a_failure(world: World) -> None:
    fired_and_emailed(world, 1)
    at(world, WINDOW_ENDS)
    world.records.fail_next_commit_with = Conflict(["AC-1"])

    assert world.close().failed == 1
    assert stored(world, AC_1).state is DropOffState.FIRED


def test_a_sent_ready_email_without_its_window_is_reported_not_skipped(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """Phase 4's item conversion dropping the field must show, not keep details forever."""
    fired_and_emailed(world, 1)
    ready = email_of(world, AC_1, EmailKind.READY)
    world.records.commit([Update(replace(ready, pickup_window_days=None))])
    at(world, WINDOW_ENDS)

    assert world.close().failed == 1

    [event] = events(caplog, "close_failed")
    assert (event["drop_off_id"], event["error_code"], event["reason"]) == (
        "AC-1",
        "ValueError",
        "unexpected",
    )
    assert stored(world, AC_1).state is DropOffState.FIRED


def test_the_close_raises_when_it_cant_list_drop_offs(world: World) -> None:
    fired_and_emailed(world, 1)
    at(world, WINDOW_ENDS)
    world.studio()

    def unreachable(states: Collection[DropOffState]) -> list[DropOff]:
        raise RecordsUnavailable("InternalServerError")

    world.records.drop_offs_in = unreachable  # type: ignore[method-assign]  # the fake list replaced to fail
    with pytest.raises(RecordsUnavailable):
        world.close()  # the schedule retries the run


def test_nothing_is_deleted_on_the_word_of_a_stale_list(world: World) -> None:
    rejected(world, 1)
    at(world, WINDOW_ENDS)
    stale = world.records.drop_offs_in({DropOffState.REJECTED})
    drop_off = stored(world, AC_1)
    # Since the list was read, the drop-off went back to waiting.
    world.records.commit([Update(replace(drop_off, state=DropOffState.WAITING, rejection=None))])

    def stale_list(states: Collection[DropOffState]) -> list[DropOff]:
        return stale

    world.records.drop_offs_in = stale_list  # type: ignore[method-assign]  # the fake list replaced to stage a race
    report = world.close()

    assert (report.closed, report.failed) == ((), 0)
    assert world.photos.kept_count(AC_1) == 4
    assert stored(world, AC_1).state is DropOffState.WAITING


def test_a_fired_drop_off_without_a_ready_email_is_reported(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    fired_and_emailed(world, 1)
    world.records._items.pop(("email", AC_1, EmailKind.READY, ""))  # a broken record
    at(world, WINDOW_ENDS)

    assert world.close().failed == 1
    assert [e["drop_off_id"] for e in events(caplog, "close_failed")] == ["AC-1"]
