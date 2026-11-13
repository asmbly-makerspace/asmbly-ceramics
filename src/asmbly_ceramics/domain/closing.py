"""Closing a finished drop-off: delete the person's details, keep the rest."""

from dataclasses import replace
from datetime import datetime, timedelta

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState


def is_closable(
    drop_off: DropOff, ready_sent_at: datetime | None, pickup_window_days: int, now: datetime
) -> bool:
    window = timedelta(days=pickup_window_days)
    if drop_off.state is DropOffState.FIRED:
        return ready_sent_at is not None and ready_sent_at + window <= now
    if drop_off.state is DropOffState.REJECTED and drop_off.rejection is not None:
        return drop_off.rejection.at + window <= now
    return False


def close(drop_off: DropOff, at: datetime) -> DropOff:
    if drop_off.state not in (DropOffState.FIRED, DropOffState.REJECTED):
        raise ValueError(f"{drop_off.id} can't be closed from {drop_off.state}.")
    rejection = replace(drop_off.rejection, message=None) if drop_off.rejection is not None else None
    return replace(
        drop_off, state=DropOffState.CLOSED, contact=None, photos=(), rejection=rejection, closed_at=at
    )
