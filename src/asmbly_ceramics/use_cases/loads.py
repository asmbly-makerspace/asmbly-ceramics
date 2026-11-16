"""Building a kiln load and firing it (#4): what the console's load pages call.

Every change reads what it changes (strongly consistent) and commits it in one commit of
`Update`s with the versions read, so two staff acting at once can't both win: the loser
gets `Conflict`. Where the page passes the version it showed, the domain's refusal of a
wrong status comes first, so a second click on "Fired" says `AlreadyFired`, not
`Conflict`. Logs carry load and drop-off IDs and the staff username only.

Every change to the load itself (#42) puts one line of its history (`LoadEvent`) in the
same commit, with the staff username and the clock's time; adding or removing a drop-off
writes none. A line names loads, studio items, steps, times and record values, never a
person's details: the history is kept with the load after the close (#7).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus, needs_acting_on
from asmbly_ceramics.domain.errors import AlreadyFired, FiredLoadNotDeletable, NotFound, TooManyNotesToMove
from asmbly_ceramics.domain.firing import (
    FiringRecord,
    changed_fields,
    read_firing_record,
    record_changes,
    record_values,
)
from asmbly_ceramics.domain.history import LoadEvent, event
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.load import (
    Load,
    LoadStatus,
    Step,
    add_to_load,
    can_correct_step,
    can_delete,
    can_start_firing,
    change_load,
    correct_step_time,
    delete_load,
    fire,
    firing_type_locked,
    numbers_window,
    remove_from_load,
    set_firing_record,
    start_firing,
    start_load,
    step_time,
    suggest_numbers,
)
from asmbly_ceramics.domain.notes import move_note, remove_note
from asmbly_ceramics.domain.studio import (
    CatalogItem,
    CatalogList,
    KilnCounts,
    Studio,
    nameable_cone_ids,
    nameable_cones,
)
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.ids import IdNumbers
from asmbly_ceramics.ports.records import MAX_CHANGES, Change, Conflict, Put, Records, Update
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.use_cases.studio import CurrentStudio, item_name
from asmbly_ceramics.use_cases.waiting import WaitingList, WaitingRow

RECENT_LOADS = timedelta(weeks=8)
"""How far back `ListLoads` lists fired loads; older ones stay viewable by their ID."""

NOTES_MOVED_MAX = MAX_CHANGES - 2
"""The most notes a kiln change can move: its commit also holds the load and its history line."""

STEP_LABELS = {Step.STARTED: "Loading", Step.FIRING: "Firing", Step.FIRED: "Fired"}
_STEP_CORRECTED = {
    Step.STARTED: "when it was started",
    Step.FIRING: "when it started firing",
    Step.FIRED: "when it was fired",
}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _load(records: Records, id: LoadId) -> Load:
    """The load, or `NotFound`: a deleted load is gone for every use case and page."""
    load = records.load(id)
    if load is None or load.status is LoadStatus.DELETED:
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


def _event(load: Load, staff: StaffMember, at: datetime, what: str) -> Put:
    """The load's history line for this change, to commit with it."""
    return Put(event(load.id, staff.username, at, what))


def _day(on: date, *, year: bool = False) -> str:
    """`Nov 12`, or `Nov 12, 2026` with `year`."""
    day = f"{_MONTHS[on.month - 1]} {on.day}"
    return f"{day}, {on.year}" if year else day


def _days(old: date, new: date) -> tuple[str, str]:
    """Both days as a line shows them: with their years when the years differ."""
    year = old.year != new.year
    return _day(old, year=year), _day(new, year=year)


def _austin(at: datetime, *, year: bool = False) -> str:
    """`Nov 12, 4:10 pm` (`Nov 12, 2026, 4:10 pm` with `year`), in Austin time."""
    local = at.astimezone(STUDIO_TZ)
    hour = local.hour % 12 or 12
    return f"{_day(local.date(), year=year)}, {hour}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"


def _same_minute(a: datetime, b: datetime) -> bool:
    """The same instant to the minute, the precision the page posts and a line shows."""
    return a.astimezone(UTC).replace(second=0, microsecond=0) == b.astimezone(UTC).replace(
        second=0, microsecond=0
    )


def _cone_name(studio: Studio) -> Callable[[ItemId], str]:
    return lambda id: item_name(studio, CatalogList.CONES, id)


def _record_line(old: FiringRecord, new: FiringRecord, studio: Studio) -> str | None:
    lines = record_changes(old, new, _cone_name(studio))
    return "Firing record: " + "; ".join(lines) if lines else None


