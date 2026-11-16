from types import MappingProxyType

import pytest

from asmbly_ceramics.domain import errors
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId, NoteId

AC12 = DropOffId(12)
L4 = LoadId(4)
N12 = NoteId(12)

EXPECTED: list[tuple[errors.DomainError, str]] = [
    (errors.InvalidDetails({"email": "email.invalid"}), "The drop-off has errors."),
    (errors.NotFound(AC12), "AC-12 doesn't exist."),
    (errors.NotFound(L4), "Load L-4 doesn't exist."),
    (errors.NotFound(N12), "Note N-12 doesn't exist."),
    (errors.NotWaiting(AC12, "fired"), "AC-12 isn't waiting: it is fired."),
    (
        errors.DropOffNotDeletable(AC12, "in load"),
        "AC-12 is in load: only a waiting drop-off can be deleted.",
    ),
    (errors.AlreadyInLoad(AC12, L4), "AC-12 is already in load L-4."),
    (errors.NotInLoad(AC12, L4), "AC-12 isn't in load L-4."),
    (errors.LoadNotLoading(L4, "firing"), "Load L-4 is firing: nothing can be added or removed."),
    (errors.LoadFull(L4, 48), "Load L-4 already holds 48 drop-offs."),
    (errors.EmptyLoad(L4), "Load L-4 is empty: add a drop-off before firing."),
    (errors.WrongLoadStatus(L4, "loading", "firing"), "Load L-4 is loading, not firing."),
    (errors.AlreadyFired(L4), "Load L-4 is already fired; nothing was sent again."),
    (errors.FiredLoadNotDeletable(L4), "Load L-4 is fired: a fired load can't be deleted."),
    (
        errors.FiringTypeMismatch(DropOffId(61), ItemId("bisque"), ItemId("cone-6-glaze")),
        "AC-61's firing type is bisque; this load's is cone-6-glaze.",
    ),
    (
        errors.FiringTypeLocked(L4),
        "Load L-4 has drop-offs in it: remove them before changing its firing type.",
    ),
    (errors.InvalidRecord({"max_temp_f": "Enter a whole number from 0 to 2,500."}), "Check the firing"),
    (errors.InvalidNote({"text": "Write the note."}), "Check the note."),
    (errors.LoadNotNotable(L4), "Load L-4 was deleted: it takes no notes."),
    (errors.StepNotReached(L4, "firing"), "Load L-4 hasn't reached firing, or its time wasn't recorded."),
    (
        errors.StepTimeOutOfOrder(L4, "firing"),
        "Load L-4 can't have started firing before it was started, "
        "or have been fired before it started firing.",
    ),
    (errors.StepTimeInFuture(L4), "That time is in the future."),
    (errors.StepTimeTooEarly(L4, 2000), "Enter a time from 2000 on."),
    (errors.InvalidLogRange(), "Choose a date range of at most 5 years, ending after it starts."),
    (
        errors.TooManyNotesToMove(L4, 98),
        "Load L-4 has more than 98 notes, so its kiln can't be changed.",
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
    (
        errors.ItemInUse("Helios"),
        "Helios is in use by a drop-off, a load or a default program, so it stays retired.",
    ),
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


def test_invalid_note_holds_messages_and_is_read_only() -> None:
    error = errors.InvalidNote({"text": "Write the note.", "glaze_types": "Pick each glaze type once."})
    assert dict(error.errors) == {"text": "Write the note.", "glaze_types": "Pick each glaze type once."}
    assert isinstance(error.errors, MappingProxyType)
    with pytest.raises(ValueError, match="at least one"):
        errors.InvalidNote({})


def test_errors_keep_the_ids_they_name() -> None:
    assert errors.NotFound(L4).id == L4
    assert errors.NotFound(N12).id == N12
    assert errors.LoadNotNotable(L4).load_id == L4
    mismatch = errors.FiringTypeMismatch(AC12, ItemId("bisque"), ItemId("glaze"))
    assert (mismatch.drop_off_id, mismatch.drop_off_firing_type, mismatch.load_firing_type) == (
        AC12,
        ItemId("bisque"),
        ItemId("glaze"),
    )
    assert errors.FiringTypeLocked(L4).load_id == L4
    assert errors.InvalidSetting("name", "Enter a name.").field == "name"
    assert errors.TestEmailFailed("Throttling").code == "Throttling"


def test_invalid_record_counts_its_fields_and_is_read_only() -> None:
    one = errors.InvalidRecord({"cost": "Enter the cost in dollars."})
    two = errors.InvalidRecord({"cost": "Enter the cost in dollars.", "speed": "Pick a speed."})
    assert one.message == "Check the firing record: 1 field needs fixing."
    assert two.message == "Check the firing record: 2 fields need fixing."
    assert isinstance(two.errors, MappingProxyType)
    with pytest.raises(ValueError, match="at least one"):
        errors.InvalidRecord({})
