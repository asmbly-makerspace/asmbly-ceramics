from types import MappingProxyType

import pytest

from asmbly_ceramics.domain import errors
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId

AC12 = DropOffId(12)
L4 = LoadId(4)

EXPECTED: list[tuple[errors.DomainError, str]] = [
    (errors.InvalidDetails({"email": "email.invalid"}), "The drop-off has errors."),
    (errors.NotFound(AC12), "AC-12 doesn't exist."),
    (errors.NotFound(L4), "Load L-4 doesn't exist."),
    (errors.NotWaiting(AC12, "fired"), "AC-12 isn't waiting: it is fired."),
    (errors.AlreadyInLoad(AC12, L4), "AC-12 is already in load L-4."),
    (errors.NotInLoad(AC12, L4), "AC-12 isn't in load L-4."),
    (errors.LoadNotLoading(L4, "firing"), "Load L-4 is firing: nothing can be added or removed."),
    (errors.LoadFull(L4, 48), "Load L-4 already holds 48 drop-offs."),
    (errors.EmptyLoad(L4), "Load L-4 is empty: add a drop-off before firing."),
    (errors.WrongLoadStatus(L4, "loading", "firing"), "Load L-4 is loading, not firing."),
    (errors.AlreadyFired(L4), "Load L-4 is already fired; nothing was sent again."),
    (
        errors.FiringTypeMismatch(DropOffId(61), ItemId("bisque"), ItemId("cone-6-glaze")),
        "AC-61's firing type is bisque; this load's is cone-6-glaze.",
    ),
    (
        errors.FiringTypeLocked(L4),
        "Load L-4 has drop-offs in it: remove them before changing its firing type.",
    ),
    (errors.MessageRequired(), "This reason needs a message."),
    (errors.MessageTooLong(1000), "The message is longer than 1,000 characters."),
    (errors.NotRejected(AC12), "AC-12 isn't rejected."),
    (
        errors.UndoTooLate(AC12),
        "AC-12 was rejected on an earlier day; undo works only the same day.",
    ),
    (errors.SendingAddressOutsideAsmbly("asmbly.org"), "Use an address at asmbly.org."),
    (errors.InvalidSetting("pickup_window_days", "Enter a number of days from 1 to 90."), "Enter a number"),
    (errors.UnknownItem("kiln"), "That kiln doesn't exist."),
    (errors.ItemRetired("Vulcan"), "Vulcan is retired and can't be picked."),
    (errors.ItemInUse("Helios"), "Helios is used by a drop-off or a load: retire it instead."),
    (errors.DuplicateItem("kiln", "Helios"), "There is already a kiln called Helios."),
    (errors.EmailNotRetryable(), "That email isn't failed."),
    (errors.NoStaffEmail(), "Your sign-in has no email address, so a test email can't be sent."),
    (errors.TestEmailFailed("MessageRejected"), "The test email didn't send (MessageRejected)."),
    (errors.TooManySubmissions(), "Too many drop-offs from here in the last few minutes. Try again later."),
    (errors.SubmissionNotFound(), "That page has expired."),
]


def test_every_domain_error_class_is_checked() -> None:
    classes = {
        value
        for value in vars(errors).values()
        if isinstance(value, type)
        and issubclass(value, errors.DomainError)
        and value is not errors.DomainError
    }
    assert classes == {type(error) for error, _ in EXPECTED}


@pytest.mark.parametrize(("error", "expected"), EXPECTED, ids=lambda value: type(value).__name__)
def test_every_domain_error_message_is_safe(error: errors.DomainError, expected: str) -> None:
    # Built from IDs, states and item names only, each message holds those and nothing else.
    assert error.message.startswith(expected)
    assert str(error) == error.message
    assert "@" not in error.message


def test_invalid_details_holds_keys_not_values() -> None:
    error = errors.InvalidDetails({"email": "email.invalid", "photo.2": "photo.too_large"})
    assert dict(error.errors) == {"email": "email.invalid", "photo.2": "photo.too_large"}
    # Read only: a caller can't slip a field's value in afterwards.
    assert isinstance(error.errors, MappingProxyType)


def test_invalid_details_needs_an_error() -> None:
    with pytest.raises(ValueError, match="at least one"):
        errors.InvalidDetails({})


def test_errors_keep_the_ids_they_name() -> None:
    assert errors.NotFound(L4).id == L4
    mismatch = errors.FiringTypeMismatch(AC12, ItemId("bisque"), ItemId("glaze"))
    assert (mismatch.drop_off_id, mismatch.drop_off_firing_type, mismatch.load_firing_type) == (
        AC12,
        ItemId("bisque"),
        ItemId("glaze"),
    )
    assert errors.FiringTypeLocked(L4).load_id == L4
    assert errors.InvalidSetting("name", "Enter a name.").field == "name"
    assert errors.TestEmailFailed("Throttling").code == "Throttling"
