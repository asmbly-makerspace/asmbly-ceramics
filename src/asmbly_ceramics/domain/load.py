"""A kiln load (story #4): `loading → firing → fired`, or `deleted` from loading or firing.

A load records who moved it from step to step and when (#42), may be a test firing, and
carries an optional firing record (`domain.firing`) that can change at any live status
without touching its drop-offs. A test load can start firing and be fired with no
drop-offs in it; any other load needs one.

Drop-offs are added and removed only while the load is loading; a fired load's contents
and its drop-offs never change. A load started by mistake can be deleted while it is
loading or firing: its drop-offs go back to waiting, and the load is kept, marked
deleted with who deleted it and when, but no list or page shows it again. A load holds
at most `LOAD_CAPACITY` drop-offs, because firing commits the load, each drop-off and
each ready email in one transaction (decision 0002).
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
    FiredLoadNotDeletable,
    FiringTypeLocked,
    FiringTypeMismatch,
    LoadFull,
    LoadNotLoading,
    NotFound,
    NotInLoad,
    NotWaiting,
    StepNotReached,
    StepTimeInFuture,
    StepTimeOutOfOrder,
    StepTimeTooEarly,
    WrongLoadStatus,
)
from asmbly_ceramics.domain.firing import EMPTY_RECORD, FiringRecord, Program
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import (
    FIRING_NUMBER_MAX,
    LOAD_CAPACITY,
    NUMBERS_DATE_MARGIN,
    NUMBERS_LOOKBACK,
    NUMBERS_READ_AHEAD,
    STEP_TIME_YEAR_MIN,
    STUDIO_TZ,
)
from asmbly_ceramics.domain.studio import CatalogList, KilnCounts, Studio


class LoadStatus(StrEnum):
    LOADING = "loading"
    FIRING = "firing"
    FIRED = "fired"
    DELETED = "deleted"


LIVE_STATUSES = frozenset({LoadStatus.LOADING, LoadStatus.FIRING, LoadStatus.FIRED})
"""Every status but `DELETED`: a deleted load uses no kiln or firing type and is listed nowhere."""


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
    deleted_by: str | None = None  # staff username
    deleted_at: dt.datetime | None = None
    test: bool = False  # a test firing: it may start firing and be fired with no drop-offs
    firing_started_by: str | None = None  # staff username; None on a load made before #42
    firing_started_at: dt.datetime | None = None
    fired_by: str | None = None  # staff username; None on a load made before #42
    record: FiringRecord = EMPTY_RECORD
    version: int = 0


class Step(StrEnum):
    """A step of the load page's status steps, each reached at a time (#42)."""

    STARTED = "started"
    FIRING = "firing"
    FIRED = "fired"


@dataclass(frozen=True, slots=True)
class FireResult:
    load: Load
    drop_offs: tuple[DropOff, ...]  # in the load's `members` order
    emails: tuple[Email, ...]  # one ready email per drop-off


def start_load(
    id: LoadId,
    kiln: ItemId,
    firing_type: ItemId,
    on: dt.date,
    by: str,
    at: dt.datetime,
    studio: Studio,
    *,
    test: bool = False,
) -> Load:
    """A new, empty load, a test firing or not. The kiln and the firing type must be
    active items. Its record starts with the firing type's default program, if it has one
    (#42)."""
    _check_aware(at)
    if not by:
        raise ValueError("a load needs the staff username")
    studio.active_item(CatalogList.KILNS, kiln)
    default = studio.active_item(CatalogList.FIRING_TYPES, firing_type).default_program
    return Load(
        id=id,
        kiln=kiln,
        firing_type=firing_type,
        date=on,
        status=LoadStatus.LOADING,
        members=(),
        started_by=by,
        started_at=at,
        test=test,
        record=EMPTY_RECORD if default is None else FiringRecord(program=default),
    )


