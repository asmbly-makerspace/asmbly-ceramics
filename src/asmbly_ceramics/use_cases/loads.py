"""Building a kiln load and firing it (#4): what the console's load pages call.

Every change reads what it changes (strongly consistent) and commits it in one commit of
`Update`s with the versions read, so two staff acting at once can't both win: the loser
gets `Conflict`. Where the page passes the version it showed, the domain's refusal of a
wrong status comes first, so a second click on "Fired" says `AlreadyFired`, not
`Conflict`. Logs carry load and drop-off IDs and the staff username only.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from types import MappingProxyType

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus, needs_acting_on
from asmbly_ceramics.domain.errors import AlreadyFired, NotFound
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.load import (
    Load,
    LoadStatus,
    add_to_load,
    change_load,
    fire,
    remove_from_load,
    start_firing,
    start_load,
)
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.ids import IdNumbers
from asmbly_ceramics.ports.records import Change, Conflict, Put, Records, Update
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.use_cases.studio import CurrentStudio, item_name
from asmbly_ceramics.use_cases.waiting import WaitingList, WaitingRow

RECENT_LOADS = timedelta(weeks=8)
"""How far back `ListLoads` lists fired loads; older ones stay viewable by their ID."""


def _load(records: Records, id: LoadId) -> Load:
    load = records.load(id)
    if load is None:
        raise NotFound(id)
    return load


def _drop_off(records: Records, id: DropOffId) -> DropOff:
    drop_off = records.drop_off(id)
    if drop_off is None:
        raise NotFound(id)
    return drop_off


def _check_version(load: Load, version: int) -> None:
    """The load is still at the version the staff member saw, else the page reloads."""
    if load.version != version:
        raise Conflict([str(load.id)])


def _stored(load: Load) -> Load:
    """The load as `Records` stores it after the commit: at its version plus one."""
    return replace(load, version=load.version + 1)


class StartLoad:
    def __init__(self, records: Records, ids: IdNumbers, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._ids = ids
        self._clock = clock
        self._studio = studio

    def __call__(self, kiln: ItemId, firing_type: ItemId, on: date | None, staff: StaffMember) -> Load:
        """A new, empty load, dated `on` or today in Austin. `UnknownItem`, `ItemRetired`."""
        studio = self._studio()
        now = self._clock.now()
        # The domain's own checks, asked before a number is spent on a refused load.
        studio.active_item(CatalogList.KILNS, kiln)
        studio.active_item(CatalogList.FIRING_TYPES, firing_type)
        day = on if on is not None else now.astimezone(STUDIO_TZ).date()
        load = start_load(self._ids.next_load_id(), kiln, firing_type, day, staff.username, now, studio)
        self._records.commit([Put(load)])
        log_event("load_started", load_id=str(load.id), user=staff.username)
        return _stored(load)


class ChangeLoad:
    def __init__(self, records: Records, studio: CurrentStudio) -> None:
        self._records = records
        self._studio = studio

    def __call__(
        self, load_id: LoadId, kiln: ItemId, firing_type: ItemId, on: date, version: int, staff: StaffMember
    ) -> Load:
        """ "Change kiln, firing or date", only while loading; the firing type only while
        empty. `NotFound`, `LoadNotLoading`, `FiringTypeLocked`, `UnknownItem`,
        `ItemRetired`, `Conflict`."""
        load = _load(self._records, load_id)
        changed = change_load(load, kiln, firing_type, on, self._studio())
        _check_version(load, version)
        self._records.commit([Update(changed)])
        log_event("load_changed", load_id=str(load.id), user=staff.username)
        return _stored(changed)


class AddToLoad:
    def __init__(self, records: Records) -> None:
        self._records = records

    def __call__(
        self, load_id: LoadId, drop_off_id: DropOffId, *, confirmed: bool, staff: StaffMember
    ) -> Load:
        """Moves a waiting drop-off into the load. `NotFound`, `LoadNotLoading`,
        `AlreadyInLoad`, `NotWaiting`, `LoadFull`, `FiringTypeMismatch` (unless
        `confirmed`: the page asks "Add anyway?"), `Conflict`."""
        load = _load(self._records, load_id)
        drop_off = _drop_off(self._records, drop_off_id)
        new_load, added = add_to_load(load, drop_off, confirmed=confirmed)
        self._records.commit([Update(new_load), Update(added)])
        log_event("added_to_load", load_id=str(load.id), drop_off_id=str(drop_off.id), user=staff.username)
        return _stored(new_load)


class RemoveFromLoad:
    def __init__(self, records: Records) -> None:
        self._records = records

    def __call__(self, load_id: LoadId, drop_off_id: DropOffId, staff: StaffMember) -> Load:
        """Puts the drop-off back in the waiting list. `NotFound`, `LoadNotLoading`,
        `NotInLoad`, `Conflict`."""
        load = _load(self._records, load_id)
        drop_off = _drop_off(self._records, drop_off_id)
        new_load, removed = remove_from_load(load, drop_off)
        self._records.commit([Update(new_load), Update(removed)])
        log_event(
            "removed_from_load", load_id=str(load.id), drop_off_id=str(drop_off.id), user=staff.username
        )
        return _stored(new_load)


class StartFiring:
    def __init__(self, records: Records) -> None:
        self._records = records

    def __call__(self, load_id: LoadId, version: int, staff: StaffMember) -> Load:
        """Loading to firing: nothing can be added or removed after this. `NotFound`,
        `WrongLoadStatus`, `EmptyLoad`, `Conflict`."""
        load = _load(self._records, load_id)
        firing = start_firing(load)
        _check_version(load, version)
        self._records.commit([Update(firing)])
        log_event("load_firing", load_id=str(load.id), user=staff.username)
        return _stored(firing)


class MarkFired:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, load_id: LoadId, version: int, staff: StaffMember) -> Load:
        """Firing to fired: the load, each drop-off fired and one ready email each, in one
        commit (at most 1 + 48 + 48 changes). `AlreadyFired` (nothing is queued again),
        `WrongLoadStatus`, `NotFound`, `Conflict`."""
        load = _load(self._records, load_id)
        members = (
            [_drop_off(self._records, id) for id in load.members]
            if load.status is LoadStatus.FIRING
            else []  # `fire` refuses the status before it looks at members
        )
        # Another "Fired" landed between the load's read and its members': let that one's
        # status answer (`AlreadyFired`). Still firing, no race changes a firing load's
        # members, so `fire` reports the broken record.
        moved = any(d.state is not DropOffState.IN_LOAD or d.load_id != load.id for d in members)
        if moved and _load(self._records, load_id).status is LoadStatus.FIRED:
            raise AlreadyFired(load.id)
        result = fire(load, members, self._clock.now())
        _check_version(load, version)
        changes: list[Change] = [Update(result.load)]
        changes.extend(Update(drop_off) for drop_off in result.drop_offs)
        changes.extend(Put(email) for email in result.emails)
        self._records.commit(changes)
        log_event("load_fired", load_id=str(load.id), count=len(result.drop_offs), user=staff.username)
        return _stored(result.load)


@dataclass(frozen=True, slots=True)
class LoadView:
    load: Load
    kiln: str
    firing_type: str
    members: tuple[DropOff, ...]  # in the order added
    total_drop_offs: int
    total_pieces: int
    emails: Mapping[DropOffId, Email]  # the ready email of each member, once fired
    sent: int  # "11 of 12 emails sent"
    needing_attention: tuple[Email, ...]  # failed, or stuck sending or pending
    waiting: tuple[WaitingRow, ...]  # while loading: waiting drop-offs, by default of the load's firing type


class ViewLoad:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio
        self._waiting = WaitingList(records, clock, studio)

    def __call__(self, load_id: LoadId, *, all_firing_types: bool = False) -> LoadView:
        """Past loads stay viewable with their contents (#4). `NotFound`. A read: logs nothing."""
        load = _load(self._records, load_id)
        studio = self._studio()
        now = self._clock.now()
        members = tuple(
            drop_off for id in load.members if (drop_off := self._records.drop_off(id)) is not None
        )
        emails: dict[DropOffId, Email] = {}
        attention: list[Email] = []
        if load.status is LoadStatus.FIRED:
            for drop_off in members:
                email = self._records.email(drop_off.id, EmailKind.READY)
                if email is None:
                    continue
                emails[drop_off.id] = email
                if needs_acting_on(drop_off, email, now):
                    attention.append(email)
        waiting: tuple[WaitingRow, ...] = ()
        if load.status is LoadStatus.LOADING:
            waiting = self._waiting(None if all_firing_types else load.firing_type).rows
        return LoadView(
            load=load,
            kiln=item_name(studio, CatalogList.KILNS, load.kiln),
            firing_type=item_name(studio, CatalogList.FIRING_TYPES, load.firing_type),
            members=members,
            total_drop_offs=len(members),
            total_pieces=sum(drop_off.pieces for drop_off in members),
            emails=MappingProxyType(emails),
            sent=sum(1 for email in emails.values() if email.status is EmailStatus.SENT),
            needing_attention=tuple(attention),
            waiting=waiting,
        )


class ListLoads:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self) -> tuple[list[Load], list[Load]]:
        """(loading or firing, by date; fired in the last `RECENT_LOADS` by `fired_at`, newest
        first). A load dated Sunday and fired on Monday is listed by when it was fired."""
        since = self._clock.now() - RECENT_LOADS
        open_loads = self._records.loads_in({LoadStatus.LOADING, LoadStatus.FIRING})
        fired = [
            load
            for load in self._records.loads_in({LoadStatus.FIRED})
            if load.fired_at is not None and load.fired_at >= since
        ]
        fired.sort(key=lambda load: (load.fired_at, load.id), reverse=True)
        return open_loads, fired
