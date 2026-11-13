"""Where the drop-offs, loads, emails, the studio and its history are kept.

One table, one transaction per change with a version check on each item (decision
0002). The contract below is what the in-memory fake keeps and the DynamoDB adapter
(phase 4) matches:

- Keys: a drop-off and a load by their IDs; the studio is one item; an email by
  (`drop_off_id`, `kind`, `occasion`); a submission by `token_hash`; a `SettingChange` by
  its `at` and a random suffix, so two at the same instant both land.
- `Put` stores the item at `version + 1` and is refused with `Conflict` when the key
  exists. `Update` stores it at `version + 1` and is refused with `Conflict` unless an
  item with that key is stored at exactly `item.version`.
- `commit` is all or nothing. More than `MAX_CHANGES` changes, or two on one key, is a
  `ValueError` before anything is written. An empty commit is a no-op: nothing is sent
  (DynamoDB refuses an empty transaction) and nothing is written.
- A read of a key with nothing stored returns `None`.
- Every method raises `RecordsUnavailable(code)` when the table can't be reached.
- Ranges are half-open, `start <= value < end`, and their bounds are aware.
- Lists come in order: drop-offs by `created_at` then ID, loads by `date` then ID, emails
  by `created_at`, history newest first.
"""

# The errors are named for what happened (`Conflict`, `SendFailed`), as the plan's
# contract names them, not with an `Error` suffix.
# ruff: noqa: N818

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.studio import CatalogList, SettingChange, Studio
from asmbly_ceramics.ports.errors import PortError

MAX_CHANGES = 100  # DynamoDB's transaction limit; the 48-drop-off load keeps a fire at 97


@dataclass(frozen=True, slots=True)
class Submission:
    """One per form submission token, so a refresh makes no second drop-off.

    Holds the ID page's summary, so the public form never reads a drop-off item: no
    name, email, phone, message or photo, ever.
    """

    token_hash: str = field(repr=False)  # a keyed hash of the form's token: a lookup handle
    drop_off_id: DropOffId
    pieces: int
    firing_type: str  # the item's name when submitted
    glaze_type: str | None
    created_at: datetime
    expires_at: datetime  # SUBMISSION_LIFETIME after created_at; the adapter sets TTL from it


Item = DropOff | Load | Email | Studio | SettingChange | Submission


@dataclass(frozen=True, slots=True)
class Put:
    """Create; refused if the key exists."""

    item: Item


@dataclass(frozen=True, slots=True)
class Update:
    """Replace; refused unless the stored version equals `item.version`."""

    item: DropOff | Load | Email | Studio


Change = Put | Update


class Conflict(PortError):
    """Someone else changed one of these first. Nothing was written."""

    def __init__(self, ids: Sequence[str] = ()) -> None:
        if isinstance(ids, str):
            raise TypeError("Conflict takes a sequence of IDs, not one string")
        self.ids = tuple(ids)  # the drop-off or load IDs, when known
        super().__init__("changed by someone else first: " + (", ".join(self.ids) or "unknown"))


class Records(Protocol):
    def commit(self, changes: Sequence[Change]) -> None:
        """All or nothing; `Conflict`; at most `MAX_CHANGES` changes; empty is a no-op;
        `RecordsUnavailable`."""
        ...

    # Strongly consistent reads, used right before a commit. `None` when nothing is
    # stored under the key; `RecordsUnavailable`.
    def drop_off(self, id: DropOffId) -> DropOff | None: ...
    def load(self, id: LoadId) -> Load | None: ...
    def studio(self) -> Studio | None: ...
    def email(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> Email | None: ...
    def submission(self, token_hash: str) -> Submission | None: ...

    # Lists. Eventually consistent is fine: a stale list can't cause a wrong write,
    # because every write checks versions.
    def drop_offs_in(self, states: Collection[DropOffState]) -> list[DropOff]: ...
    def drop_offs_created_between(self, start: datetime, end: datetime) -> list[DropOff]: ...
    def drop_offs_rejected_between(self, start: datetime, end: datetime) -> list[DropOff]: ...
    def loads_in(self, statuses: Collection[LoadStatus]) -> list[Load]: ...
    def loads_between(self, start: date, end: date) -> list[Load]: ...
    def emails_for(self, drop_off_id: DropOffId) -> list[Email]: ...
    def emails_in(self, statuses: Collection[EmailStatus]) -> list[Email]: ...
    def history(self, limit: int, before: datetime | None = None) -> list[SettingChange]:
        """Newest first, at most `limit`, strictly before `before` when given."""
        ...

    def is_item_used(self, which: CatalogList, id: ItemId) -> bool:
        """A kiln by any load; a firing type by any drop-off or load; a glaze type by any
        drop-off; a reason by any drop-off's rejection, closed ones included."""
        ...
