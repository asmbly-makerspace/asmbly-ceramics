"""`Records` in memory: dictionaries keyed as the port's contract says.

Entities are frozen, so storing and returning the same objects is storing copies. Logs
nothing.
"""

import itertools
from collections.abc import Collection, Hashable, Iterable, Sequence
from dataclasses import replace
from datetime import date, datetime

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.studio import CatalogList, SettingChange, Studio
from asmbly_ceramics.ports.records import (
    MAX_CHANGES,
    BadCursor,
    Change,
    Conflict,
    HistoryPage,
    Item,
    Put,
    Submission,
    Update,
)

_STUDIO_KEY = ("studio",)


class MemoryRecords:
    def __init__(self) -> None:
        self._items: dict[Hashable, Item] = {}
        self._suffix = itertools.count(1)  # the adapter's random suffix on a SettingChange key
        self.fail_next_commit_with: Exception | None = None
        self.fail_reads_with: Exception | None = None
        self.commits: list[tuple[Change, ...]] = []  # the commits that succeeded
        # Every read, by the method's name, once per call (failed ones too), so a test can
        # prove which items a use case read. `commit` doesn't append.
        self.reads: list[str] = []

    def commit(self, changes: Sequence[Change]) -> None:
        changes = tuple(changes)
        if not changes:
            return  # the contract's no-op: not sent, not recorded
        if len(changes) > MAX_CHANGES:
            raise ValueError(f"at most {MAX_CHANGES} changes in one commit")
        keys = [self._key(change.item) for change in changes]
        if len(set(keys)) != len(keys):
            raise ValueError("two changes on one key in one commit")
        if self.fail_next_commit_with is not None:
            error, self.fail_next_commit_with = self.fail_next_commit_with, None
            raise error

        refused = [
            change for change, key in zip(changes, keys, strict=True) if not self._allowed(change, key)
        ]
        if refused:
            ids = dict.fromkeys(_conflict_id(change.item) for change in refused)  # in order, once each
            raise Conflict([known for known in ids if known])
        for change, key in zip(changes, keys, strict=True):
            self._items[key] = _stored(change.item)
        self.commits.append(changes)

    def drop_off(self, id: DropOffId) -> DropOff | None:
        return self._get("drop_off", ("drop_off", id), DropOff)

    def load(self, id: LoadId) -> Load | None:
        return self._get("load", ("load", id), Load)

    def studio(self) -> Studio | None:
        return self._get("studio", _STUDIO_KEY, Studio)

    def email(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> Email | None:
        return self._get("email", ("email", drop_off_id, kind, occasion), Email)

    def submission(self, token_hash: str) -> Submission | None:
        return self._get("submission", ("submission", token_hash), Submission)

    def drop_offs_in(self, states: Collection[DropOffState]) -> list[DropOff]:
        self._read("drop_offs_in")
        return _by_created(d for d in self._all(DropOff) if d.state in states)

    def drop_offs_created_between(self, start: datetime, end: datetime) -> list[DropOff]:
        _check_range(start, end)
        self._read("drop_offs_created_between")
        return _by_created(d for d in self._all(DropOff) if start <= d.created_at < end)

    def drop_offs_rejected_between(self, start: datetime, end: datetime) -> list[DropOff]:
        _check_range(start, end)
        self._read("drop_offs_rejected_between")
        return _by_created(
            d for d in self._all(DropOff) if d.rejection is not None and start <= d.rejection.at < end
        )

    def loads_in(self, statuses: Collection[LoadStatus]) -> list[Load]:
        self._read("loads_in")
        return _by_date(load for load in self._all(Load) if load.status in statuses)

    def loads_between(self, start: date, end: date) -> list[Load]:
        self._read("loads_between")
        return _by_date(load for load in self._all(Load) if start <= load.date < end)

    def emails_for(self, drop_off_id: DropOffId) -> list[Email]:
        self._read("emails_for")
        return sorted(
            (e for e in self._all(Email) if e.drop_off_id == drop_off_id), key=lambda e: e.created_at
        )

    def emails_in(self, statuses: Collection[EmailStatus]) -> list[Email]:
        self._read("emails_in")
        return sorted((e for e in self._all(Email) if e.status in statuses), key=lambda e: e.created_at)

    def history(self, limit: int, before: str | None = None) -> HistoryPage:
        if limit < 1:
            raise ValueError("history's limit is at least 1")
        start = None if before is None else _parse_cursor(before)
        self._read("history")
        keyed = sorted(
            (
                ((key[1], key[2]), item)
                for key, item in self._items.items()
                if isinstance(item, SettingChange) and isinstance(key, tuple)
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if start is not None:
            keyed = [pair for pair in keyed if pair[0] < start]
        page = keyed[:limit]
        older = _cursor(*page[-1][0]) if len(keyed) > limit else None
        return HistoryPage(tuple(change for _, change in page), older)

    def is_item_used(self, which: CatalogList, id: ItemId) -> bool:
        self._read("is_item_used")
        drop_offs = self._all(DropOff)
        loads = self._all(Load)
        match which:
            case CatalogList.KILNS:
                return any(load.kiln == id for load in loads)
            case CatalogList.FIRING_TYPES:
                return any(d.firing_type == id for d in drop_offs) or any(
                    load.firing_type == id for load in loads
                )
            case CatalogList.GLAZE_TYPES:
                return any(d.glaze_type == id for d in drop_offs)
            case CatalogList.REASONS:
                return any(d.rejection is not None and d.rejection.reason == id for d in drop_offs)

    def _allowed(self, change: Change, key: Hashable) -> bool:
        stored = self._items.get(key)
        match change:
            case Put():
                return stored is None
            case Update(item=item):
                return stored is not None and getattr(stored, "version", None) == item.version

    def _key(self, item: Item) -> Hashable:
        match item:
            case DropOff():
                return ("drop_off", item.id)
            case Load():
                return ("load", item.id)
            case Studio():
                return _STUDIO_KEY
            case Email():
                return ("email", item.drop_off_id, item.kind, item.occasion)
            case Submission():
                return ("submission", item.token_hash)
            case SettingChange():
                return ("setting_change", item.at, next(self._suffix))

    def _get[T](self, read: str, key: Hashable, kind: type[T]) -> T | None:
        self._read(read)
        item = self._items.get(key)
        return item if isinstance(item, kind) else None

    def _all[T](self, kind: type[T]) -> list[T]:
        return [item for item in self._items.values() if isinstance(item, kind)]

    def _read(self, name: str) -> None:
        self.reads.append(name)
        if self.fail_reads_with is not None:
            raise self.fail_reads_with


def _stored(item: Item) -> Item:
    """The item as stored: an entity's version goes up by one."""
    match item:
        case DropOff() | Load() | Email() | Studio():
            return replace(item, version=item.version + 1)
        case SettingChange() | Submission():
            return item


def _conflict_id(item: Item) -> str:
    """The drop-off or load ID a refused change names, when it has one."""
    match item:
        case DropOff() | Load():
            return str(item.id)
        case Email() | Submission():
            return str(item.drop_off_id)
        case Studio() | SettingChange():
            return ""


def _cursor(at: datetime, suffix: int) -> str:
    """Like the DynamoDB adapter's sort key after `HISTORY#`: the time and the suffix."""
    return f"{at.isoformat()}#{suffix}"


def _parse_cursor(cursor: str) -> tuple[datetime, int]:
    at, _, suffix = cursor.rpartition("#")
    try:
        parsed = (datetime.fromisoformat(at), int(suffix))
    except ValueError:
        raise BadCursor() from None
    if parsed[0].utcoffset() is None or not suffix.isdigit():
        raise BadCursor()
    return parsed


def _by_created(drop_offs: Iterable[DropOff]) -> list[DropOff]:
    return sorted(drop_offs, key=lambda d: (d.created_at, d.id))


def _by_date(loads: Iterable[Load]) -> list[Load]:
    return sorted(loads, key=lambda load: (load.date, load.id))


def _check_range(start: datetime, end: datetime) -> None:
    _check_aware(start)
    _check_aware(end)


def _check_aware(at: datetime) -> None:
    if at.utcoffset() is None:
        raise ValueError("a range's times are aware")
