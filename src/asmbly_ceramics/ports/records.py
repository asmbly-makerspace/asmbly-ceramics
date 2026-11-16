"""Where the drop-offs, loads, emails, the studio and its history are kept.

One table, one transaction per change with a version check on each item (decision
0002). The contract below is what the in-memory fake keeps and the DynamoDB adapter
(phase 4) matches:

- Keys: a drop-off and a load by their IDs; the studio is one item; an email by
  (`drop_off_id`, `kind`, `occasion`); a submission by `token_hash`; a `SettingChange` by
  its `at` and a random suffix, so two at the same instant both land; a `LoadEvent` by
  its load, its `at` and a random suffix, likewise; a `FiringNote` by its load and its ID.
- `Put` stores the item at `version + 1` and is refused with `Conflict` when the key
  exists. `Update` replaces the whole item (phase 4: a transactional `Put` of the whole
  item under a version condition, not an `UpdateItem`), stores it at `version + 1`, and
  is refused with `Conflict` unless an item with that key is stored at exactly
  `item.version`.
- `commit` is all or nothing and returns nothing: a caller that needs a stored item
  after a commit reads it again (an entity is stored at `item.version + 1`). More than
  `MAX_CHANGES` changes, or two on one key, is a `ValueError` before anything is
  written. An empty commit is a no-op: nothing is sent (DynamoDB refuses an empty
  transaction) and nothing is written.
- A read of a key with nothing stored returns `None`.
- Every method raises `RecordsUnavailable(code)` when the table can't be reached.
- Ranges are half-open, `start <= value < end`, and their bounds are aware.
- Lists come in order: drop-offs by `created_at` then ID, loads by `date` then ID, emails
  by `created_at`, history newest first, a load's events oldest first, notes newest
  `written_at` first (then by ID, highest first). A removed note is listed nowhere.
- A date range (`loads_dated_between`) is half-open on plain dates; an empty or reversed
  range lists nothing.
- History pages by an opaque cursor, never by a time alone: one settings save can write
  several changes at the same instant (`change_email_settings`), and a time cursor would
  skip the ones after a page's end. Changes at one instant come in a fixed order (their
  key's suffix), and `HistoryPage.older` resumes exactly after the page's last change.
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
from asmbly_ceramics.domain.history import LoadEvent
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId, NoteId
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.notes import FiringNote
from asmbly_ceramics.domain.studio import CatalogList, SettingChange, Studio
from asmbly_ceramics.ports.errors import PortError, RecordsUnavailable

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


Item = DropOff | Load | Email | Studio | SettingChange | Submission | LoadEvent | FiringNote


@dataclass(frozen=True, slots=True)
class Put:
    """Create; refused if the key exists."""

    item: Item


@dataclass(frozen=True, slots=True)
class Update:
    """Replace; refused unless the stored version equals `item.version`."""

    item: DropOff | Load | Email | Studio | FiringNote


Change = Put | Update


class Conflict(PortError):
    """Someone else changed one of these first. Nothing was written."""

    def __init__(self, ids: Sequence[str] = ()) -> None:
        if isinstance(ids, str):
            raise TypeError("Conflict takes a sequence of IDs, not one string")
        self.ids = tuple(ids)  # the drop-off, load or note IDs, when known
        super().__init__("changed by someone else first: " + (", ".join(self.ids) or "unknown"))


class CommitOutcomeUnknown(RecordsUnavailable):
    """`commit` sent the transaction and got no answer it can trust (a timeout, a lost
    connection, the transaction still in progress, a server error): it may have landed,
    now or later, even after a strongly consistent read that found nothing. A caller that
    would undo something outside the table when nothing was written (the submit deleting
    the photos it kept) leaves it to the backstop instead. Every other failure of
    `commit`, `Conflict` included, means nothing was written."""


@dataclass(frozen=True, slots=True)
class HistoryPage:
    """At most `limit` changes, newest first, and where the next (older) page starts."""

    changes: tuple[SettingChange, ...]
    # Pass as `before` for the next page; `None` exactly when no older change exists (the
    # DynamoDB adapter asks for one more than `limit` to know). Opaque: a page passes it
    # back as it came and never builds or reads one.
    older: str | None


class BadCursor(PortError):
    """`history` was given a cursor it never returned (a hand-edited page address)."""

    def __init__(self) -> None:
        super().__init__("not a history cursor")


class Records(Protocol):
    def commit(self, changes: Sequence[Change]) -> None:
        """All or nothing; `Conflict`; at most `MAX_CHANGES` changes; empty is a no-op;
        `RecordsUnavailable`, or `CommitOutcomeUnknown` (a `RecordsUnavailable`) when it
        may still land. Returns nothing: re-read what you need afterwards."""
        ...

    # Strongly consistent reads, used right before a commit. `None` when nothing is
    # stored under the key; `RecordsUnavailable`.
    def drop_off(self, id: DropOffId) -> DropOff | None: ...
    def load(self, id: LoadId) -> Load | None: ...
    def studio(self) -> Studio | None: ...
    def email(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> Email | None: ...
    def submission(self, token_hash: str) -> Submission | None: ...
    def note(self, load_id: LoadId, note_id: NoteId) -> FiringNote | None:
        """Removed notes are returned too: the use case decides."""
        ...

    # Lists. Eventually consistent is fine: a stale list can't cause a wrong write,
    # because every write checks versions.
    def drop_offs_in(self, states: Collection[DropOffState]) -> list[DropOff]: ...
    def drop_offs_created_between(self, start: datetime, end: datetime) -> list[DropOff]: ...
    def drop_offs_rejected_between(self, start: datetime, end: datetime) -> list[DropOff]: ...
    def loads_in(self, statuses: Collection[LoadStatus]) -> list[Load]: ...
    def loads_dated_between(self, statuses: Collection[LoadStatus], start: date, end: date) -> list[Load]:
        """Loads in `statuses` dated `start <= date < end`, by date then ID. Reads only
        that range of each status's index partition, so its cost doesn't grow with the
        years kept."""
        ...

    def load_events(self, load_id: LoadId) -> list[LoadEvent]:
        """The load's history, oldest first. Two at one instant come in no promised order
        (the adapter's is its key's random suffix), so a caller or test that needs an order
        between two events gives them different times."""
        ...

    def notes_for(self, load_id: LoadId) -> list[FiringNote]:
        """The load's notes, removed ones left out, newest `written_at` first."""
        ...

    def notes_written_between(self, start: datetime, end: datetime) -> list[FiringNote]:
        """Every load's notes written `start <= written_at < end`, removed ones left out,
        newest first. Reads only that range of the index."""
        ...

    def emails_for(self, drop_off_id: DropOffId) -> list[Email]: ...
    def emails_in(self, statuses: Collection[EmailStatus]) -> list[Email]: ...
    def history(self, limit: int, before: str | None = None) -> HistoryPage:
        """Newest first, at most `limit` (at least 1, else `ValueError`), starting just
        after the change `before` (a `HistoryPage.older`) names; `BadCursor` for any other
        text. Two changes at one instant are never split or skipped across pages."""
        ...

    def is_item_used(self, which: CatalogList, id: ItemId) -> bool:
        """Deleted drop-offs and loads use nothing. A kiln by any load; a firing type by
        any drop-off or load; a glaze type by any drop-off or any firing note that isn't
        removed (#17); a reason by any drop-off's rejection, closed ones included; a cone
        by any load's program (its record's `program.cone`) or by a firing type's default
        program in the stored studio (`names_cone`; none when no studio is stored); a clay
        body by any firing note that isn't removed. A note counts whatever its load's
        status, a deleted load's included."""
        ...
