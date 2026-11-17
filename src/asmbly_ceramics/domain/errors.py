"""The domain's refusals.

Every message here is safe to show to staff and to write to a log: it names drop-off and
load IDs, states, studio items (kilns, reasons) and setting names, never a person's name,
email address, phone number or rejection message. Each constructor takes only what its
message names.

The class names are the plan's contract with the later phases and read as what happened
(`NotWaiting`, `LoadFull`), so pep8-naming's "Error" suffix rule is off in this file only.
"""

# ruff: noqa: N818

from collections.abc import Mapping
from types import MappingProxyType

from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId, NoteId
from asmbly_ceramics.domain.limits import LOG_RANGE_MAX_YEARS

FieldErrors = Mapping[str, str]
"""A field's name mapped to its message key (`email.invalid`), never to the field's value."""


class DomainError(Exception):
    """A refusal whose message is safe to show to staff and to log."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._message = message

    @property
    def message(self) -> str:
        return self._message


FORM_EXPIRED_KEY = "form.expired"
"""The message key, under "form", for a submission token or device cookie the form can't
use (malformed, missing, or an expired submission): the page serves a fresh form and token."""


class InvalidDetails(DomainError):
    def __init__(self, errors: FieldErrors) -> None:
        if not errors:
            raise ValueError("InvalidDetails needs at least one field error")
        super().__init__("The drop-off has errors.")
        self.errors: FieldErrors = MappingProxyType(dict(errors))


class NotFound(DomainError):
    def __init__(self, id: DropOffId | LoadId | NoteId) -> None:
        if isinstance(id, LoadId):
            super().__init__(f"Load {id} doesn't exist.")
        elif isinstance(id, NoteId):
            super().__init__(f"Note {id} doesn't exist.")
        else:
            super().__init__(f"{id} doesn't exist.")
        self.id = id


class NotWaiting(DomainError):
    def __init__(self, drop_off_id: DropOffId, state: str) -> None:
        super().__init__(f"{drop_off_id} isn't waiting: it is {state}.")
        self.drop_off_id = drop_off_id


class DropOffNotDeletable(DomainError):
    def __init__(self, drop_off_id: DropOffId, state: str) -> None:
        super().__init__(f"{drop_off_id} is {state}: only a waiting drop-off can be deleted.")
        self.drop_off_id = drop_off_id


class AlreadyInLoad(DomainError):
    def __init__(self, drop_off_id: DropOffId, load_id: LoadId) -> None:
        super().__init__(f"{drop_off_id} is already in load {load_id}.")
        self.drop_off_id = drop_off_id
        self.load_id = load_id


class NotInLoad(DomainError):
    def __init__(self, drop_off_id: DropOffId, load_id: LoadId) -> None:
        super().__init__(f"{drop_off_id} isn't in load {load_id}.")
        self.drop_off_id = drop_off_id
        self.load_id = load_id


class LoadNotLoading(DomainError):
    def __init__(self, load_id: LoadId, status: str) -> None:
        super().__init__(f"Load {load_id} is {status}: nothing can be added or removed.")
        self.load_id = load_id


class LoadFull(DomainError):
    def __init__(self, load_id: LoadId, capacity: int) -> None:
        super().__init__(f"Load {load_id} already holds {capacity} drop-offs.")
        self.load_id = load_id


class EmptyLoad(DomainError):
    def __init__(self, load_id: LoadId) -> None:
        super().__init__(f"Load {load_id} is empty: add a drop-off before firing.")
        self.load_id = load_id


class WrongLoadStatus(DomainError):
    def __init__(self, load_id: LoadId, status: str, expected: str) -> None:
        super().__init__(f"Load {load_id} is {status}, not {expected}.")
        self.load_id = load_id


class AlreadyFired(DomainError):
    def __init__(self, load_id: LoadId) -> None:
        super().__init__(f"Load {load_id} is already fired; nothing was sent again.")
        self.load_id = load_id


class FiredLoadNotDeletable(DomainError):
    def __init__(self, load_id: LoadId) -> None:
        super().__init__(f"Load {load_id} is fired: a fired load can't be deleted.")
        self.load_id = load_id


class FiringTypeMismatch(DomainError):
    """Both firing types are kept by ID, so a page can name them from the studio's items."""

    def __init__(
        self, drop_off_id: DropOffId, drop_off_firing_type: ItemId, load_firing_type: ItemId
    ) -> None:
        super().__init__(
            f"{drop_off_id}'s firing type is {drop_off_firing_type}; this load's is {load_firing_type}."
        )
        self.drop_off_id = drop_off_id
        self.drop_off_firing_type = drop_off_firing_type
        self.load_firing_type = load_firing_type


class FiringTypeLocked(DomainError):
    def __init__(self, load_id: LoadId) -> None:
        super().__init__(f"Load {load_id} has drop-offs in it: remove them before changing its firing type.")
        self.load_id = load_id