def _change_lines(old: Load, new: Load, studio: Studio) -> str:
    """ "Kiln: Athena → Helios; Date: Nov 12 → Nov 13", or "" when nothing changed."""
    lines: list[str] = []
    for which, before, after in (
        (CatalogList.KILNS, old.kiln, new.kiln),
        (CatalogList.FIRING_TYPES, old.firing_type, new.firing_type),
    ):
        if before != after:
            label = "Kiln" if which is CatalogList.KILNS else "Firing type"
            lines.append(f"{label}: {item_name(studio, which, before)} → {item_name(studio, which, after)}")
    if old.date != new.date:
        old_day, new_day = _days(old.date, new.date)
        lines.append(f"Date: {old_day} → {new_day}")
    if old.test != new.test:
        lines.append("Marked a test firing" if new.test else "No longer a test firing")
    if (record := _record_line(old.record, new.record, studio)) is not None:
        lines.append(record)  # a new firing type's default program swapped in
    return "; ".join(lines)


def record_cones(studio: Studio, record: FiringRecord) -> tuple[CatalogItem, ...]:
    """The cones a record can name (`studio.nameable_cones`, as `set_default_program`
    allows)."""
    return nameable_cones(studio, record.program.cone)


class StartLoad:
    def __init__(self, records: Records, ids: IdNumbers, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._ids = ids
        self._clock = clock
        self._studio = studio

    def __call__(
        self, kiln: ItemId, firing_type: ItemId, on: date | None, staff: StaffMember, *, test: bool = False
    ) -> Load:
        """A new, empty load, dated `on` or today in Austin, a test firing or not.
        `UnknownItem`, `ItemRetired`."""
        studio = self._studio()
        now = self._clock.now()
        # The domain's own checks, asked before a number is spent on a refused load.
        studio.active_item(CatalogList.KILNS, kiln)
        studio.active_item(CatalogList.FIRING_TYPES, firing_type)
        day = on if on is not None else now.astimezone(STUDIO_TZ).date()
        load = start_load(
            self._ids.next_load_id(), kiln, firing_type, day, staff.username, now, studio, test=test
        )
        what = "Started the load as a test firing" if test else "Started the load"
        self._records.commit([Put(load), _event(load, staff, now, what)])
        if test:
            log_event("load_started", load_id=str(load.id), kind="test", user=staff.username)
        else:
            log_event("load_started", load_id=str(load.id), user=staff.username)
        return _stored(load)


class ChangeLoad:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def __call__(
        self,
        load_id: LoadId,
        kiln: ItemId,
        firing_type: ItemId,
        on: date,
        version: int,
        staff: StaffMember,
        *,
        test: bool,
    ) -> Load:
        """ "Change kiln, firing or date", and whether it is a test, only while loading; the
        firing type only while empty. `NotFound`, `LoadNotLoading`, `FiringTypeLocked`,
        `UnknownItem`, `ItemRetired`, `TooManyNotesToMove`, `Conflict`.

        Nothing changed: no commit and no log, the load returned as it is. A new kiln
        moves the load's notes (removed ones are listed nowhere and keep theirs) in the
        same commit, so the notes search by kiln finds them where the load now is."""
        load = _load(self._records, load_id)
        studio = self._studio()
        changed = change_load(load, kiln, firing_type, on, studio, test=test)
        _check_version(load, version)
        what = _change_lines(load, changed, studio)
        if not what:
            return load
        changes: list[Change] = [Update(changed), _event(changed, staff, self._clock.now(), what)]
        if changed.kiln != load.kiln:
            notes = self._records.notes_for(load.id)
            if len(notes) > NOTES_MOVED_MAX:
                raise TooManyNotesToMove(load.id, NOTES_MOVED_MAX)
            changes.extend(Update(move_note(note, changed.kiln)) for note in notes)
        self._records.commit(changes)
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
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, load_id: LoadId, version: int, staff: StaffMember) -> Load:
        """Loading to firing, recording who and when: nothing can be added or removed after
        this. `NotFound`, `WrongLoadStatus`, `EmptyLoad` (unless a test), `Conflict`."""
        load = _load(self._records, load_id)
        now = self._clock.now()
        firing = start_firing(load, staff.username, now)
        _check_version(load, version)
        self._records.commit([Update(firing), _event(firing, staff, now, "Started firing")])
        log_event("load_firing", load_id=str(load.id), user=staff.username)
        return _stored(firing)


