"""Storage of every record, behind one atomic `commit`."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.studio import CatalogList, SettingChange, Studio


@dataclass(frozen=True, slots=True)
class Submission:
    """One per form submission token, so a refresh makes no second drop-off.

    The ID page's summary, so the public form never reads a drop-off item.
    No name, email, phone, message or photo: ever.
    """

    token_hash: str
    drop_off_id: DropOffId
    pieces: int
    firing_type: str  # the item's name when submitted
    glaze_type: str | None
    created_at: datetime
    expires_at: datetime  # SUBMISSION_LIFETIME; the adapter sets TTL from it


Item = DropOff | Load | Email | Studio | SettingChange | Submission


@dataclass(frozen=True, slots=True)
class Put:
    item: Item  # create; refused if the key exists


@dataclass(frozen=True, slots=True)
class Update:
    item: Item  # replace; refused unless the stored version equals item.version


Change = Put | Update


class Conflict(Exception):
    """Someone else changed one of these first. Nothing was written."""


class Unavailable(Exception):
    """AWS or the network failed. Safe to show as "try again"; holds the provider's
    error code only, never its message."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RecordsUnavailable(Unavailable): ...


class IdsUnavailable(Unavailable): ...


class PhotosUnavailable(Unavailable): ...


class SignInUnavailable(Unavailable): ...


class SecretsUnavailable(Unavailable): ...


class SecretMissing(Exception):
    """The parameter doesn't exist (a setup error, at start)."""


MAX_CHANGES = 100


class Records(Protocol):
    def commit(self, changes: Sequence[Change]) -> None:
        """All or nothing. Raises Conflict. At most MAX_CHANGES changes."""
        ...

    # Strongly consistent reads, used right before a commit.
    def drop_off(self, id: DropOffId) -> DropOff | None: ...
    def load(self, id: LoadId) -> Load | None: ...
    def studio(self) -> Studio | None: ...
    def email(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> Email | None: ...
    def submission(self, token_hash: str) -> Submission | None: ...

    # Lists. Eventually consistent is fine: every write checks versions.
    def drop_offs_in(self, states: Collection[DropOffState]) -> list[DropOff]: ...
    def drop_offs_created_between(self, start: datetime, end: datetime) -> list[DropOff]: ...
    def drop_offs_rejected_between(self, start: datetime, end: datetime) -> list[DropOff]: ...
    def loads_in(self, statuses: Collection[LoadStatus]) -> list[Load]: ...
    def loads_between(self, start: date, end: date) -> list[Load]: ...
    def emails_for(self, drop_off_id: DropOffId) -> list[Email]: ...
    def emails_in(self, statuses: Collection[EmailStatus]) -> list[Email]: ...
    def history(self, limit: int, before: datetime | None = None) -> list[SettingChange]:
        """Newest first."""
        ...

    def is_item_used(self, which: CatalogList, id: ItemId) -> bool: ...
