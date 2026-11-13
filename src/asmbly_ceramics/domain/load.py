"""A kiln load (story #4): `loading → firing → fired`.

Drop-offs are added and removed only while the load is loading; a fired load and its
drop-offs never change. A load holds at most `LOAD_CAPACITY` drop-offs, because firing
commits the load, each drop-off and each ready email in one transaction (decision 0002).
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, new_email
from asmbly_ceramics.domain.errors import (
    AlreadyFired,
    AlreadyInLoad,
    EmptyLoad,
    FiringTypeLocked,
    FiringTypeMismatch,
    LoadFull,
    LoadNotLoading,
    NotInLoad,
    NotWaiting,
    WrongLoadStatus,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import LOAD_CAPACITY
from asmbly_ceramics.domain.studio import CatalogList, Studio


class LoadStatus(StrEnum):
    LOADING = "loading"
    FIRING = "firing"
    FIRED = "fired"


@dataclass(frozen=True, slots=True)
class Load:
    id: LoadId
    kiln: ItemId
    firing_type: ItemId
    date: dt.date
    status: LoadStatus
    members: tuple[DropOffId, ...]
    started_by: str  # staff username
    started_at: dt.datetime
    fired_at: dt.datetime | None = None
    version: int = 0


@dataclass(frozen=True, slots=True)
class FireResult:
    load: Load
    drop_offs: tuple[DropOff, ...]  # in the load's `members` order
    emails: tuple[Email, ...]  # one ready email per drop-off


def start_load(
    id: LoadId, kiln: ItemId, firing_type: ItemId, on: dt.date, by: str, at: dt.datetime, studio: Studio
) -> Load:
    """A new, empty load. The kiln and the firing type must be active items."""
    _check_aware(at)
    if not by:
        raise ValueError("a load needs the staff username")
    studio.active_item(CatalogList.KILNS, kiln)
    studio.active_item(CatalogList.FIRING_TYPES, firing_type)
    return Load(
        id=id,
        kiln=kiln,
        firing_type=firing_type,
        date=on,
        status=LoadStatus.LOADING,
        members=(),
        started_by=by,
        started_at=at,
    )


def change_load(load: Load, kiln: ItemId, firing_type: ItemId, on: dt.date, studio: Studio) -> Load:
    """Change a loading load's kiln, firing type or date.

    Only what changes is checked: a new kiln or firing type must be an active item, and
    keeping a kiln retired since the load was started doesn't block a date change. The
    firing type of a load with drop-offs in it can't change (`FiringTypeLocked`): each
    was added, and any different one confirmed, against the firing type it has (#4).
    """
    _require_loading(load)
    if firing_type != load.firing_type:
        if load.members:
            raise FiringTypeLocked(load.id)
        studio.active_item(CatalogList.FIRING_TYPES, firing_type)
    if kiln != load.kiln:
        studio.active_item(CatalogList.KILNS, kiln)
    return replace(load, kiln=kiln, firing_type=firing_type, date=on)


def add_to_load(load: Load, drop_off: DropOff, *, confirmed: bool) -> tuple[Load, DropOff]:
    """Add a waiting drop-off. A different firing type from the load's needs `confirmed`."""
    _require_loading(load)
    if drop_off.state is DropOffState.IN_LOAD:
        if drop_off.load_id is None:
            raise ValueError(f"{drop_off.id} is in a load with no load ID")
        raise AlreadyInLoad(drop_off.id, drop_off.load_id)
    if drop_off.state is not DropOffState.WAITING:
        raise NotWaiting(drop_off.id, drop_off.state.label)
    if drop_off.id in load.members:
        raise ValueError(f"{drop_off.id} is waiting but listed in load {load.id}")
    if len(load.members) >= LOAD_CAPACITY:
        raise LoadFull(load.id, LOAD_CAPACITY)
    if drop_off.firing_type != load.firing_type and not confirmed:
        raise FiringTypeMismatch(drop_off.id, drop_off.firing_type, load.firing_type)
    return (
        replace(load, members=(*load.members, drop_off.id)),
        replace(drop_off, state=DropOffState.IN_LOAD, load_id=load.id),
    )


def remove_from_load(load: Load, drop_off: DropOff) -> tuple[Load, DropOff]:
    """Take a drop-off out of a loading load and put it back in the waiting list."""
    _require_loading(load)
    if (
        drop_off.state is not DropOffState.IN_LOAD
        or drop_off.load_id != load.id
        or drop_off.id not in load.members
    ):
        raise NotInLoad(drop_off.id, load.id)
    return (
        replace(load, members=tuple(id for id in load.members if id != drop_off.id)),
        replace(drop_off, state=DropOffState.WAITING, load_id=None),
    )


def start_firing(load: Load) -> Load:
    if load.status is not LoadStatus.LOADING:
        raise WrongLoadStatus(load.id, load.status.value, LoadStatus.LOADING.value)
    if not load.members:
        raise EmptyLoad(load.id)
    return replace(load, status=LoadStatus.FIRING)


def fire(load: Load, members: Sequence[DropOff], at: dt.datetime) -> FireResult:
    """Mark a firing load fired: each member fired, with one ready email each.

    Firing again raises `AlreadyFired` and returns nothing, so nothing is sent twice.
    `members` must be exactly the load's drop-offs, each in this load: anything else is
    a bug in the caller, not a refusal.
    """
    _check_aware(at)
    if load.status is LoadStatus.FIRED:
        raise AlreadyFired(load.id)
    if load.status is not LoadStatus.FIRING:
        raise WrongLoadStatus(load.id, load.status.value, LoadStatus.FIRING.value)
    by_id = {drop_off.id: drop_off for drop_off in members}
    if len(by_id) != len(members) or set(by_id) != set(load.members):
        raise ValueError(f"the drop-offs given aren't exactly load {load.id}'s members")
    for drop_off in members:
        if drop_off.state is not DropOffState.IN_LOAD or drop_off.load_id != load.id:
            raise ValueError(f"{drop_off.id} isn't in load {load.id}")
    fired = tuple(replace(by_id[id], state=DropOffState.FIRED, fired_at=at) for id in load.members)
    return FireResult(
        load=replace(load, status=LoadStatus.FIRED, fired_at=at),
        drop_offs=fired,
        emails=tuple(new_email(drop_off.id, EmailKind.READY, at) for drop_off in fired),
    )


def _require_loading(load: Load) -> None:
    if load.status is not LoadStatus.LOADING:
        raise LoadNotLoading(load.id, load.status.value)


def _check_aware(at: dt.datetime) -> None:
    if at.utcoffset() is None:
        raise ValueError("a load's times are aware")
