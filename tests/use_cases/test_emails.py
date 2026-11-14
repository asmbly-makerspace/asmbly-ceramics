"""`SendPendingEmail` and `RetryEmail` (#4, #2, #5, #6), against the fakes.

The person is made up (`tests/domain/builders.py`); assertions are on what was sent,
stored and logged.
"""

import logging
from dataclasses import fields, replace
from datetime import timedelta

import pytest

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus, claim
from asmbly_ceramics.domain.errors import EmailNotRetryable, NotFound
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.limits import STALE_SENDING_AFTER, STUDIO_TZ
from asmbly_ceramics.ports.errors import PhotosUnavailable, RecordsUnavailable
from asmbly_ceramics.ports.records import Conflict, Update
from asmbly_ceramics.use_cases.emails import EmailNeedingAttention, SendPendingEmail
from asmbly_ceramics.use_cases.reject import RejectRequest, UndoRequest
from tests.domain.builders import NOW, TEST_EMAIL, TEST_MESSAGE, a_sending_address
from tests.use_cases.conftest import World
from tests.use_cases.flows import STAFF_MEMBER, dropped_off, email_of, fired, pending, send_all
from tests.use_cases.test_submit import PHOTO, PHOTO_2

AC_1 = DropOffId(1)


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, object]]:
    return [vars(r) for r in caplog.records if r.getMessage() == name]


def send(world: World, email: Email) -> EmailStatus | None:
    return world.send_email(email.drop_off_id, email.kind, email.occasion)


def received(world: World) -> Email:
    return email_of(world, AC_1, EmailKind.RECEIVED)


