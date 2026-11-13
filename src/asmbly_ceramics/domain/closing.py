"""Closing a finished drop-off, which deletes the person's details (#7).

The pickup window counts from the ready email for a fired drop-off (epic #1) and from
the rejection for a rejected one. Closing keeps what the weekly counts need (the ID,
dates, firing type, glaze type, pieces, load and reason) and drops the name, email,
phone, the rejection's message and the photos' refs; the caller deletes the photos
themselves through the `PhotoStore` port in the same run.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.limits import STUDIO_TZ


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


def is_closable(
    drop_off: DropOff, ready_sent_at: datetime | None, pickup_window_days: int, now: datetime
) -> bool:
    """Whether the pickup window has passed (`pickup_deadline`, the end of the Austin day
    the ready email named). For a fired drop-off, `pickup_window_days` is the window its
    ready email gave, kept with it, not the studio's later setting. A fired
    drop-off whose ready email never went out never closes: the console shows the failed
    email instead."""
    _check_aware(now)
    if ready_sent_at is not None:
        _check_aware(ready_sent_at)
    if pickup_window_days < 1:
        raise ValueError("the pickup window is at least a day")
    match drop_off.state:
        case DropOffState.FIRED:
            return ready_sent_at is not None and pickup_deadline(ready_sent_at, pickup_window_days) <= now
        case DropOffState.REJECTED:
            rejection = drop_off.rejection
            return rejection is not None and pickup_deadline(rejection.at, pickup_window_days) <= now
        case DropOffState.WAITING | DropOffState.IN_LOAD | DropOffState.CLOSED:
            return False


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