class MarkFired:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, load_id: LoadId, version: int, staff: StaffMember) -> Load:
        """Firing to fired: the load, each drop-off fired, one ready email each and the
        history line, in one commit (at most 1 + 48 + 48 + 1 changes). `AlreadyFired`
        (nothing is queued again), `WrongLoadStatus`, `NotFound`, `Conflict`."""
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
        now = self._clock.now()
        result = fire(load, members, staff.username, now)
        _check_version(load, version)
        changes: list[Change] = [Update(result.load)]
        changes.extend(Update(drop_off) for drop_off in result.drop_offs)
        changes.extend(Put(email) for email in result.emails)
        changes.append(_event(result.load, staff, now, "Marked fired"))
        self._records.commit(changes)
        log_event("load_fired", load_id=str(load.id), count=len(result.drop_offs), user=staff.username)
        return _stored(result.load)


class DeleteLoad:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, load_id: LoadId, version: int, staff: StaffMember) -> Load:
        """A load started by mistake, deleted while loading or firing: its drop-offs go back
        to the waiting list and its notes are removed (by the staff member deleting, so a
        deleted load's tags count as used nowhere), in one commit with the load and its
        history line. `NotFound` (deleted already), `FiredLoadNotDeletable`,
        `TooManyNotesToMove` (more notes than the commit holds beside the load, its
        drop-offs and the line), `Conflict`."""
        load = _load(self._records, load_id)
        members = [_drop_off(self._records, id) for id in load.members] if can_delete(load) else []
        # Another action landed between the load's read and its members' (a fire, a remove,
        # another delete): let the load as it is now answer, not the members it no longer has.
        if any(d.state is not DropOffState.IN_LOAD or d.load_id != load.id for d in members):
            now = _load(self._records, load_id)  # `NotFound` once deleted
            if now.status is LoadStatus.FIRED:
                raise FiredLoadNotDeletable(load.id)
            raise Conflict([str(load.id)])
        at = self._clock.now()
        deleted, waiting = delete_load(load, members, staff.username, at)
        _check_version(load, version)
        notes = self._records.notes_for(load.id)
        room = MAX_CHANGES - 2 - len(waiting)
        if len(notes) > room:
            raise TooManyNotesToMove(load.id, room, deleting=True)
        changes: list[Change] = [Update(deleted)]
        changes.extend(Update(drop_off) for drop_off in waiting)
        changes.extend(Update(remove_note(note, staff.username, at)) for note in notes)
        changes.append(_event(deleted, staff, at, "Deleted the load"))
        self._records.commit(changes)
        log_event("load_deleted", load_id=str(load.id), count=len(waiting), user=staff.username)
        return _stored(deleted)


class SaveFiringRecord:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def __call__(self, load_id: LoadId, values: Mapping[str, str], version: int, staff: StaffMember) -> Load:
        """The firing record from the page, at any live status (#42). Its cone is an active
        cone or the one the record already names (the cones `record_cones` offers, and that
        one even if the studio no longer lists it). It never changes the
        load's drop-offs and queues no email. Nothing changed: no commit, the load
        returned as it is. `NotFound`, `InvalidRecord`, `Conflict`."""
        load = _load(self._records, load_id)
        studio = self._studio()
        cones = nameable_cone_ids(studio, load.record.program.cone)  # even one gone from the list
        saved = set_firing_record(load, read_firing_record(values, cones))
        _check_version(load, version)
        what = _record_line(load.record, saved.record, studio)
        if what is None:
            return load
        self._records.commit([Update(saved), _event(saved, staff, self._clock.now(), what)])
        fields = ",".join(changed_fields(load.record, saved.record))
        log_event("firing_record_saved", load_id=str(load.id), user=staff.username, fields=fields)
        return _stored(saved)