def change_load(
    load: Load, kiln: ItemId, firing_type: ItemId, on: dt.date, studio: Studio, *, test: bool
) -> Load:
    """Change a loading load's kiln, firing type, date or whether it is a test.

    Only while loading: once a load starts firing, none of them can change (#42).

    Only what changes is checked: a new kiln or firing type must be an active item, and
    keeping a kiln retired since the load was started doesn't block a date change. The
    firing type of a load with drop-offs in it can't change (`FiringTypeLocked`): each
    was added, and any different one confirmed, against the firing type it has (#4).

    A new firing type swaps in its default program when the load's program is still the
    old firing type's default, or empty; a program staff changed is kept (#42).
    """
    require_loading(load)
    record = load.record
    if firing_type != load.firing_type:
        if firing_type_locked(load):
            raise FiringTypeLocked(load.id)
        new_default = studio.active_item(CatalogList.FIRING_TYPES, firing_type).default_program
        if record.program in (Program(), _default_program(studio, load.firing_type)):
            record = replace(record, program=new_default or Program())
    if kiln != load.kiln:
        studio.active_item(CatalogList.KILNS, kiln)
    return replace(load, kiln=kiln, firing_type=firing_type, date=on, test=test, record=record)


def _default_program(studio: Studio, firing_type: ItemId) -> Program:
    """The firing type's default program, empty if it has none or was deleted."""
    for item in studio.firing_types:
        if item.id == firing_type:
            return item.default_program or Program()
    return Program()


def suggest_numbers(counts: KilnCounts | None, fired: Sequence[Load]) -> tuple[int | None, int | None]:
    """(firing number, all-time number) to suggest for a kiln's next firing (#42).

    `fired` is the kiln's fired loads (the caller picks them). Each number is the latest
    of those, by `fired_at`, that was fired after `counts.as_of` and holds that number,
    plus 1; else that count plus 1; else None (no counts and no numbered firing: the page
    leaves the field blank). Never more than `FIRING_NUMBER_MAX`. It lives here, not in
    `domain.firing`, which `Load` imports.
    """
    after = sorted(
        (
            (load.fired_at, load)
            for load in fired
            if load.status is LoadStatus.FIRED
            and load.fired_at is not None
            and (counts is None or load.fired_at > counts.as_of)
        ),
        key=lambda pair: pair[0],
    )
    latest = [load.record for _, load in reversed(after)]
    since = next((r.firing_number for r in latest if r.firing_number is not None), None)
    total = next((r.all_time_number for r in latest if r.all_time_number is not None), None)
    if counts is not None:
        since = counts.since_elements if since is None else since
        total = counts.all_time if total is None else total
    return _next_number(since), _next_number(total)


def numbers_window(counts: KilnCounts | None, at: dt.datetime) -> tuple[dt.date, dt.date]:
    """The load dates to read, half-open, for `suggest_numbers`' fired loads (#42) when
    numbering a firing at `at` (now, or a fired load's `fired_at`).

    It starts `NUMBERS_LOOKBACK` before `at`'s Austin day, or `NUMBERS_DATE_MARGIN` before
    the counts' Austin day when that is later (a load's date can come well before its
    firing), and ends `NUMBERS_READ_AHEAD` after `at`'s day (a load dated after it may
    already be fired). So the read is bounded by those limits, not by the years kept:
    a load dated outside it isn't read, and a kiln with no numbered firing in the
    lookback gets its counts plus 1 suggested (staff can correct either)."""
    _check_aware(at)
    day = at.astimezone(STUDIO_TZ).date()
    start = day - NUMBERS_LOOKBACK
    if counts is not None:
        start = max(start, counts.as_of.astimezone(STUDIO_TZ).date() - NUMBERS_DATE_MARGIN)
    return start, day + NUMBERS_READ_AHEAD


def _next_number(latest: int | None) -> int | None:
    return None if latest is None else min(latest + 1, FIRING_NUMBER_MAX)


def add_to_load(load: Load, drop_off: DropOff, *, confirmed: bool) -> tuple[Load, DropOff]:
    """Add a waiting drop-off. A different firing type from the load's needs `confirmed`."""
    require_loading(load)
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
    require_loading(load)
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


