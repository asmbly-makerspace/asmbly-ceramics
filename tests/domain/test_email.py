from collections.abc import Callable
from datetime import datetime, timedelta

import pytest

from asmbly_ceramics.domain import errors
from asmbly_ceramics.domain.dropoff import DropOffState, reject, undo_rejection
from asmbly_ceramics.domain.email import (
    ERROR_CODE_MAX,
    Email,
    EmailKind,
    EmailStatus,
    claim,
    is_history,
    is_rejection_occasion,
    is_still_rejected,
    mark_cancelled,
    mark_failed,
    mark_sent,
    needs_attention,
    new_email,
    rejection_occasion,
    retry,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.limits import STALE_SENDING_AFTER, STUDIO_TZ
from asmbly_ceramics.domain.studio import CatalogList
from tests.domain.builders import NOW, STAFF, a_drop_off, a_studio

AC12 = DropOffId(12)


def pending() -> Email:
    return new_email(AC12, EmailKind.RECEIVED, NOW)


def sending() -> Email:
    return claim(pending(), NOW)


def failed() -> Email:
    return mark_failed(sending(), "Throttling")


def sent() -> Email:
    return mark_sent(sending(), NOW)


def cancelled() -> Email:
    return mark_cancelled(pending())


def test_a_new_email_is_pending() -> None:
    email = pending()
    assert (email.status, email.attempts, email.occasion, email.version) == (EmailStatus.PENDING, 0, "", 0)
    assert email.created_at == NOW


def test_a_rejected_email_needs_an_occasion_and_the_others_have_none() -> None:
    occasion = rejection_occasion(NOW)
    assert new_email(AC12, EmailKind.REJECTED, NOW, occasion).occasion == occasion
    with pytest.raises(ValueError, match="occasion"):
        new_email(AC12, EmailKind.REJECTED, NOW)
    with pytest.raises(ValueError, match="occasion"):
        new_email(AC12, EmailKind.READY, NOW, occasion)


def test_the_occasion_is_utc_to_the_microsecond() -> None:
    assert rejection_occasion(NOW) == "2026-11-13T18:30:00.000000+00:00"
    in_austin = NOW.astimezone(STUDIO_TZ).replace(microsecond=7)
    assert rejection_occasion(in_austin) == "2026-11-13T18:30:00.000007+00:00"
    with pytest.raises(ValueError, match="aware"):
        rejection_occasion(datetime(2026, 11, 13, 12))  # noqa: DTZ001


def test_the_occasion_survives_a_round_trip_through_another_offset_or_precision() -> None:
    # A store may give the time back in another offset, or drop zero microseconds.
    occasion = rejection_occasion(NOW)
    read_back = datetime.fromisoformat(NOW.astimezone(STUDIO_TZ).isoformat(timespec="seconds"))
    assert rejection_occasion(read_back) == occasion
    assert rejection_occasion(datetime.fromisoformat(occasion)) == occasion


@pytest.mark.parametrize(
    "occasion",
    [
        NOW.isoformat(),  # no microseconds
        NOW.astimezone(STUDIO_TZ).isoformat(timespec="microseconds"),  # not UTC
        "2026-11-13T18:30:00.000000",  # naive
        "2026-11-13T18:30:00.000000Z",
        "yesterday",
    ],
)
def test_a_rejected_email_refuses_any_other_occasion_format(occasion: str) -> None:
    assert not is_rejection_occasion(occasion)
    with pytest.raises(ValueError, match="occasion"):
        new_email(AC12, EmailKind.REJECTED, NOW, occasion)


def test_is_still_rejected_only_by_the_same_rejection() -> None:
    reason = a_studio().item(CatalogList.REASONS, ItemId("has-glaze-issues"))
    rejected = reject(a_drop_off(), reason, "", STAFF, NOW)
    occasion = rejection_occasion(NOW.astimezone(STUDIO_TZ))  # however the caller held the time
    assert is_still_rejected(rejected, occasion)
    waiting = undo_rejection(rejected, NOW + timedelta(minutes=5))
    assert not is_still_rejected(waiting, occasion)
    again = reject(waiting, reason, "", STAFF, NOW + timedelta(minutes=10))
    assert not is_still_rejected(again, occasion)
    assert is_still_rejected(again, rejection_occasion(NOW + timedelta(minutes=10)))
    assert not is_still_rejected(a_drop_off(state=DropOffState.CLOSED), occasion)


def test_an_email_needs_aware_times() -> None:
    naive = datetime(2026, 11, 13, 12)  # noqa: DTZ001
    with pytest.raises(ValueError, match="aware"):
        new_email(AC12, EmailKind.READY, naive)
    with pytest.raises(ValueError, match="aware"):
        claim(pending(), naive)
    with pytest.raises(ValueError, match="aware"):
        mark_sent(sending(), naive)
    # A failed email needs no clock to be retried or shown, but a naive time is still a bug.
    for make in (failed, sending, pending):
        with pytest.raises(ValueError, match="aware"):
            retry(make(), naive)
        with pytest.raises(ValueError, match="aware"):
            needs_attention(make(), naive)


def test_email_moves_pending_sending_sent() -> None:
    claimed = claim(pending(), NOW)
    assert (claimed.status, claimed.attempts, claimed.claimed_at) == (EmailStatus.SENDING, 1, NOW)
    later = NOW + timedelta(seconds=3)
    done = mark_sent(claimed, later)
    assert (done.status, done.sent_at, done.error_code) == (EmailStatus.SENT, later, None)


def test_email_moves_pending_sending_failed_with_its_code() -> None:
    email = mark_failed(sending(), "MessageRejected")
    assert (email.status, email.error_code, email.sent_at) == (EmailStatus.FAILED, "MessageRejected", None)


@pytest.mark.parametrize(
    "code",
    [
        "",
        "Email address is not verified",  # spaces: a message, not a code
        "Bad<code>",
        "Code\nInjected",
        "x" * (ERROR_CODE_MAX + 1),
        "Thröttling",
    ],
)
def test_an_error_code_with_other_characters_is_refused(code: str) -> None:
    with pytest.raises(ValueError, match="code"):
        mark_failed(sending(), code)


def test_the_longest_error_code_is_kept() -> None:
    assert mark_failed(sending(), "x" * ERROR_CODE_MAX).error_code == "x" * ERROR_CODE_MAX


@pytest.mark.parametrize(
    ("move", "make"),
    [
        (lambda e: claim(e, NOW), sending),
        (lambda e: claim(e, NOW), sent),
        (lambda e: claim(e, NOW), failed),
        (lambda e: mark_sent(e, NOW), pending),
        (lambda e: mark_sent(e, NOW), failed),
        (lambda e: mark_failed(e, "Throttling"), pending),
        (lambda e: mark_failed(e, "Throttling"), sent),
    ],
)
def test_a_move_from_a_status_it_doesnt_allow_is_a_bug(
    move: Callable[[Email], Email], make: Callable[[], Email]
) -> None:
    with pytest.raises(ValueError, match=r"AC-12's received email is"):
        move(make())


def test_cancel_from_pending_or_sending_only() -> None:
    assert mark_cancelled(pending()).status is EmailStatus.CANCELLED
    assert mark_cancelled(sending()).status is EmailStatus.CANCELLED
    for make in (sent, failed, cancelled):
        with pytest.raises(ValueError, match="email is"):
            mark_cancelled(make())


def test_retry_a_failed_email() -> None:
    email = retry(failed(), NOW)
    assert (email.status, email.error_code, email.claimed_at, email.attempts) == (
        EmailStatus.PENDING,
        None,
        None,
        1,
    )


def test_retry_only_failed_or_stale_sending() -> None:
    stale_at = NOW + STALE_SENDING_AFTER + timedelta(seconds=1)
    assert retry(sending(), stale_at).status is EmailStatus.PENDING
    for make in (pending, sent, cancelled):
        with pytest.raises(errors.EmailNotRetryable):
            retry(make(), stale_at)
    with pytest.raises(errors.EmailNotRetryable):
        retry(sending(), NOW + STALE_SENDING_AFTER)


def test_needs_attention_after_15_minutes_sending() -> None:
    assert timedelta(minutes=15) == STALE_SENDING_AFTER
    assert not needs_attention(sending(), NOW + timedelta(minutes=15))
    assert needs_attention(sending(), NOW + timedelta(minutes=15, seconds=1))
    assert needs_attention(failed(), NOW)
    for make in (pending, sent, cancelled):
        assert not needs_attention(make(), NOW + timedelta(days=1))


def test_is_history_for_a_closed_drop_off_or_an_undone_rejection() -> None:
    received = new_email(DropOffId(1), EmailKind.RECEIVED, NOW)
    rejected_drop_off = a_drop_off(1, DropOffState.REJECTED)
    assert rejected_drop_off.rejection is not None
    current = new_email(
        DropOffId(1), EmailKind.REJECTED, NOW, rejection_occasion(rejected_drop_off.rejection.at)
    )
    stale = new_email(DropOffId(1), EmailKind.REJECTED, NOW, rejection_occasion(NOW - timedelta(hours=1)))

    assert is_history(a_drop_off(1, DropOffState.CLOSED), received)
    assert not is_history(a_drop_off(1, DropOffState.FIRED), received)
    assert not is_history(rejected_drop_off, current)
    assert is_history(rejected_drop_off, stale)
    assert is_history(a_drop_off(1), current)  # waiting again: the rejection was undone
