"""Closing a finished drop-off, which deletes the person's details (#7).

The pickup window counts from the ready email for a fired drop-off (epic #1) and from
the rejected email for a rejected one (#20), once that email is sent. Closing keeps
what the weekly counts need (the ID, dates, firing type, glaze type, pieces, load and
reason) and drops the name, email, phone, the rejection's message and the photos'
refs; the caller deletes the photos themselves through the `PhotoStore` port in the
same run.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus, rejection_occasion
from asmbly_ceramics.domain.limits import STUDIO_TZ, UNSENT_EMAIL_CLOSE_AFTER


def pickup_day(start: datetime, pickup_window_days: int) -> date:
    """The last Austin day of the pickup window that started at `start`: Austin's date
    at `start` plus `pickup_window_days` calendar days. The ready email's "Pick up by"."""
    _check_aware(start)
    if pickup_window_days < 1:
        raise ValueError("the pickup window is at least a day")
    return start.astimezone(STUDIO_TZ).date() + timedelta(days=pickup_window_days)


def pickup_deadline(start: datetime, pickup_window_days: int) -> datetime:
    """When the pickup window that started at `start` ends: the start of the Austin day
    after `pickup_day`, so the whole day the email names is the person's, whatever the
    time of day it went out and across a change of daylight saving time. An aware time;
    the same `start` in any zone gives the same instant. (Midnight is never skipped or
    repeated in Austin: the clocks change at 2 AM.)"""
    following = pickup_day(start, pickup_window_days) + timedelta(days=1)
    return datetime.combine(following, time(0), tzinfo=STUDIO_TZ)


def _window_passed(start: datetime, pickup_window_days: int, now: datetime) -> bool:
    """Whether the pickup window that started at `start` has passed (`pickup_deadline`,
    the end of the Austin day it names)."""
    _check_aware(now)
    return pickup_deadline(start, pickup_window_days) <= now


def _unsent_limit_passed(since: datetime | None, what: str, drop_off: DropOff, now: datetime) -> bool:
    """Whether `UNSENT_EMAIL_CLOSE_AFTER` has passed since the firing or the rejection,
    for a drop-off whose email hasn't gone (failed, or stuck sending or pending) (#20)."""
    if since is None:
        raise ValueError(f"{drop_off.id} has no {what} time")
    _check_aware(now)
    _check_aware(since)
    return since + UNSENT_EMAIL_CLOSE_AFTER <= now


def is_due_to_close(drop_off: DropOff, email: Email | None, studio_window_days: int, now: datetime) -> bool:
    """The close's whole rule (#7, #20). `email` is the drop-off's ready email when it is
    fired, and the rejected email of its current rejection when it is rejected; any other
    drop-off never closes and `email` is ignored.

    The pickup window starts when that email is sent, so the person is told before their
    details are deleted. A fired drop-off counts with the window its ready email gave
    (kept with it), never the studio's later setting; a rejected one, whose email names no
    date, with the studio's window. While the email hasn't gone (failed, or stuck sending
    or pending) there is no window, and the console shows it for staff to send again; the
    drop-off still closes `UNSENT_EMAIL_CLOSE_AFTER` after its firing or rejection, so the
    person's details are never kept without an end.

    `ValueError` for a broken record, which the close reports rather than skip silently: a
    fired drop-off with no ready email or no firing time, a rejected one with no rejection
    or no rejected email, an email of another drop-off or rejection, a sent email without
    its time or (ready) its window."""
    _check_aware(now)
    if studio_window_days < 1:
        raise ValueError("the pickup window is at least a day")
    if drop_off.state in (DropOffState.WAITING, DropOffState.IN_LOAD, DropOffState.CLOSED):
        return False
    if drop_off.state is DropOffState.FIRED:
        if email is None:
            raise ValueError(f"{drop_off.id} is fired with no ready email")  # firing queues one
        if email.status is not EmailStatus.SENT:
            return _unsent_limit_passed(drop_off.fired_at, "firing", drop_off, now)
        if email.kind is not EmailKind.READY or email.drop_off_id != drop_off.id:
            raise ValueError(f"that isn't {drop_off.id}'s ready email")
        if email.sent_at is None or email.pickup_window_days is None:
            raise ValueError(f"{drop_off.id}'s sent ready email has no pickup window")
        return _window_passed(email.sent_at, email.pickup_window_days, now)
    # Rejected: the only state left.
    rejection = drop_off.rejection
    if rejection is None:
        raise ValueError(f"{drop_off.id} is rejected with no rejection")
    if email is None:
        raise ValueError(f"{drop_off.id} is rejected with no rejected email")  # rejecting queues one
    if (
        email.kind is not EmailKind.REJECTED
        or email.drop_off_id != drop_off.id
        or email.occasion != rejection_occasion(rejection.at)
    ):
        raise ValueError(f"that isn't the rejected email of {drop_off.id}'s rejection")
    if email.status is not EmailStatus.SENT:
        return _unsent_limit_passed(rejection.at, "rejection", drop_off, now)
    if email.sent_at is None:
        raise ValueError(f"{drop_off.id}'s sent rejected email has no time")
    return _window_passed(email.sent_at, studio_window_days, now)


def close(drop_off: DropOff, at: datetime) -> DropOff:
    """A fired or rejected drop-off, closed: its personal details and photo refs gone."""
    _check_aware(at)
    if drop_off.state not in (DropOffState.FIRED, DropOffState.REJECTED):
        raise ValueError(f"{drop_off.id} is {drop_off.state.label}: only a fired or rejected drop-off closes")
    rejection = replace(drop_off.rejection, message=None) if drop_off.rejection is not None else None
    return replace(
        drop_off, state=DropOffState.CLOSED, contact=None, photos=(), rejection=rejection, closed_at=at
    )


def _check_aware(at: datetime) -> None:
    if at.utcoffset() is None:
        raise ValueError("closing needs an aware time")