def start_firing(load: Load, by: str, at: dt.datetime) -> Load:
    """Loading to firing, recording who started the firing and when; `can_start_firing`
    says beforehand whether this refuses. An empty load is refused (`EmptyLoad`) unless
    it is a test."""
    _check_aware(at)
    if not by:
        raise ValueError("starting a firing needs the staff username")
    if not accepts_drop_offs(load):
        raise WrongLoadStatus(load.id, load.status.value, LoadStatus.LOADING.value)
    if not load.members and not load.test:
        raise EmptyLoad(load.id)
    return replace(load, status=LoadStatus.FIRING, firing_started_by=by, firing_started_at=at)


def accepts_drop_offs(load: Load) -> bool:
    """Drop-offs can still be added to or removed from `load` (it is loading)."""
    return load.status is LoadStatus.LOADING


def firing_type_locked(load: Load) -> bool:
    """`change_load` refuses a new firing type (`FiringTypeLocked`): drop-offs are in it."""
    return bool(load.members)


def can_start_firing(load: Load) -> bool:
    """`start_firing` accepts `load`: it is loading and holds a drop-off or is a test."""
    return accepts_drop_offs(load) and (bool(load.members) or load.test)


def fire(load: Load, members: Sequence[DropOff], by: str, at: dt.datetime) -> FireResult:
    """Mark a firing load fired, recording who and when: each member fired, with one
    ready email each. A test load with no drop-offs fires with none and no emails.

    Firing again raises `AlreadyFired` and returns nothing, so nothing is sent twice.
    `members` must be exactly the load's drop-offs, each in this load: anything else is
    a bug in the caller, not a refusal.
    """
    _check_aware(at)
    if not by:
        raise ValueError("marking a load fired needs the staff username")
    require_firing(load)
    by_id = {drop_off.id: drop_off for drop_off in members}
    if len(by_id) != len(members) or set(by_id) != set(load.members):
        raise ValueError(f"the drop-offs given aren't exactly load {load.id}'s members")
    for drop_off in members:
        if drop_off.state is not DropOffState.IN_LOAD or drop_off.load_id != load.id:
            raise ValueError(f"{drop_off.id} isn't in load {load.id}")
    fired = tuple(replace(by_id[id], state=DropOffState.FIRED, fired_at=at) for id in load.members)
    return FireResult(
        load=replace(load, status=LoadStatus.FIRED, fired_at=at, fired_by=by),
        drop_offs=fired,
        emails=tuple(new_email(drop_off.id, EmailKind.READY, at) for drop_off in fired),
    )


def set_firing_record(load: Load, record: FiringRecord) -> Load:
    """The load's firing record replaced, at any live status (loading, firing or fired).
    Its drop-offs never change: a fired load's contents stay as they were (#42).
    `NotFound` on a deleted load."""
    if load.status is LoadStatus.DELETED:
        raise NotFound(load.id)
    return replace(load, record=record)


def step_time(load: Load, step: Step) -> dt.datetime | None:
    """When `load` reached `step`, or None if it hasn't, or a load made before #42 didn't
    record it (the firing step)."""
    match step:
        case Step.STARTED:
            return load.started_at
        case Step.FIRING:
            return load.firing_started_at
        case Step.FIRED:
            return load.fired_at


def can_correct_step(load: Load, step: Step) -> bool:
    """Whether `correct_step_time` accepts a time for `step` at all: the load is live and
    the step has a time (not the firing step of a load made before #42)."""
    return load.status is not LoadStatus.DELETED and step_time(load, step) is not None


def require_correctable(load: Load, step: Step) -> None:
    """`StepNotReached` unless `can_correct_step`: a page asks this for a step it has no
    "Correct time" field to show a refusal by (a stale page)."""
    if not can_correct_step(load, step):
        raise StepNotReached(load.id, step.value)


