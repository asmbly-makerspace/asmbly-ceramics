"""`PreviewRejection`, `RejectDropOff` and `UndoRejection` (#5), against the fakes.

Asserts on what was stored and logged, not only on what was returned. The person and the
message are made up (`tests/domain/builders.py`).
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import pytest

from asmbly_ceramics.adapters.memory.records import MemoryRecords
from asmbly_ceramics.domain.dropoff import DropOff, DropOffState, Rejection
from asmbly_ceramics.domain.email import (
    Email,
    EmailKind,
    EmailStatus,
    claim,
    mark_failed,
    mark_sent,
    new_email,
    rejection_occasion,
)
from asmbly_ceramics.domain.errors import (
    ItemRetired,
    MessageRequired,
    MessageTooLong,
    NotFound,
    NotRejected,
    NotWaiting,
    UndoTooLate,
    UnknownItem,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.limits import MESSAGE_MAX, STUDIO_TZ
from asmbly_ceramics.domain.load import add_to_load
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.domain.studio import ItemStatus
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import Conflict, Put, Update
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.reject import (
    RejectDropOff,
    RejectionEmail,
    RejectRequest,
    Undone,
    UndoRejection,
    UndoRequest,
)
from asmbly_ceramics.use_cases.studio import CurrentStudio
from tests.domain.builders import (
    NOW,
    STAFF,
    TEST_EMAIL,
    TEST_MESSAGE,
    a_drop_off,
    a_load,
    a_sending_address,
    an_address,
)
from tests.use_cases.conftest import World

AC_1 = DropOffId(1)
OTHER = ItemId("other")
GLAZE_ISSUES = ItemId("has-glaze-issues")
STAFF_MEMBER = StaffMember(STAFF, an_address("kiln.tech"))


def console_src(ref: PhotoRef) -> str:
    return f"/console/drop-offs/{ref.drop_off_id}/photos/{ref.index}"


def a_reject(
    reason: ItemId = OTHER, message: str = TEST_MESSAGE, *, version: int = 1, number: int = 1
) -> RejectRequest:
    return RejectRequest(DropOffId(number), reason, message, version, STAFF_MEMBER)


def an_undo(version: int = 2) -> UndoRequest:
    return UndoRequest(AC_1, version, STAFF_MEMBER)


def stored(world: World, *drop_offs: DropOff) -> None:
    world.records.commit([Put(drop_off) for drop_off in drop_offs])


def waiting(world: World) -> DropOff:
    """AC-1, waiting, stored at version 1, with the studio already seeded."""
    world.studio()
    stored(world, a_drop_off(1))
    return world.records.drop_off(AC_1) or pytest.fail("not stored")


def the_rejected_email(world: World) -> Email:
    [email] = [e for e in world.records.emails_for(AC_1) if e.kind is EmailKind.REJECTED]
    return email


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, object]]:
    return [vars(r) for r in caplog.records if r.getMessage() == name]


def set_email(world: World, email: Email) -> None:
    world.records.commit([Update(email)])
    world.records.commits.clear()


# Preview


def test_preview_shows_the_email_with_reason_and_message_and_saves_nothing(world: World) -> None:
    waiting(world)
    commits = len(world.records.commits)

    email = world.preview(a_reject(GLAZE_ISSUES, "Smooth the <b>base</b>."), console_src)

    assert email.subject == "Your drop-off needs attention (AC-1)"
    assert email.drop_off_id == AC_1
    assert "Has glaze issues" in email.html
    assert "Smooth the &lt;b&gt;base&lt;/b&gt;." in email.html
    assert 'src="/console/drop-offs/AC-1/photos/1"' in email.html
    assert 'src="/console/drop-offs/AC-1/photos/2"' in email.html
    assert "Smooth the <b>base</b>." in email.text
    # Nothing stored: the drop-off is still waiting at the version the page saw.
    assert len(world.records.commits) == commits
    assert world.records.drop_off(AC_1) == waiting_again(world)
    assert world.records.emails_for(AC_1) == []


def waiting_again(world: World) -> DropOff:
    drop_off = world.records.drop_off(AC_1)
    assert drop_off is not None
    assert (drop_off.state, drop_off.version, drop_off.rejection) == (DropOffState.WAITING, 1, None)
    return drop_off


def test_the_preview_is_the_email_that_is_sent(world: World) -> None:
    """The same template and the same settings: the sent email differs only in where its
    images point."""
    waiting(world)
    preview = world.preview(a_reject(), console_src)
    rejected = world.reject(a_reject())

    sent = world.composer.rejected(rejected, world.studio(), console_src)

    assert (sent.subject, sent.html, sent.text) == (preview.subject, preview.html, preview.text)


def test_the_preview_logs_nothing(world: World, caplog: pytest.LogCaptureFixture) -> None:
    waiting(world)
    world.studio()
    caplog.clear()

    world.preview(a_reject(), console_src)

    assert caplog.records == []


@pytest.mark.parametrize("message", ["", "  \r\n "])
def test_preview_refuses_other_without_a_message(world: World, message: str) -> None:
    waiting(world)

    with pytest.raises(MessageRequired):
        world.preview(a_reject(OTHER, message), console_src)


def test_preview_refuses_a_message_over_1000_characters(world: World) -> None:
    waiting(world)

    with pytest.raises(MessageTooLong):
        world.preview(a_reject(OTHER, "x" * (MESSAGE_MAX + 1)), console_src)
    world.preview(a_reject(OTHER, "x" * MESSAGE_MAX), console_src)


def test_preview_allows_no_message_for_a_reason_that_needs_none(world: World) -> None:
    waiting(world)

    email = world.preview(a_reject(GLAZE_ISSUES, ""), console_src)

    assert "Has glaze issues" in email.html


def test_preview_refuses_what_reject_refuses(world: World) -> None:
    stored(world, a_drop_off(1, DropOffState.IN_LOAD))

    with pytest.raises(NotWaiting, match="AC-1 isn't waiting: it is in load"):
        world.preview(a_reject(), console_src)
    with pytest.raises(NotFound):
        world.preview(a_reject(number=9), console_src)
    with pytest.raises(Conflict):
        world.preview(a_reject(version=7), console_src)


# Reject


def test_reject_stores_the_rejection_and_queues_one_email(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    waiting(world)

    returned = world.reject(a_reject(OTHER, f"  {TEST_MESSAGE}\r\n"))

    stored_drop_off = world.records.drop_off(AC_1)
    assert returned == stored_drop_off
    assert returned.state is DropOffState.REJECTED
    assert returned.version == 2
    assert returned.rejection == Rejection(OTHER, TEST_MESSAGE, STAFF, NOW)
    [email] = world.records.emails_for(AC_1)
    assert (email.kind, email.status, email.occasion) == (
        EmailKind.REJECTED,
        EmailStatus.PENDING,
        rejection_occasion(NOW),
    )
    assert world.mailer.sent == []  # queued, not sent: the mailer sends from the outbox
    # One commit holds both: no rejection without its email, or the other way round.
    [commit] = world.records.commits[-1:]
    assert [type(change.item).__name__ for change in commit] == ["DropOff", "Email"]
    [event] = events(caplog, "drop_off_rejected")
    assert (event["drop_off_id"], event["user"], event["reason"]) == ("AC-1", STAFF, "other")


@pytest.mark.parametrize("reason", ["raku", "", "AC-1"])
def test_reject_with_an_unknown_reason_is_refused(world: World, reason: str) -> None:
    waiting(world)

    with pytest.raises(UnknownItem, match="That reason doesn't exist"):
        world.reject(a_reject(ItemId(reason)))
    waiting_again(world)
    assert world.records.emails_for(AC_1) == []


def test_reject_with_a_retired_reason_is_refused(world: World) -> None:
    studio = world.studio()
    reasons = tuple(
        replace(item, status=ItemStatus.RETIRED) if item.id == GLAZE_ISSUES else item
        for item in studio.reasons
    )
    world.records.commit([Update(replace(studio, reasons=reasons))])
    waiting(world)

    with pytest.raises(ItemRetired):
        world.reject(a_reject(GLAZE_ISSUES))
    waiting_again(world)


def test_a_rejected_drop_off_leaves_the_waiting_list(world: World) -> None:
    waiting(world)
    stored(world, a_drop_off(2))

    rejected = world.reject(a_reject())

    assert [str(row.drop_off.id) for row in world.waiting().rows] == ["AC-2"]
    with pytest.raises(NotWaiting):
        add_to_load(a_load(1), rejected, confirmed=False)


def test_reject_with_a_stale_version_is_a_conflict_and_stores_nothing(world: World) -> None:
    waiting(world)

    with pytest.raises(Conflict) as refused:
        world.reject(a_reject(version=0))

    assert refused.value.ids == ("AC-1",)
    waiting_again(world)
    assert world.records.emails_for(AC_1) == []


def test_rejecting_twice_is_refused(world: World) -> None:
    waiting(world)
    world.reject(a_reject())

    with pytest.raises(NotWaiting):
        world.reject(a_reject(version=2))
    assert len(world.records.emails_for(AC_1)) == 1


def test_reject_an_unknown_drop_off_is_not_found(world: World) -> None:
    with pytest.raises(NotFound):
        world.reject(a_reject(number=9))


# Undo


def test_undo_the_same_day_returns_it_to_waiting_and_sends_nothing(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    waiting(world)
    world.reject(a_reject())
    world.clock.advance(timedelta(hours=2))
    world.records.commits.clear()

    undone = world.undo(an_undo())

    assert undone == Undone(
        world.records.drop_off(AC_1) or pytest.fail("not stored"), RejectionEmail.CANCELLED
    )
    assert (undone.drop_off.state, undone.drop_off.rejection, undone.drop_off.version) == (
        DropOffState.WAITING,
        None,
        3,
    )
    assert not undone.contact_the_person
    assert the_rejected_email(world).status is EmailStatus.CANCELLED
    # One commit: the drop-off and the cancelled email; nothing new queued or sent.
    [commit] = world.records.commits
    assert all(isinstance(change, Update) for change in commit)
    assert world.mailer.sent == []
    assert [str(row.drop_off.id) for row in world.waiting().rows] == ["AC-1"]
    [event] = events(caplog, "rejection_undone")
    assert (event["drop_off_id"], event["user"], event["outcome"]) == ("AC-1", STAFF, "cancelled")


def test_undo_cancels_the_rejection_email_if_still_pending(world: World) -> None:
    waiting(world)
    world.reject(a_reject())

    assert world.undo(an_undo()).email is RejectionEmail.CANCELLED
    assert the_rejected_email(world).status is EmailStatus.CANCELLED


def test_undo_while_sending_cancels_and_says_it_may_have_gone(world: World) -> None:
    """The drop-off as read back with its rejection time in another offset still finds the
    email: the key is `rejection_occasion`'s."""
    austin = NOW.astimezone(STUDIO_TZ)
    drop_off = replace(
        a_drop_off(1, DropOffState.REJECTED), rejection=Rejection(OTHER, TEST_MESSAGE, STAFF, austin)
    )
    stored(world, drop_off)
    email = claim(new_email(AC_1, EmailKind.REJECTED, NOW, rejection_occasion(NOW)), NOW)
    world.records.commit([Put(email)])

    undone = world.undo(an_undo(version=1))

    assert undone.email is RejectionEmail.MAY_HAVE_GONE
    assert undone.contact_the_person
    assert the_rejected_email(world).status is EmailStatus.CANCELLED