class CorrectStepTime:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, load_id: LoadId, step: Step, at: datetime, version: int, staff: StaffMember) -> Load:
        """A reached step's time corrected, for a button pressed late (#42): the old and new
        times go in the history line, and who reached the step never changes. The same
        time to the minute (the page posts minutes; the line shows them): no commit, and
        the stored seconds stay. The line shows the years when they differ. `NotFound`,
        `StepNotReached`, `StepTimeInFuture`, `StepTimeTooEarly`, `StepTimeOutOfOrder`,
        `Conflict`.

        Correcting the fired step moves `load.fired_at` only: its drop-offs keep their own
        `fired_at`."""
        load = _load(self._records, load_id)
        now = self._clock.now()
        corrected = correct_step_time(load, step, at, now)
        _check_version(load, version)
        old = step_time(load, step)
        if old is None or _same_minute(old, at):  # `correct_step_time` refused an unreached step
            return load
        year = old.astimezone(STUDIO_TZ).year != at.astimezone(STUDIO_TZ).year
        what = f"Corrected {_STEP_CORRECTED[step]}: {_austin(old, year=year)} → {_austin(at, year=year)}"
        self._records.commit([Update(corrected), _event(corrected, staff, now, what)])
        log_event("step_time_corrected", load_id=str(load.id), kind=step.value, user=staff.username)
        return _stored(corrected)


@dataclass(frozen=True, slots=True)
class StepView:
    step: Step
    label: str  # "Loading", "Firing", "Fired"
    reached: bool
    by: str | None  # None with reached True: "not recorded" (a load made before #42)
    at: datetime | None
    can_correct: bool  # the domain's `can_correct_step`: False for a pre-#42 load's firing step


def _steps(load: Load) -> tuple[StepView, ...]:
    reached = {
        Step.STARTED: True,
        Step.FIRING: load.status in (LoadStatus.FIRING, LoadStatus.FIRED),
        Step.FIRED: load.status is LoadStatus.FIRED,
    }
    by = {Step.STARTED: load.started_by, Step.FIRING: load.firing_started_by, Step.FIRED: load.fired_by}
    return tuple(
        StepView(
            step=step,
            label=STEP_LABELS[step],
            reached=reached[step],
            by=by[step] if reached[step] else None,
            at=step_time(load, step) if reached[step] else None,
            can_correct=can_correct_step(load, step),
        )
        for step in Step
    )


def _kiln_counts(studio: Studio, kiln: ItemId) -> KilnCounts | None:
    return next((item.counts for item in studio.kilns if item.id == kiln), None)


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
    can_start_firing: bool  # the domain's `can_start_firing`
    can_delete: bool  # the domain's `can_delete`
    firing_type_locked: bool  # the domain's `firing_type_locked`
    steps: tuple[StepView, ...]  # STARTED, FIRING, FIRED in order
    history: tuple[LoadEvent, ...]  # oldest first
    suggested: tuple[int | None, int | None]  # (firing #, all time #) for the record form
    cones: tuple[CatalogItem, ...]  # the cones the record form offers (`record_cones`)
    record_fields: Mapping[str, str]  # the record as the form shows it ("11:38", "8.19", "none")


class ViewLoad:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio
        self._waiting = WaitingList(records, clock, studio)

    def __call__(self, load_id: LoadId, *, all_firing_types: bool = False) -> LoadView:
        """Past loads stay viewable with their contents (#4), with who moved them, their
        firing record and their history (#42). `NotFound`. A read: logs nothing."""
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
            can_start_firing=can_start_firing(load),
            can_delete=can_delete(load),
            firing_type_locked=firing_type_locked(load),
            steps=_steps(load),
            history=tuple(self._records.load_events(load.id)),
            suggested=self._suggested(load, studio, now),
            cones=record_cones(studio, load.record),
            record_fields=MappingProxyType(record_values(load.record)),
        )

    def _suggested(self, load: Load, studio: Studio, now: datetime) -> tuple[int | None, int | None]:
        """The numbers to suggest, only while the record has neither (so a numbered load's
        page reads no other load): from the kiln's counts and its loads fired before this
        one (`numbers_window` around its `fired_at`, or now while unfired), this load left
        out. None for a load fired at or before the counts' `as_of`: the counts already
        include it, so counts plus 1 would be the next firing's number, not its own.
        Two loads loading on one kiln at once are both suggested the same next number."""
        if load.record.firing_number is not None or load.record.all_time_number is not None:
            return None, None
        counts = _kiln_counts(studio, load.kiln)
        if counts is not None and load.fired_at is not None and load.fired_at <= counts.as_of:
            return None, None
        start, end = numbers_window(counts, load.fired_at or now)
        dated = self._records.loads_dated_between({LoadStatus.FIRED}, start, end)
        fired = [
            other
            for other in dated
            if other.kiln == load.kiln
            and other.id != load.id
            and (load.fired_at is None or (other.fired_at is not None and other.fired_at < load.fired_at))
        ]
        return suggest_numbers(counts, fired)


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
