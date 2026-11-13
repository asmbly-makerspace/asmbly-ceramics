"""An in-memory `Records`: a dict per kind and the contract's checks."""

from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.studio import CatalogList, SettingChange, Studio
from asmbly_ceramics.ports.records import MAX_CHANGES, Change, Conflict, Item, Put, Submission, Update


class MemoryRecords:
    def __init__(self) -> None:
        self._items: dict[tuple[Any, ...], Item] = {}
        self._history_seq = 0
        self.fail_next_commit_with: Exception | None = None
        self.commits: list[Sequence[Change]] = []

    # --- keys, as the table's keys will be ---

    def _key(self, item: Item) -> tuple[Any, ...]:
        match item:
            case DropOff():
                return ("dropoff", item.id.number)
            case Load():
                return ("load", item.id.number)
            case Email():
                return ("email", item.drop_off_id.number, item.kind.value, item.occasion)
            case Studio():
                return ("studio",)
            case SettingChange():
                self._history_seq += 1  # the adapter adds a random suffix; this is a counter
                return ("history", item.at, self._history_seq)
            case Submission():
                return ("submission", item.token_hash)

    # --- writes ---

    def commit(self, changes: Sequence[Change]) -> None:
        if self.fail_next_commit_with is not None:
            failure, self.fail_next_commit_with = self.fail_next_commit_with, None
            raise failure
        if len(changes) > MAX_CHANGES:
            raise ValueError(f"At most {MAX_CHANGES} changes in one commit.")
        staged = dict(self._items)
        seq = self._history_seq
        try:
            for change in changes:
                self._apply(staged, change)
        except Conflict:
            self._history_seq = seq
            raise
        self._items = staged
        self.commits.append(tuple(changes))

    def _apply(self, staged: dict[tuple[Any, ...], Item], change: Change) -> None:
        item = change.item
        key = self._key(item)
        stored = staged.get(key)
        match change:
            case Put():
                if stored is not None:
                    raise Conflict("That already exists.")
            case Update():
                if stored is None or getattr(stored, "version", 0) != getattr(item, "version", 0):
                    raise Conflict("Someone else changed that first.")
        match item:
            case DropOff() | Load() | Email() | Studio():
                item = replace(item, version=item.version + 1)
            case _:
                pass
        staged[key] = item

    # --- strongly consistent reads ---

    def _get[T](self, key: tuple[Any, ...], kind: type[T]) -> T | None:
        found = self._items.get(key)
        return found if isinstance(found, kind) else None

    def drop_off(self, id: DropOffId) -> DropOff | None:
        return self._get(("dropoff", id.number), DropOff)

    def load(self, id: LoadId) -> Load | None:
        return self._get(("load", id.number), Load)

    def studio(self) -> Studio | None:
        return self._get(("studio",), Studio)

    def email(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> Email | None:
        return self._get(("email", drop_off_id.number, kind.value, occasion), Email)

    def submission(self, token_hash: str) -> Submission | None:
        return self._get(("submission", token_hash), Submission)

    # --- lists ---

    def _all[T](self, kind: type[T]) -> list[T]:
        return [i for i in self._items.values() if isinstance(i, kind)]

    def drop_offs_in(self, states: Collection[DropOffState]) -> list[DropOff]:
        found = [d for d in self._all(DropOff) if d.state in states]
        return sorted(found, key=lambda d: (d.created_at, d.id))

    def drop_offs_created_between(self, start: datetime, end: datetime) -> list[DropOff]:
        """From `start` up to, not including, `end`."""
        found = [d for d in self._all(DropOff) if start <= d.created_at < end]
        return sorted(found, key=lambda d: (d.created_at, d.id))

    def drop_offs_rejected_between(self, start: datetime, end: datetime) -> list[DropOff]:
        """Rejected at `start` up to, not including, `end`."""
        found = [d for d in self._all(DropOff) if d.rejection is not None and start <= d.rejection.at < end]
        return sorted(found, key=lambda d: (d.created_at, d.id))

    def loads_in(self, statuses: Collection[LoadStatus]) -> list[Load]:
        return sorted((x for x in self._all(Load) if x.status in statuses), key=lambda x: x.id)

    def loads_between(self, start: date, end: date) -> list[Load]:
        """Both dates included."""
        return sorted((x for x in self._all(Load) if start <= x.date <= end), key=lambda x: x.id)

    def emails_for(self, drop_off_id: DropOffId) -> list[Email]:
        found = [e for e in self._all(Email) if e.drop_off_id == drop_off_id]
        return sorted(found, key=lambda e: (e.created_at, e.kind.value, e.occasion))

    def emails_in(self, statuses: Collection[EmailStatus]) -> list[Email]:
        found = [e for e in self._all(Email) if e.status in statuses]
        return sorted(found, key=lambda e: (e.created_at, e.drop_off_id, e.kind.value, e.occasion))

    def history(self, limit: int, before: datetime | None = None) -> list[SettingChange]:
        keyed = sorted(
            ((k, v) for k, v in self._items.items() if isinstance(v, SettingChange)),
            key=lambda kv: (kv[0][1], kv[0][2]),
            reverse=True,
        )
        return [v for _, v in keyed if before is None or v.at < before][:limit]

    def is_item_used(self, which: CatalogList, id: ItemId) -> bool:
        match which:
            case CatalogList.KILNS:
                return any(x.kiln == id for x in self._all(Load))
            case CatalogList.FIRING_TYPES:
                return any(d.firing_type == id for d in self._all(DropOff)) or any(
                    x.firing_type == id for x in self._all(Load)
                )
            case CatalogList.GLAZE_TYPES:
                return any(d.glaze_type == id for d in self._all(DropOff))
            case CatalogList.REASONS:
                return any(d.rejection is not None and d.rejection.reason == id for d in self._all(DropOff))
