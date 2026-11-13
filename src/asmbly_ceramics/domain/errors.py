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

from asmbly_ceramics.domain.ids import DropOffId, LoadId

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


class InvalidDetails(DomainError):
    def __init__(self, errors: FieldErrors) -> None:
        if not errors:
            raise ValueError("InvalidDetails needs at least one field error")
        super().__init__("The drop-off has errors.")
        self.errors: FieldErrors = MappingProxyType(dict(errors))


class NotFound(DomainError):
    def __init__(self, id: DropOffId | LoadId) -> None:
        if isinstance(id, LoadId):
            super().__init__(f"Load {id} doesn't exist.")
        else:
            super().__init__(f"{id} doesn't exist.")
        self.id = id


class NotWaiting(DomainError):
    def __init__(self, drop_off_id: DropOffId, state: str) -> None:
        super().__init__(f"{drop_off_id} isn't waiting: it is {state}.")
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


class FiringTypeMismatch(DomainError):
    def __init__(self, drop_off_id: DropOffId, drop_off_firing_type: str, load_firing_type: str) -> None:
        super().__init__(f"{drop_off_id} is {drop_off_firing_type}. This load is {load_firing_type}.")
        self.drop_off_id = drop_off_id


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
        super().__init__(f"{name} is used by a drop-off or a load: retire it instead.")


class DuplicateItem(DomainError):
    def __init__(self, kind: str, name: str) -> None:
        super().__init__(f"There is already a {kind} called {name}.")


class EmailNotRetryable(DomainError):
    def __init__(self) -> None:
        super().__init__("That email isn't failed.")


class TooManySubmissions(DomainError):
    def __init__(self) -> None:
        super().__init__("Too many drop-offs from this device. Try again later.")
