"""Closing a finished drop-off, which deletes the person's details (#7).

The pickup window counts from the ready email for a fired drop-off (epic #1) and from
the rejection for a rejected one. Closing keeps what the weekly counts need (the ID,
dates, firing type, glaze type, pieces, load and reason) and drops the name, email,
phone, the rejection's message and the photos' refs; the caller deletes the photos
themselves through the `PhotoStore` port in the same run.
"""

from dataclasses import replace
from datetime import datetime, timedelta

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState


def is_closable(
    drop_off: DropOff, ready_sent_at: datetime | None, pickup_window_days: int, now: datetime
) -> bool:
    """Whether the pickup window has passed. A fired drop-off whose ready email never went
    out never closes: the console shows the failed email instead."""
    _check_aware(now)
    if ready_sent_at is not None:
        _check_aware(ready_sent_at)
    if pickup_window_days < 1:
        raise ValueError("the pickup window is at least a day")
    window = timedelta(days=pickup_window_days)
    match drop_off.state:
        case DropOffState.FIRED:
            return ready_sent_at is not None and ready_sent_at + window <= now
        case DropOffState.REJECTED:
            return drop_off.rejection is not None and drop_off.rejection.at + window <= now
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