def correct_step_time(load: Load, step: Step, at: dt.datetime, now: dt.datetime) -> Load:
    """A reached step's time corrected, for a button pressed late (#42).

    `StepNotReached` for a step with no time: not reached yet, or the firing step of a
    load made before #42, so a time is never invented for an unknown step.
    `StepTimeInFuture` when `at` is after `now`, `StepTimeTooEarly` when it is before
    `STEP_TIME_YEAR_MIN` in Austin (a typed year's typo). `StepTimeOutOfOrder` unless started ≤
    firing ≤ fired holds afterwards, among the steps that have a time. `NotFound` on a
    deleted load. Who reached each step never changes.
    """
    _check_aware(at)
    _check_aware(now)
    if load.status is LoadStatus.DELETED:
        raise NotFound(load.id)
    require_correctable(load, step)
    if at > now:
        raise StepTimeInFuture(load.id)
    if at < dt.datetime(STEP_TIME_YEAR_MIN, 1, 1, tzinfo=STUDIO_TZ):
        raise StepTimeTooEarly(load.id, STEP_TIME_YEAR_MIN)
    match step:
        case Step.STARTED:
            corrected = replace(load, started_at=at)
        case Step.FIRING:
            corrected = replace(load, firing_started_at=at)
        case Step.FIRED:
            corrected = replace(load, fired_at=at)
    times = [time for s in Step if (time := step_time(corrected, s)) is not None]
    if times != sorted(times):
        raise StepTimeOutOfOrder(load.id, step.value)
    return corrected


def delete_load(
    load: Load, members: Sequence[DropOff], by: str, at: dt.datetime
) -> tuple[Load, tuple[DropOff, ...]]:
    """Delete a loading or firing load: it is marked deleted and emptied, and each of its
    drop-offs goes back to waiting. A fired load can't be deleted (`FiredLoadNotDeletable`):
    its drop-offs are fired and their ready emails queued. Deleting twice is `NotFound`,
    as a deleted load is gone for every page. `members` must be exactly the load's
    drop-offs, each in this load: anything else is a bug in the caller, not a refusal.
    """
    _check_aware(at)
    if not by:
        raise ValueError("deleting a load needs the staff username")
    require_deletable(load)
    by_id = {drop_off.id: drop_off for drop_off in members}
    if len(by_id) != len(members) or set(by_id) != set(load.members):
        raise ValueError(f"the drop-offs given aren't exactly load {load.id}'s members")
    for drop_off in members:
        if drop_off.state is not DropOffState.IN_LOAD or drop_off.load_id != load.id:
            raise ValueError(f"{drop_off.id} isn't in load {load.id}")
    waiting = tuple(replace(by_id[id], state=DropOffState.WAITING, load_id=None) for id in load.members)
    deleted = replace(load, status=LoadStatus.DELETED, members=(), deleted_by=by, deleted_at=at)
    return deleted, waiting


def can_delete(load: Load) -> bool:
    """`delete_load` accepts `load`: it is loading or firing."""
    return load.status in (LoadStatus.LOADING, LoadStatus.FIRING)


def require_deletable(load: Load) -> None:
    """`FiredLoadNotDeletable` or `NotFound` unless `load` can be deleted now; a page asks
    before it shows "Delete L-4?"."""
    if load.status is LoadStatus.DELETED:
        raise NotFound(load.id)
    if load.status is LoadStatus.FIRED:
        raise FiredLoadNotDeletable(load.id)


def require_loading(load: Load) -> None:
    """`LoadNotLoading` unless drop-offs can still be added to or removed from `load`; a
    page asks before it offers the add field's search."""
    if not accepts_drop_offs(load):
        raise LoadNotLoading(load.id, load.status.value)


def require_firing(load: Load) -> None:
    """`AlreadyFired` or `WrongLoadStatus` unless `load` can be marked fired now; a page
    asks before it shows "Mark L-4 fired?"."""
    if load.status is LoadStatus.FIRED:
        raise AlreadyFired(load.id)
    if load.status is not LoadStatus.FIRING:
        raise WrongLoadStatus(load.id, load.status.value, LoadStatus.FIRING.value)


def _check_aware(at: dt.datetime) -> None:
    if at.utcoffset() is None:
        raise ValueError("a load's times are aware")
