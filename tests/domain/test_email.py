from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from asmbly_ceramics.domain import errors
from asmbly_ceramics.domain.dropoff import DropOffState, reject, undo_rejection
from asmbly_ceramics.domain.email import (
    ERROR_CODE_MAX,
    Email,
    EmailKind,
    EmailStatus,
    cancel_unsent,
    claim,
    holds_claim,
    is_email_occasion,
    is_history,
    is_rejection_occasion,
    is_still_rejected,
    mark_cancelled,
    mark_failed,
    mark_sent,
    needs_acting_on,
    needs_attention,
    new_email,
    rejection_occasion,
    retry,
    stuck_since,
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


@pytest.mark.parametrize("kind", list(EmailKind))
def test_is_email_occasion_is_the_rule_new_email_applies(kind: EmailKind) -> None:
    for occasion in ("", rejection_occasion(NOW), "yesterday"):
        try:
            new_email(AC12, kind, NOW, occasion)
        except ValueError:
            made = False
        else:
            made = True
        assert is_email_occasion(kind, occasion) is made


def test_only_a_rejected_email_has_an_occasion() -> None:
    occasion = rejection_occasion(NOW)
    assert is_email_occasion(EmailKind.REJECTED, occasion)
    assert not is_email_occasion(EmailKind.REJECTED, "")
    assert not is_email_occasion(EmailKind.REJECTED, "yesterday")
    assert is_email_occasion(EmailKind.RECEIVED, "")
    assert not is_email_occasion(EmailKind.READY, occasion)


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


def test_cancel_unsent_cancels_pending_sending_and_failed_only() -> None:
    for make in (pending, sending, failed):
        assert cancel_unsent(make()).status is EmailStatus.CANCELLED
    for make in (sent, cancelled):
        with pytest.raises(ValueError, match="email is"):
            cancel_unsent(make())


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


def test_retry_only_failed_or_stuck() -> None:
    stale_at = NOW + STALE_SENDING_AFTER + timedelta(seconds=1)
    assert retry(sending(), stale_at).status is EmailStatus.PENDING
    for make in (sent, cancelled):
        with pytest.raises(errors.EmailNotRetryable):
            retry(make(), stale_at)
    for make in (sending, pending):
        with pytest.raises(errors.EmailNotRetryable):
            retry(make(), NOW + STALE_SENDING_AFTER)


def test_a_pending_email_the_stream_gave_up_on_needs_attention_and_can_be_retried() -> None:
    stale_at = NOW + STALE_SENDING_AFTER + timedelta(seconds=1)
    assert needs_attention(pending(), stale_at)
    requeued = retry(pending(), stale_at)
    assert (requeued.status, requeued.retried_at) == (EmailStatus.PENDING, stale_at)
    # Queued again: it waits from the retry, not from when it was first queued.
    assert not needs_attention(requeued, stale_at + STALE_SENDING_AFTER)
    assert needs_attention(requeued, stale_at + STALE_SENDING_AFTER + timedelta(seconds=1))


def test_needs_attention_after_15_minutes_sending() -> None:
    assert timedelta(minutes=15) == STALE_SENDING_AFTER
    assert not needs_attention(sending(), NOW + timedelta(minutes=15))
    assert needs_attention(sending(), NOW + timedelta(minutes=15, seconds=1))
    assert needs_attention(failed(), NOW)
    assert not needs_attention(pending(), NOW + timedelta(minutes=15))
    for make in (sent, cancelled):
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
    assert is_history(a_drop_off(1, DropOffState.DELETED), received)  # its address is gone too
    assert not is_history(a_drop_off(1, DropOffState.FIRED), received)
    assert not is_history(rejected_drop_off, current)
    assert is_history(rejected_drop_off, stale)
    assert is_history(a_drop_off(1), current)  # waiting again: the rejection was undone


def test_a_sent_ready_email_keeps_the_pickup_window_it_gave() -> None:
    ready = claim(new_email(AC12, EmailKind.READY, NOW), NOW)
    done = mark_sent(ready, NOW, pickup_window_days=14)
    assert (done.status, done.sent_at, done.pickup_window_days) == (EmailStatus.SENT, NOW, 14)
    for missing in (None, 0):
        with pytest.raises(ValueError, match="pickup window"):
            mark_sent(ready, NOW, pickup_window_days=missing)


def test_only_a_ready_email_gives_a_pickup_window() -> None:
    with pytest.raises(ValueError, match="only a ready email"):
        mark_sent(sending(), NOW, pickup_window_days=14)
    assert sent().pickup_window_days is None


def test_needs_acting_on_leaves_out_history() -> None:
    stale = NOW + STALE_SENDING_AFTER + timedelta(seconds=1)
    failed_email = failed()
    assert needs_acting_on(a_drop_off(12), failed_email, NOW)
    assert not needs_acting_on(a_drop_off(12, DropOffState.CLOSED), failed_email, NOW)
    assert needs_acting_on(a_drop_off(12), sending(), stale)
    assert not needs_acting_on(a_drop_off(12), sending(), NOW)


def test_a_sending_email_without_its_claim_time_shows_as_stuck() -> None:
    assert needs_attention(replace(sending(), claimed_at=None), NOW)


def test_stuck_since_is_when_the_wait_that_goes_stale_began() -> None:
    later = NOW + timedelta(hours=1)
    assert stuck_since(pending()) == NOW
    assert stuck_since(retry(failed(), later)) == later
    assert stuck_since(claim(pending(), later)) == later
    assert stuck_since(replace(sending(), claimed_at=None)) is None
    assert stuck_since(failed()) is None
    assert stuck_since(sent()) is None


def test_needs_attention_counts_from_stuck_since() -> None:
    requeued = retry(failed(), NOW + timedelta(hours=1))
    since = stuck_since(requeued)
    assert since is not None
    assert not needs_attention(requeued, since + STALE_SENDING_AFTER)
    assert needs_attention(requeued, since + STALE_SENDING_AFTER + timedelta(seconds=1))


def stored(email: Email) -> Email:
    """`email` as `Records` stores it: one version up."""
    return replace(email, version=email.version + 1)


def test_holds_claim_when_the_stored_email_is_this_claim() -> None:
    claimed = claim(pending(), NOW)
    assert holds_claim(stored(claimed), claimed)


def test_holds_claim_is_false_for_a_pending_email() -> None:
    assert not holds_claim(pending(), claim(pending(), NOW))


def test_holds_claim_is_false_for_none() -> None:
    assert not holds_claim(None, claim(pending(), NOW))


def test_holds_claim_is_false_for_another_calls_claim() -> None:
    claimed = claim(pending(), NOW)
    other = claim(pending(), NOW + timedelta(microseconds=1))
    assert not holds_claim(stored(other), claimed)


def test_holds_claim_is_false_for_a_later_attempt() -> None:
    claimed = claim(pending(), NOW)
    again = claim(retry(mark_failed(claimed, "Throttling"), NOW), NOW)  # the same time, one more attempt
    assert again.claimed_at == claimed.claimed_at
    assert not holds_claim(stored(again), claimed)


@pytest.mark.parametrize("finished", [sent, failed, cancelled])
def test_holds_claim_is_false_for_a_sent_failed_or_cancelled_email(finished: Callable[[], Email]) -> None:
    assert not holds_claim(stored(finished()), claim(pending(), NOW))


def test_holds_claim_is_false_when_the_claim_isnt_a_claim() -> None:
    assert not holds_claim(stored(sending()), pending())