def test_undo_after_the_email_was_sent_says_so(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    waiting(world)
    world.reject(a_reject())
    set_email(world, mark_sent(claim(the_rejected_email(world), NOW), NOW))

    undone = world.undo(an_undo())

    assert undone.email is RejectionEmail.SENT
    assert undone.contact_the_person
    assert undone.drop_off.state is DropOffState.WAITING
    assert the_rejected_email(world).status is EmailStatus.SENT
    [commit] = world.records.commits
    assert [type(change.item).__name__ for change in commit] == ["DropOff"]
    assert [e["outcome"] for e in events(caplog, "rejection_undone")] == ["sent"]


def test_undo_after_the_email_failed_says_it_never_went(world: World) -> None:
    waiting(world)
    world.reject(a_reject())
    set_email(world, mark_failed(claim(the_rejected_email(world), NOW), "Throttling"))

    undone = world.undo(an_undo())

    assert undone.email is RejectionEmail.NOT_SENT
    assert not undone.contact_the_person
    assert the_rejected_email(world).status is EmailStatus.FAILED
    assert world.view(AC_1).emails_needing_attention == ()


def test_undo_without_a_stored_email_says_it_never_went(world: World) -> None:
    stored(world, a_drop_off(1, DropOffState.REJECTED))

    undone = world.undo(an_undo(version=1))

    assert undone.email is RejectionEmail.NOT_SENT
    assert undone.drop_off.state is DropOffState.WAITING


def test_undo_the_next_day_is_refused(world: World) -> None:
    waiting(world)
    world.reject(a_reject())
    world.clock.advance(timedelta(days=1))
    world.records.commits.clear()

    with pytest.raises(UndoTooLate, match="AC-1 was rejected on an earlier day"):
        world.undo(an_undo())

    assert world.records.commits == []
    assert the_rejected_email(world).status is EmailStatus.PENDING


def test_undo_refuses_a_drop_off_that_isnt_rejected(world: World) -> None:
    waiting(world)

    with pytest.raises(NotRejected):
        world.undo(an_undo(version=1))


def test_undo_with_a_stale_version_is_a_conflict(world: World) -> None:
    waiting(world)
    world.reject(a_reject())
    world.records.commits.clear()

    with pytest.raises(Conflict):
        world.undo(an_undo(version=1))
    with pytest.raises(NotFound):
        world.undo(UndoRequest(DropOffId(9), 1, STAFF_MEMBER))
    assert world.records.commits == []


def test_a_rejection_after_an_undo_queues_its_own_email(world: World) -> None:
    waiting(world)
    world.reject(a_reject())
    world.undo(an_undo())
    world.clock.advance(timedelta(minutes=5))

    world.reject(a_reject(version=3))

    emails = world.records.emails_for(AC_1)
    assert [(e.status, e.occasion) for e in emails] == [
        (EmailStatus.CANCELLED, rejection_occasion(NOW)),
        (EmailStatus.PENDING, rejection_occasion(NOW + timedelta(minutes=5))),
    ]


# Requests


def test_the_request_repr_holds_no_message(world: World) -> None:
    text = repr(a_reject(OTHER, TEST_MESSAGE)) + repr(an_undo())

    assert TEST_MESSAGE not in text
    assert TEST_EMAIL not in text
    assert "kiln.tech" not in text
    assert "AC-1" in text or "number=1" in text


class LosesDropOffs(MemoryRecords):
    """Can't read the drop-off back once a commit of it has landed: a throttled read."""

    def drop_off(self, id: DropOffId) -> DropOff | None:
        if self.commits[-1:] and isinstance(self.commits[-1][0].item, DropOff):
            raise RecordsUnavailable("ThrottlingException")
        return super().drop_off(id)


def test_reject_still_returns_the_rejection_when_the_read_back_fails(world: World) -> None:
    records = LosesDropOffs()
    records.commit([Put(a_drop_off(1))])
    records.commits.clear()
    reject = RejectDropOff(records, world.clock, CurrentStudio(records, world.clock, a_sending_address()))

    rejected = reject(a_reject())

    assert (rejected.state, rejected.version) == (DropOffState.REJECTED, 2)
    assert rejected.rejection == Rejection(OTHER, TEST_MESSAGE, STAFF, NOW)
    [email] = records.emails_for(AC_1)
    assert email.status is EmailStatus.PENDING


class MissesDropOffs(MemoryRecords):
    """Reads back no drop-off once a commit of it has landed: a read that missed the item."""

    def drop_off(self, id: DropOffId) -> DropOff | None:
        if self.commits[-1:] and isinstance(self.commits[-1][0].item, DropOff):
            return None
        return super().drop_off(id)


def test_reject_and_undo_still_answer_when_the_read_back_misses_the_drop_off(world: World) -> None:
    records = MissesDropOffs()
    studio = CurrentStudio(records, world.clock, a_sending_address())

    rejected = RejectDropOff(records, world.clock, studio)(a_reject_after_storing(records))

    assert (rejected.state, rejected.version) == (DropOffState.REJECTED, 2)
    [email] = records.emails_for(AC_1)
    assert email.status is EmailStatus.PENDING

    records.commit([Update(email)])  # a later commit of something else: the drop-off reads again
    undone = UndoRejection(records, world.clock)(an_undo())

    assert undone.email is RejectionEmail.CANCELLED
    assert (undone.drop_off.state, undone.drop_off.version, undone.drop_off.rejection) == (
        DropOffState.WAITING,
        3,
        None,
    )
    assert records.drop_off(AC_1) is None  # the read-back really missed


@pytest.mark.parametrize("use", ["preview", "reject", "undo"])
def test_a_failed_first_read_is_records_unavailable_and_stores_and_logs_nothing(
    world: World, caplog: pytest.LogCaptureFixture, use: str
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    waiting(world)
    if use == "undo":
        world.reject(a_reject())
    world.records.commits.clear()
    caplog.clear()
    world.records.fail_reads_with = RecordsUnavailable("ThrottlingException")

    calls: dict[str, Callable[[], object]] = {
        "preview": lambda: world.preview(a_reject(), console_src),
        "reject": lambda: world.reject(a_reject()),
        "undo": lambda: world.undo(an_undo()),
    }

    with pytest.raises(RecordsUnavailable):
        calls[use]()

    assert world.records.commits == []
    assert caplog.records == []


def test_reject_losing_the_commit_is_a_conflict_and_logs_nothing(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    waiting(world)
    world.records.fail_next_commit_with = Conflict(["AC-1"])

    with pytest.raises(Conflict):
        world.reject(a_reject())

    waiting_again(world)
    assert world.records.emails_for(AC_1) == []
    assert events(caplog, "drop_off_rejected") == []


def test_reject_and_undo_when_records_are_unavailable_store_and_log_nothing(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    waiting(world)
    world.records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
    with pytest.raises(RecordsUnavailable):
        world.reject(a_reject())
    waiting_again(world)

    world.reject(a_reject())
    world.records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
    with pytest.raises(RecordsUnavailable):
        world.undo(an_undo())

    stored_drop_off = world.records.drop_off(AC_1)
    assert stored_drop_off is not None
    assert stored_drop_off.state is DropOffState.REJECTED
    assert the_rejected_email(world).status is EmailStatus.PENDING
    assert events(caplog, "rejection_undone") == []


class ClaimsOnRead(MemoryRecords):
    """A mailer claims the rejected email just after the undo reads it."""

    def email(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> Email | None:
        read = super().email(drop_off_id, kind, occasion)
        if read is not None and read.status is EmailStatus.PENDING:
            self.commit([Update(claim(read, NOW))])
        return read


def test_undo_loses_to_a_mailer_that_claimed_the_email_first(world: World) -> None:
    records = ClaimsOnRead()
    studio = CurrentStudio(records, world.clock, a_sending_address())
    RejectDropOff(records, world.clock, studio)(a_reject_after_storing(records))

    with pytest.raises(Conflict):
        UndoRejection(records, world.clock)(an_undo())

    drop_off = records.drop_off(AC_1)
    assert drop_off is not None
    assert drop_off.state is DropOffState.REJECTED  # nothing of the undo was stored
    [email] = records.emails_for(AC_1)
    assert email.status is EmailStatus.SENDING


def a_reject_after_storing(records: MemoryRecords) -> RejectRequest:
    records.commit([Put(a_drop_off(1))])
    return a_reject()


class LosesAfterUndo(MemoryRecords):
    """Can't read the drop-off back once the undo has stored it (waiting again, version 3)."""

    def drop_off(self, id: DropOffId) -> DropOff | None:
        stored = super().drop_off(id)
        if stored is not None and stored.state is DropOffState.WAITING and stored.version >= 3:
            raise RecordsUnavailable("ThrottlingException")
        return stored


def test_undo_still_says_the_email_went_when_the_read_back_fails(world: World) -> None:
    records = LosesAfterUndo()
    studio = CurrentStudio(records, world.clock, a_sending_address())
    RejectDropOff(records, world.clock, studio)(a_reject_after_storing(records))
    [email] = records.emails_for(AC_1)
    records.commit([Update(mark_sent(claim(email, NOW), NOW))])

    undone = UndoRejection(records, world.clock)(an_undo())

    assert undone.email is RejectionEmail.SENT
    assert undone.contact_the_person
    assert (undone.drop_off.state, undone.drop_off.version, undone.drop_off.rejection) == (
        DropOffState.WAITING,
        3,
        None,
    )
    with pytest.raises(RecordsUnavailable):
        records.drop_off(AC_1)  # the read-back really failed
