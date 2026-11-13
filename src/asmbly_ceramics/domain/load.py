"""A kiln load: loading, firing, fired."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, new_email
from asmbly_ceramics.domain.errors import (
    AlreadyFired,
    AlreadyInLoad,
    EmptyLoad,
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
    date: date
    status: LoadStatus
    members: tuple[DropOffId, ...]
    started_by: str
    started_at: datetime
    fired_at: datetime | None = None
    version: int = 0


@dataclass(frozen=True, slots=True)
class FireResult:
    load: Load
    drop_offs: tuple[DropOff, ...]
    emails: tuple[Email, ...]


def _check_choices(kiln: ItemId, firing_type: ItemId, studio: Studio) -> None:
    studio.active_item(CatalogList.KILNS, kiln)
    studio.active_item(CatalogList.FIRING_TYPES, firing_type)


def _must_be_loading(load: Load) -> None:
    if load.status is not LoadStatus.LOADING:
        raise LoadNotLoading(f"Load {load.id} is {load.status}: nothing can be added or removed.")


def start_load(
    id: LoadId, kiln: ItemId, firing_type: ItemId, on: date, by: str, at: datetime, studio: Studio
) -> Load:
    _check_choices(kiln, firing_type, studio)
    return Load(id, kiln, firing_type, on, LoadStatus.LOADING, (), by, at)


def change_load(load: Load, kiln: ItemId, firing_type: ItemId, on: date, studio: Studio) -> Load:
    if load.status is not LoadStatus.LOADING:
        raise LoadNotLoading(f"Load {load.id} is {load.status}: it can't be changed.")
    _check_choices(kiln, firing_type, studio)
    return replace(load, kiln=kiln, firing_type=firing_type, date=on)


def add_to_load(load: Load, drop_off: DropOff, *, confirmed: bool) -> tuple[Load, DropOff]:
    _must_be_loading(load)
    if drop_off.state is DropOffState.IN_LOAD:
        raise AlreadyInLoad(f"{drop_off.id} is already in load {drop_off.load_id}.")
    if drop_off.state is not DropOffState.WAITING:
        raise NotWaiting(f"{drop_off.id} isn't waiting: it is {drop_off.state.value.replace('_', ' ')}.")
    if len(load.members) >= LOAD_CAPACITY:
        raise LoadFull(f"Load {load.id} already holds {LOAD_CAPACITY} drop-offs.")
    if drop_off.firing_type != load.firing_type and not confirmed:
        raise FiringTypeMismatch(
            f"{drop_off.id} is {drop_off.firing_type}. Load {load.id} is {load.firing_type}.", drop_off.id
        )
    return (
        replace(load, members=(*load.members, drop_off.id)),
        replace(drop_off, state=DropOffState.IN_LOAD, load_id=load.id),
    )


def remove_from_load(load: Load, drop_off: DropOff) -> tuple[Load, DropOff]:
    _must_be_loading(load)
    if drop_off.id not in load.members or drop_off.load_id != load.id:
        raise NotInLoad(f"{drop_off.id} isn't in load {load.id}.")
    return (
        replace(load, members=tuple(m for m in load.members if m != drop_off.id)),
        replace(drop_off, state=DropOffState.WAITING, load_id=None),
    )


def start_firing(load: Load) -> Load:
    if load.status is not LoadStatus.LOADING:
        raise WrongLoadStatus(f"Load {load.id} is {load.status}, not loading.")
    if not load.members:
        raise EmptyLoad(f"Load {load.id} is empty: add a drop-off before firing.")
    return replace(load, status=LoadStatus.FIRING)


def fire(load: Load, members: Sequence[DropOff], at: datetime) -> FireResult:
    if load.status is LoadStatus.FIRED:
        raise AlreadyFired(f"Load {load.id} is already fired; nothing was sent again.")
    if load.status is not LoadStatus.FIRING:
        raise WrongLoadStatus(f"Load {load.id} is {load.status}, not firing.")
    if sorted(m.id for m in members) != sorted(load.members) or any(
        m.state is not DropOffState.IN_LOAD or m.load_id != load.id for m in members
    ):
        raise ValueError("The members given are not exactly the load's members, in this load.")
    fired = tuple(replace(m, state=DropOffState.FIRED, fired_at=at) for m in members)
    emails = tuple(new_email(m.id, EmailKind.READY, at) for m in fired)
    return FireResult(replace(load, status=LoadStatus.FIRED, fired_at=at), fired, emails)
