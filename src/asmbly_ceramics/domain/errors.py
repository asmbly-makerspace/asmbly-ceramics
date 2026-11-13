"""Refusals. Every message is safe to show to staff and to log: it names IDs, states and
setting names, never a person's name, email, phone or message."""

from collections.abc import Mapping

FieldErrors = Mapping[str, str]  # field name -> message key


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
        super().__init__("The drop-off has errors.")
        self.errors = dict(errors)


class NotFound(DomainError): ...  # "AC-12 doesn't exist." / "Load L-4 doesn't exist."


class NotWaiting(DomainError): ...  # "AC-12 isn't waiting: it is fired."


class AlreadyInLoad(DomainError): ...  # "AC-12 is already in load L-4."


class NotInLoad(DomainError): ...  # "AC-12 isn't in load L-4."


class LoadNotLoading(DomainError): ...  # "Load L-4 is firing: nothing can be added or removed."


class LoadFull(DomainError): ...  # "Load L-4 already holds 48 drop-offs."


class EmptyLoad(DomainError): ...  # "Load L-4 is empty: add a drop-off before firing."


class WrongLoadStatus(DomainError): ...  # "Load L-4 is loading, not firing."


class AlreadyFired(DomainError): ...  # "Load L-4 is already fired; nothing was sent again."


class FiringTypeMismatch(DomainError):
    def __init__(self, message: str, drop_off_id: object) -> None:
        super().__init__(message)
        self.drop_off_id = drop_off_id


class MessageRequired(DomainError): ...


class MessageTooLong(DomainError): ...


class NotRejected(DomainError): ...


class UndoTooLate(DomainError): ...


class SendingAddressOutsideAsmbly(DomainError): ...


class InvalidSetting(DomainError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class UnknownItem(DomainError): ...


class ItemRetired(DomainError): ...


class ItemInUse(DomainError): ...


class DuplicateItem(DomainError): ...


class EmailNotRetryable(DomainError): ...


class TooManySubmissions(DomainError): ...