def test_a_pending_email_is_sent_once_to_the_drop_offs_own_address(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    dropped_off(world, 1)

    assert send(world, received(world)) is EmailStatus.SENT

    [message] = world.mailer.sent
    assert message.to == TEST_EMAIL
    assert message.from_address == message.reply_to == a_sending_address()
    assert message.subject == "We received your drop-off (AC-1)"
    assert [(image.content_id, image.data) for image in message.inline] == [
        ("photo-1", PHOTO),
        ("photo-2", PHOTO_2),
    ]
    assert 'src="cid:photo-1"' in message.html
    stored = received(world)
    assert (stored.status, stored.sent_at, stored.attempts, stored.pickup_window_days) == (
        EmailStatus.SENT,
        NOW,
        1,
        None,
    )
    [event] = events(caplog, "email_sent")
    assert (event["kind"], event["drop_off_id"]) == ("received", "AC-1")


def test_a_duplicate_delivery_sends_nothing(world: World) -> None:
    dropped_off(world, 1)
    email = received(world)

    assert send(world, email) is EmailStatus.SENT
    assert send(world, email) is None

    assert len(world.mailer.sent) == 1


def test_a_claim_lost_to_another_invocation_sends_nothing(world: World) -> None:
    dropped_off(world, 1)
    email = received(world)
    world.records.fail_next_commit_with = Conflict(["AC-1"])

    assert send(world, email) is None

    assert world.mailer.sent == []
    assert received(world).status is EmailStatus.PENDING


def test_a_missing_or_not_pending_email_is_ignored(world: World) -> None:
    assert world.send_email(AC_1, EmailKind.RECEIVED, "") is None
    dropped_off(world, 1)
    world.records.commit([Update(claim(received(world), NOW))])

    assert send(world, received(world)) is None
    assert world.mailer.sent == []


def test_a_failure_before_the_claim_is_raised_so_the_stream_retries(world: World) -> None:
    dropped_off(world, 1)
    email = received(world)
    world.records.fail_reads_with = RecordsUnavailable("ProvisionedThroughputExceededException")

    with pytest.raises(RecordsUnavailable):
        send(world, email)

    world.records.fail_reads_with = None
    assert received(world).status is EmailStatus.PENDING
    world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        send(world, email)
    assert received(world).status is EmailStatus.PENDING
    assert world.mailer.sent == []


def test_the_email_uses_the_settings_in_force_when_sent(world: World) -> None:
    dropped_off(world, 1)
    studio = world.studio()
    world.change_email_settings(
        sending_address=a_sending_address("kilnops"),
        pickup_window_days="14",
        pickup_hours_text=studio.pickup_hours_text,
        version=studio.version,
        staff=STAFF_MEMBER,
    )

    send(world, received(world))

    [message] = world.mailer.sent
    assert message.from_address == a_sending_address("kilnops")


def test_a_ready_email_records_sent_at_for_the_pickup_window(world: World) -> None:
    dropped_off(world, 1)
    fired(world, AC_1)
    world.clock.advance(timedelta(hours=2))
    ready = email_of(world, AC_1, EmailKind.READY)

    assert send(world, ready) is EmailStatus.SENT

    stored = email_of(world, AC_1, EmailKind.READY)
    assert (stored.sent_at, stored.pickup_window_days) == (NOW + timedelta(hours=2), 14)
    [message] = world.mailer.sent
    assert message.subject == "Ready for pickup (AC-1)"
    assert len(message.inline) == 2


def test_a_failure_records_the_code_and_logs_email_failed(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    dropped_off(world, 1)
    world.mailer.fail_with = "MessageRejected"

    assert send(world, received(world)) is EmailStatus.FAILED

    stored = received(world)
    assert (stored.status, stored.error_code) == (EmailStatus.FAILED, "MessageRejected")
    [record] = [r for r in caplog.records if r.getMessage() == "email_failed"]
    assert record.levelno == logging.ERROR
    assert {key: vars(record)[key] for key in ("event", "kind", "drop_off_id", "error_code")} == {
        "event": "email_failed",
        "kind": "received",
        "drop_off_id": "AC-1",
        "error_code": "MessageRejected",
    }


class _Exploding:
    """A mailer whose send raises something no port promises, with text that must not leak."""

    def send(self, message: object) -> None:
        raise KeyError(TEST_EMAIL)


def test_an_unexpected_error_is_recorded_without_its_text_and_not_raised(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    dropped_off(world, 1)
    exploding = SendPendingEmail(
        world.records, world.photos, _Exploding(), world.clock, world.studio, world.composer
    )

    assert exploding(AC_1, EmailKind.RECEIVED, "") is EmailStatus.FAILED

    assert received(world).error_code == "unexpected"
    [event] = events(caplog, "email_failed")
    assert (event["error_code"], event["reason"]) == ("KeyError", "unexpected")
    assert all(TEST_EMAIL not in record.getMessage() and not record.exc_info for record in caplog.records)


def test_a_missing_photo_fails_the_email_with_photo_missing(world: World) -> None:
    dropped_off(world, 1)
    world.photos.delete_drop_off(AC_1)

    assert send(world, received(world)) is EmailStatus.FAILED

    assert received(world).error_code == "photo_missing"
    assert world.mailer.sent == []


def test_an_unreachable_photo_store_fails_the_email_as_not_sent(world: World) -> None:
    dropped_off(world, 1)
    world.photos.fail_with = PhotosUnavailable("SlowDown")

    assert send(world, received(world)) is EmailStatus.FAILED

    assert received(world).error_code == "photos_unavailable"


def test_an_email_that_cant_be_composed_fails_as_compose_failed(world: World) -> None:
    dropped_off(world, 1)
    drop_off = world.records.drop_off(AC_1)
    assert drop_off is not None
    world.records.commit([Update(replace(drop_off, firing_type=ItemId("gone")))])

    assert send(world, received(world)) is EmailStatus.FAILED

    assert received(world).error_code == "compose_failed"


def test_an_email_whose_drop_off_is_missing_fails(world: World) -> None:
    dropped_off(world, 1)
    email = received(world)
    world.records._items.pop(("drop_off", AC_1))  # a broken record, not a state any move makes

    assert send(world, email) is EmailStatus.FAILED
    assert received(world).error_code == "drop_off_missing"


def test_a_sent_email_whose_record_cant_be_saved_stays_sending(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    dropped_off(world, 1)
    email = received(world)
    commit = world.records.commit
    calls = 0

    def second_commit_fails(changes: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RecordsUnavailable("InternalServerError")
        commit(changes)  # type: ignore[arg-type]  # the fake commit replaced to fail once

    world.records.commit = second_commit_fails  # type: ignore[method-assign]  # the fake commit replaced to fail once

    assert send(world, email) is EmailStatus.SENDING

    assert len(world.mailer.sent) == 1
    assert received(world).status is EmailStatus.SENDING  # never marked failed: it went
    [event] = events(caplog, "email_unrecorded")
    assert event["error_code"] == "InternalServerError"
    assert events(caplog, "email_failed") == []


def test_a_failure_whose_record_cant_be_saved_is_still_logged_for_the_alarm(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    dropped_off(world, 1)
    world.mailer.fail_with = "Throttling"
    commit = world.records.commit
    calls = 0

    def second_commit_fails(changes: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise Conflict(["AC-1"])
        commit(changes)  # type: ignore[arg-type]  # the fake commit replaced to fail once

    world.records.commit = second_commit_fails  # type: ignore[method-assign]  # the fake commit replaced to fail once

    assert send(world, received(world)) is EmailStatus.FAILED

    assert [e["error_code"] for e in events(caplog, "email_failed")] == ["Throttling"]
    assert [e["error_code"] for e in events(caplog, "email_unrecorded")] == ["Conflict"]


def rejected(world: World) -> Email:
    """AC-1 made, its received email sent, then rejected: its rejected email pending."""
    dropped_off(world, 1)
    send_all(world)
    world.reject(RejectRequest(AC_1, ItemId("other"), TEST_MESSAGE, version=1, staff=STAFF_MEMBER))
    [email] = pending(world)
    return email


def test_an_undone_rejections_email_is_cancelled_not_sent(world: World) -> None:
    email = rejected(world)
    sent_before = len(world.mailer.sent)
    world.undo(UndoRequest(AC_1, version=2, staff=STAFF_MEMBER))

    # The undo cancelled the pending email; a delivery already in flight does nothing.
    assert send(world, email) is None

    assert email_of(world, AC_1, EmailKind.REJECTED, email.occasion).status is EmailStatus.CANCELLED
    assert len(world.mailer.sent) == sent_before


def test_a_pending_email_of_an_undone_rejection_is_cancelled_by_the_sender(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    email = rejected(world)
    drop_off = world.records.drop_off(AC_1)
    assert drop_off is not None
    # Undone behind the outbox's back, as a race leaves it: the email still pending.
    world.records.commit([Update(replace(drop_off, state=DropOffState.WAITING, rejection=None))])
    sent_before = len(world.mailer.sent)

    assert send(world, email) is EmailStatus.CANCELLED

    assert len(world.mailer.sent) == sent_before
    assert email_of(world, AC_1, EmailKind.REJECTED, email.occasion).status is EmailStatus.CANCELLED
    assert [e["drop_off_id"] for e in events(caplog, "email_cancelled")] == ["AC-1"]


def test_a_rejection_read_back_in_another_offset_is_still_sent(world: World) -> None:
    email = rejected(world)
    drop_off = world.records.drop_off(AC_1)
    assert drop_off is not None
    assert drop_off.rejection is not None
    austin = replace(drop_off.rejection, at=drop_off.rejection.at.astimezone(STUDIO_TZ))
    world.records.commit([Update(replace(drop_off, rejection=austin))])

    assert send(world, email) is EmailStatus.SENT
    assert world.mailer.sent[-1].subject == "Your drop-off needs attention (AC-1)"


def test_a_closed_drop_offs_email_is_cancelled(world: World) -> None:
    dropped_off(world, 1)
    email = received(world)
    drop_off = world.records.drop_off(AC_1)
    assert drop_off is not None
    world.records.commit([Update(replace(drop_off, state=DropOffState.CLOSED, contact=None, photos=()))])

    assert send(world, email) is EmailStatus.CANCELLED
    assert world.mailer.sent == []


def test_retry_requeues_only_that_email_and_a_send_clears_the_failure(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    dropped_off(world, 1)
    dropped_off(world, 2)
    world.mailer.fail_with = "Throttling"
    send_all(world)
    assert [e.status for e in world.records.emails_in({EmailStatus.FAILED})] == [EmailStatus.FAILED] * 2
    world.mailer.fail_with = None

    retried = world.retry_email(AC_1, EmailKind.RECEIVED, "", STAFF_MEMBER)

    assert (retried.status, retried.error_code) == (EmailStatus.PENDING, None)
    assert [(e.drop_off_id, e.kind) for e in pending(world)] == [(AC_1, EmailKind.RECEIVED)]
    assert email_of(world, DropOffId(2), EmailKind.RECEIVED).status is EmailStatus.FAILED
    assert send(world, retried) is EmailStatus.SENT
    assert received(world).status is EmailStatus.SENT
    assert world.view(AC_1).emails_needing_attention == ()
    [event] = events(caplog, "email_retried")
    assert (event["drop_off_id"], event["kind"], event["user"]) == ("AC-1", "received", STAFF_MEMBER.username)


def test_retry_takes_an_email_stuck_sending(world: World) -> None:
    dropped_off(world, 1)
    world.records.commit([Update(claim(received(world), NOW))])
    world.clock.advance(STALE_SENDING_AFTER + timedelta(seconds=1))

    retried = world.retry_email(AC_1, EmailKind.RECEIVED, "", STAFF_MEMBER)

    assert retried.status is EmailStatus.PENDING


def test_retry_refuses_a_sent_email(world: World) -> None:
    dropped_off(world, 1)
    send_all(world)

    with pytest.raises(EmailNotRetryable):
        world.retry_email(AC_1, EmailKind.RECEIVED, "", STAFF_MEMBER)
    with pytest.raises(EmailNotRetryable):
        world.retry_email(AC_1, EmailKind.READY, "", STAFF_MEMBER)


def test_retry_refuses_a_closed_drop_offs_email(world: World) -> None:
    dropped_off(world, 1)
    world.mailer.fail_with = "Throttling"
    send_all(world)
    drop_off = world.records.drop_off(AC_1)
    assert drop_off is not None
    world.records.commit([Update(replace(drop_off, state=DropOffState.CLOSED, contact=None, photos=()))])

    with pytest.raises(EmailNotRetryable):
        world.retry_email(AC_1, EmailKind.RECEIVED, "", STAFF_MEMBER)


def test_retry_of_a_pending_email_changes_nothing(world: World) -> None:
    dropped_off(world, 1)
    commits = len(world.records.commits)

    assert world.retry_email(AC_1, EmailKind.RECEIVED, "", STAFF_MEMBER) == received(world)
    assert len(world.records.commits) == commits


def test_retry_of_an_unknown_drop_off_is_not_found(world: World) -> None:
    dropped_off(world, 1)
    world.records._items.pop(("drop_off", AC_1))

    with pytest.raises(NotFound):
        world.retry_email(AC_1, EmailKind.RECEIVED, "", STAFF_MEMBER)


def test_retry_requeues_a_pending_email_the_stream_gave_up_on(world: World) -> None:
    dropped_off(world, 1)
    world.clock.advance(STALE_SENDING_AFTER + timedelta(seconds=1))
    assert [e.drop_off_id for e in world.view(AC_1).emails_needing_attention] == [AC_1]
    commits = len(world.records.commits)

    retried = world.retry_email(AC_1, EmailKind.RECEIVED, "", STAFF_MEMBER)

    # Written again, so the stream delivers it again.
    assert len(world.records.commits) == commits + 1
    assert (retried.status, retried.retried_at) == (EmailStatus.PENDING, world.clock.now())
    assert world.view(AC_1).emails_needing_attention == ()


def test_a_cancel_lost_to_the_undo_isnt_logged_as_a_failure(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    email = rejected(world)
    drop_off = world.records.drop_off(AC_1)
    assert drop_off is not None
    # Undone behind the outbox's back, and the undo's cancel lands before the sender's.
    world.records.commit([Update(replace(drop_off, state=DropOffState.WAITING, rejection=None))])
    world.records.fail_next_commit_with = None
    commit = world.records.commit
    calls = 0

    def cancel_conflicts(changes: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise Conflict(["AC-1"])
        commit(changes)  # type: ignore[arg-type]  # the fake commit replaced to fail once

    world.records.commit = cancel_conflicts  # type: ignore[method-assign]  # the fake commit replaced to fail once

    assert send(world, email) is EmailStatus.CANCELLED

    assert events(caplog, "email_failed") == []
    assert events(caplog, "email_unrecorded") == []


def test_a_store_that_cant_be_read_after_the_claim_fails_as_not_sent(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    dropped_off(world, 1)
    email = received(world)
    read = world.records.drop_off

    def unreachable(id: DropOffId) -> object:
        raise RecordsUnavailable("ProvisionedThroughputExceededException")

    world.records.drop_off = unreachable  # type: ignore[assignment,method-assign]  # the fake read replaced to fail
    assert send(world, email) is EmailStatus.FAILED
    world.records.drop_off = read  # type: ignore[method-assign]  # restored

    assert received(world).error_code == "records_unavailable"
    [event] = events(caplog, "email_failed")
    assert event["error_code"] == "ProvisionedThroughputExceededException"
    assert "reason" not in event
    assert world.mailer.sent == []


def test_retry_refuses_an_undone_rejections_failed_email(world: World) -> None:
    email = rejected(world)
    world.mailer.fail_with = "MessageRejected"
    send(world, email)
    world.undo(UndoRequest(AC_1, version=2, staff=STAFF_MEMBER))

    with pytest.raises(EmailNotRetryable):
        world.retry_email(AC_1, EmailKind.REJECTED, email.occasion, STAFF_MEMBER)


def test_retry_requeues_a_failed_rejected_email_by_its_occasion(world: World) -> None:
    email = rejected(world)
    world.mailer.fail_with = "Throttling"
    send(world, email)
    world.mailer.fail_with = None

    retried = world.retry_email(AC_1, EmailKind.REJECTED, email.occasion, STAFF_MEMBER)

    assert (retried.occasion, retried.status) == (email.occasion, EmailStatus.PENDING)
    assert send(world, retried) is EmailStatus.SENT
    assert world.mailer.sent[-1].subject == "Your drop-off needs attention (AC-1)"


def attention(world: World) -> list[tuple[str, EmailKind, EmailStatus, str | None]]:
    return [
        (str(row.drop_off_id), row.kind, row.status, row.error_code)
        for row in world.emails_needing_attention()
    ]


def test_a_fired_drop_offs_failed_ready_email_needs_attention_after_its_load_leaves_the_list(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    dropped_off(world, 1)
    send_all(world)
    fired(world, AC_1)
    world.mailer.fail_with = "MessageRejected"
    send_all(world)
    world.mailer.fail_with = None
    world.clock.advance(timedelta(weeks=9))
    caplog.clear()

    assert world.list_loads()[1] == []  # its load is no longer listed
    assert attention(world) == [("AC-1", EmailKind.READY, EmailStatus.FAILED, "MessageRejected")]
    assert caplog.records == []  # a read: nothing is logged

    [row] = world.emails_needing_attention()
    retried = world.retry_email(row.drop_off_id, row.kind, row.occasion, STAFF_MEMBER)
    assert send(world, retried) is EmailStatus.SENT
    assert attention(world) == []


def test_needs_attention_rows_hold_keys_and_states_only() -> None:
    assert [field.name for field in fields(EmailNeedingAttention)] == [
        "drop_off_id",
        "kind",
        "occasion",
        "status",
        "error_code",
        "created_at",
    ]


def test_a_stuck_email_needs_attention_only_once_stale(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)
    world.records.commit([Update(claim(email_of(world, DropOffId(2), EmailKind.RECEIVED), NOW))])

    assert attention(world) == []

    world.clock.advance(STALE_SENDING_AFTER + timedelta(seconds=1))

    assert attention(world) == [
        ("AC-1", EmailKind.RECEIVED, EmailStatus.PENDING, None),
        ("AC-2", EmailKind.RECEIVED, EmailStatus.SENDING, None),
    ]


def test_history_never_needs_attention(world: World) -> None:
    email = rejected(world)
    world.mailer.fail_with = "MessageRejected"
    send(world, email)
    world.undo(UndoRequest(AC_1, version=2, staff=STAFF_MEMBER))
    dropped_off(world, 2)
    send_all(world)  # still failing: AC-2's received email fails
    drop_off = world.records.drop_off(DropOffId(2))
    assert drop_off is not None
    world.records.commit([Update(replace(drop_off, state=DropOffState.CLOSED, contact=None, photos=()))])

    assert attention(world) == []


def test_an_email_of_a_missing_drop_off_is_shown_not_hidden(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    dropped_off(world, 1)
    world.mailer.fail_with = "MessageRejected"
    send_all(world)
    monkeypatch.setattr(world.records, "drop_off", lambda id: None)

    assert attention(world) == [("AC-1", EmailKind.RECEIVED, EmailStatus.FAILED, "MessageRejected")]