class InvalidRecord(DomainError):
    """A firing record with refused fields (#42). Unlike `InvalidDetails`' keys, `errors`
    maps each field's name to its message, fixed text built from the limits, as
    `InvalidSetting`'s is: never the value sent."""

    def __init__(self, errors: Mapping[str, str]) -> None:
        if not errors:
            raise ValueError("InvalidRecord needs at least one field error")
        count = len(errors)
        fields = "1 field needs" if count == 1 else f"{count} fields need"
        super().__init__(f"Check the firing record: {fields} fixing.")
        self.errors: Mapping[str, str] = MappingProxyType(dict(errors))


class InvalidNote(DomainError):
    """A firing note with refused fields (#17). As `InvalidRecord`'s, `errors` maps each
    field's name to its message, fixed text: never the note's text or anything sent."""

    def __init__(self, errors: Mapping[str, str]) -> None:
        if not errors:
            raise ValueError("InvalidNote needs at least one field error")
        super().__init__("Check the note.")
        self.errors: Mapping[str, str] = MappingProxyType(dict(errors))


class LoadNotNotable(DomainError):
    def __init__(self, load_id: LoadId) -> None:
        super().__init__(f"Load {load_id} was deleted: it takes no notes.")
        self.load_id = load_id


class StepNotReached(DomainError):
    def __init__(self, load_id: LoadId, step: str) -> None:
        super().__init__(f"Load {load_id} hasn't reached {step}, or its time wasn't recorded.")
        self.load_id = load_id


class StepTimeOutOfOrder(DomainError):
    def __init__(self, load_id: LoadId, step: str) -> None:
        super().__init__(
            f"Load {load_id} can't have started firing before it was started, "
            "or have been fired before it started firing."
        )
        self.load_id = load_id
        self.step = step


class StepTimeInFuture(DomainError):
    def __init__(self, load_id: LoadId) -> None:
        super().__init__("That time is in the future.")
        self.load_id = load_id


class StepTimeTooEarly(DomainError):
    def __init__(self, load_id: LoadId, year: int) -> None:
        super().__init__(f"Enter a time from {year} on.")
        self.load_id = load_id


class InvalidLogRange(DomainError):
    def __init__(self) -> None:
        super().__init__(
            f"Choose a date range of at most {LOG_RANGE_MAX_YEARS} years, ending after it starts."
        )


class TooManyNotesToMove(DomainError):
    """A kiln change moves the load's notes in its commit, and a delete removes them in its
    own; the commit holds at most `limit` of them. `deleting` says which was refused."""

    def __init__(self, load_id: LoadId, limit: int, *, deleting: bool = False) -> None:
        refused = (
            "it can't be deleted. Remove some of its notes first" if deleting else "its kiln can't be changed"
        )
        super().__init__(f"Load {load_id} has more than {limit} notes, so {refused}.")
        self.load_id = load_id


class MessageRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("This reason needs a message.")


class MessageTooLong(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"The message is longer than {limit:,} characters.")


class NotRejected(DomainError):
    def __init__(self, drop_off_id: DropOffId) -> None:
        super().__init__(f"{drop_off_id} isn't rejected.")
        self.drop_off_id = drop_off_id


class UndoTooLate(DomainError):
    def __init__(self, drop_off_id: DropOffId) -> None:
        super().__init__(f"{drop_off_id} was rejected on an earlier day; undo works only the same day.")
        self.drop_off_id = drop_off_id


class SendingAddressOutsideAsmbly(DomainError):
    def __init__(self, domain: str) -> None:
        super().__init__(f"Use an address at {domain}.")


class InvalidSetting(DomainError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class UnknownItem(DomainError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"That {kind} doesn't exist.")


class ItemRetired(DomainError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is retired and can't be picked.")


class ItemInUse(DomainError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name} is in use by a drop-off, a load, a default program or a note, so it stays retired."
        )


class DuplicateItem(DomainError):
    def __init__(self, kind: str, name: str) -> None:
        super().__init__(f"There is already a {kind} called {name}.")


class EmailNotRetryable(DomainError):
    def __init__(self) -> None:
        super().__init__("That email isn't failed.")


class NoStaffEmail(DomainError):
    def __init__(self) -> None:
        super().__init__("Your sign-in has no email address, so a test email can't be sent.")


class TestEmailFailed(DomainError):
    """The code is a provider's error code (`ports.errors.error_code`'s shape), never text."""

    __test__ = False  # not a pytest test class, despite its name

    def __init__(self, code: str) -> None:
        super().__init__(f"The test email didn't send ({code}). Nothing was saved.")
        self.code = code


class TooManySubmissions(DomainError):
    def __init__(self) -> None:
        super().__init__("Too many drop-offs from here in the last few minutes. Try again later.")


class SubmissionNotFound(DomainError):
    """No such submission, or it has expired (the ID page). Fixed text: it names nothing."""

    def __init__(self) -> None:
        super().__init__("That page has expired.")
