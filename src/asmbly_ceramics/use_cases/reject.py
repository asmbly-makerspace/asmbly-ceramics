"""Rejecting a drop-off with a reason and a message, its preview, and the same-day undo (#5).

The message is a person's words to another person: it never appears in a `repr`, an
error or a log. Logs carry the drop-off's ID, the staff username, the reason's item ID
and a fixed outcome.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from asmbly_ceramics.domain.dropoff import DropOff, reject, undo_rejection
from asmbly_ceramics.domain.email import EmailKind, EmailStatus, mark_cancelled, new_email, rejection_occasion
from asmbly_ceramics.domain.errors import NotFound, NotRejected
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.domain.studio import CatalogList, Studio
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.composer import ComposedEmail, Composer
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import Change, Conflict, Put, Records, Update
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.use_cases.studio import CurrentStudio


@dataclass(frozen=True, slots=True)
class RejectRequest:
    drop_off_id: DropOffId
    reason: ItemId
    message: str = field(repr=False)
    version: int  # the version the staff member saw
    staff: StaffMember


@dataclass(frozen=True, slots=True)
class UndoRequest:
    drop_off_id: DropOffId
    version: int
    staff: StaffMember


class RejectionEmail(StrEnum):
    """What became of the rejection email when the rejection was undone."""

    CANCELLED = "cancelled"  # it was pending: it never went
    # It was sending: cancelled, but a mailer already past its `is_still_rejected` check
    # may be sending it now.
    MAY_HAVE_GONE = "may_have_gone"
    SENT = "sent"
    # None was stored, or its send failed. A failed send is taken as not gone: whether a
    # FAILED email may still have left (a send that failed after SES took it) is phase 3's
    # call, with its mailer and its `mark_failed` reasons.
    NOT_SENT = "not_sent"


@dataclass(frozen=True, slots=True)
class Undone:
    drop_off: DropOff
    email: RejectionEmail

    @property
    def contact_the_person(self) -> bool:
        """The email went or may have: staff contact the person directly (#5)."""
        return self.email in (RejectionEmail.SENT, RejectionEmail.MAY_HAVE_GONE)


def _current(records: Records, id: DropOffId, version: int) -> DropOff:
    """The stored drop-off at the version the staff member saw: `NotFound`, or `Conflict`
    when someone else changed it since (the page says to reload)."""
    drop_off = records.drop_off(id)
    if drop_off is None:
        raise NotFound(id)
    if drop_off.version != version:
        raise Conflict([str(id)])
    return drop_off


def _rejected(records: Records, studio: Studio, request: RejectRequest, now: datetime) -> DropOff:
    """The stored drop-off with the domain's `reject` applied, not saved. `UnknownItem` for a
    reason the studio doesn't have; `reject`'s refusals otherwise."""
    drop_off = _current(records, request.drop_off_id, request.version)
    reason = studio.item(CatalogList.REASONS, request.reason)
    return reject(drop_off, reason, request.message, request.staff.username, now)


def _read_back(records: Records, id: DropOffId) -> DropOff | None:
    """The drop-off as stored after a commit, as the `Records` contract says to read it;
    `None` when it can't be read back (unavailable, or missing). The commit has landed
    either way, so the caller falls back on what it stored rather than fail."""
    try:
        return records.drop_off(id)
    except RecordsUnavailable:
        return None


class PreviewRejection:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio, composer: Composer) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio
        self._composer = composer

    def __call__(self, request: RejectRequest, image_src: Callable[[PhotoRef], str]) -> ComposedEmail:
        """The rejected email exactly as the template renders it with the current studio,
        with the photos at `image_src`'s addresses; every refusal `RejectDropOff` would
        raise, raised now. Stores nothing, logs nothing."""
        studio = self._studio()
        rejected = _rejected(self._records, studio, request, self._clock.now())
        return self._composer.rejected(rejected, studio, image_src)


class RejectDropOff:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def __call__(self, request: RejectRequest) -> DropOff:
        """Stores the rejection and queues its one email in one commit; returns the drop-off
        as stored. `NotFound`, `Conflict`, `UnknownItem`, `ItemRetired`, `NotWaiting`,
        `MessageRequired`, `MessageTooLong`."""
        studio = self._studio()
        now = self._clock.now()
        rejected = _rejected(self._records, studio, request, now)
        # `reject` stamps the rejection with `now`: the email's occasion is that time's.
        email = new_email(rejected.id, EmailKind.REJECTED, now, occasion=rejection_occasion(now))
        self._records.commit([Update(rejected), Put(email)])
        log_event(
            "drop_off_rejected",
            drop_off_id=str(rejected.id),
            user=request.staff.username,
            reason=str(request.reason),
        )
        # The rejection is stored and its email queued: a failed read-back must not tell
        # staff to try again. `Records` stores it at +1.
        return _read_back(self._records, rejected.id) or replace(rejected, version=rejected.version + 1)


class UndoRejection:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, request: UndoRequest) -> Undone:
        """Back to waiting the same Austin day, cancelling the rejection email if it hasn't
        gone (pending or sending). Sends and queues nothing. `NotFound`, `Conflict`,
        `NotRejected`, `UndoTooLate`."""
        drop_off = _current(self._records, request.drop_off_id, request.version)
        # The email's occasion comes from the stored rejection, which the undo clears. A
        # drop-off without one isn't rejected (a waiting one, say): the domain's refusal.
        rejection = drop_off.rejection
        if rejection is None:
            raise NotRejected(drop_off.id)
        undone = undo_rejection(drop_off, self._clock.now())
        occasion = rejection_occasion(rejection.at)
        email = self._records.email(drop_off.id, EmailKind.REJECTED, occasion)
        changes: list[Change] = [Update(undone)]
        if email is None:
            outcome = RejectionEmail.NOT_SENT
        elif email.status in (EmailStatus.PENDING, EmailStatus.SENDING):
            changes.append(Update(mark_cancelled(email)))
            outcome = (
                RejectionEmail.CANCELLED
                if email.status is EmailStatus.PENDING
                else RejectionEmail.MAY_HAVE_GONE
            )
        elif email.status is EmailStatus.SENT:
            outcome = RejectionEmail.SENT
        else:
            # FAILED stays FAILED (the domain cancels only pending and sending) and is taken
            # as not gone (see `NOT_SENT`); a CANCELLED one can't belong to a live rejection.
            outcome = RejectionEmail.NOT_SENT
        self._records.commit(changes)
        log_event(
            "rejection_undone",
            drop_off_id=str(drop_off.id),
            user=request.staff.username,
            outcome=outcome.value,
        )
        # The undo is stored; what became of the email must still reach staff (#5), so a
        # failed read-back doesn't decide the answer. `Records` stores it at +1.
        stored = _read_back(self._records, drop_off.id) or replace(undone, version=undone.version + 1)
        return Undone(stored, outcome)
