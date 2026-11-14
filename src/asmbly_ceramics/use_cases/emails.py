"""Sending a queued email once, "Try sending again", and the console's list of emails
needing attention (#4, #2, #5, #6, #7).

`SendPendingEmail` is what the mailer function (phase 7) calls for each stream record
whose new image is `pending`. The stream delivers at least once, so the email is claimed
with a version check before anything is sent: only the claimer sends. The recipient is
always the drop-off's own address, read by the same key as its photos.

Failures are stored and logged by code only. The alarm (phase 7) counts the ERROR line
`event=email_failed` with `kind`, `drop_off_id` and `error_code`.
"""

import logging
from dataclasses import dataclass, replace
from datetime import datetime

from asmbly_ceramics.domain.dropoff import DropOff
from asmbly_ceramics.domain.email import (
    Email,
    EmailKind,
    EmailStatus,
    claim,
    is_history,
    mark_cancelled,
    mark_failed,
    mark_sent,
    needs_attention,
    retry,
)
from asmbly_ceramics.domain.errors import EmailNotRetryable, NotFound
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.photos import PhotoSize
from asmbly_ceramics.domain.studio import Studio
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.composer import ComposedEmail, Composer, cid, outgoing
from asmbly_ceramics.ports.errors import Unavailable
from asmbly_ceramics.ports.mailer import REFUSED_CODES, Mailer, OutgoingEmail, SendFailed
from asmbly_ceramics.ports.photos import PhotoStore, UploadMissing
from asmbly_ceramics.ports.records import Conflict, Records, Update
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.use_cases.studio import CurrentStudio

# Failures before `Mailer.send` was called: the email certainly didn't go.
PHOTO_MISSING = "photo_missing"
PHOTOS_UNAVAILABLE = "photos_unavailable"
COMPOSE_FAILED = "compose_failed"
DROP_OFF_MISSING = "drop_off_missing"
RECORDS_UNAVAILABLE = "records_unavailable"  # the drop-off or the studio couldn't be read
# Any other exception after the claim: it may have come from inside the send.
UNEXPECTED = "unexpected"

NOT_SENT_CODES = REFUSED_CODES | {
    PHOTO_MISSING,
    PHOTOS_UNAVAILABLE,
    COMPOSE_FAILED,
    DROP_OFF_MISSING,
    RECORDS_UNAVAILABLE,
}


def was_not_sent(code: str | None) -> bool:
    """Whether a failed email's code says it certainly never reached the person. An
    allowlist: `unexpected`, `unknown`, a network error or any code not listed may have
    gone, so staff are told to contact the person (#5)."""
    return code is not None and code in NOT_SENT_CODES


def may_have_gone(email: Email) -> bool:
    """Whether any attempt at this email may have reached the person. An attempt is made
    once it is claimed (`attempts`). `retry` clears the last failure's code, so an email
    tried more than once may have gone on an earlier attempt, whatever its code says now;
    one tried once may have gone unless `was_not_sent` its code. Sent counts as gone."""
    match email.status:
        case EmailStatus.SENT | EmailStatus.SENDING:
            return True
        case EmailStatus.FAILED:
            return email.attempts > 1 or not was_not_sent(email.error_code)
        case EmailStatus.PENDING | EmailStatus.CANCELLED:
            return email.attempts >= 1


class _NotSentError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _code(error: Exception) -> str:
    """A port's error code, else the exception's class name: never its text."""
    return error.code if isinstance(error, Unavailable) else type(error).__name__


class SendPendingEmail:
    def __init__(
        self,
        records: Records,
        photos: PhotoStore,
        mailer: Mailer,
        clock: Clock,
        studio: CurrentStudio,
        composer: Composer,
    ) -> None:
        self._records = records
        self._photos = photos
        self._mailer = mailer
        self._clock = clock
        self._studio = studio
        self._composer = composer

    def __call__(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str) -> EmailStatus | None:
        """What became of the email, or `None` when this call had nothing to do (it isn't
        pending, or another call claimed it). Errors before the claim (`RecordsUnavailable`)
        are raised so the stream tries again: nothing was sent. After the claim nothing is
        raised, so the stream never repeats a send that may have half happened."""
        email = self._records.email(drop_off_id, kind, occasion)
        if email is None or email.status is not EmailStatus.PENDING:
            return None
        now = self._clock.now()
        claimed = claim(email, now)
        try:
            self._records.commit([Update(claimed)])
        except Conflict:
            return None
        claimed = replace(claimed, version=claimed.version + 1)  # as `Records` stores it
        try:
            return self._send(claimed, now)
        except Exception as error:  # recorded by class name; the stream must not retry
            return self._fail(claimed, UNEXPECTED, error_code=type(error).__name__, unexpected=True)

    def _send(self, email: Email, now: datetime) -> EmailStatus:
        try:
            drop_off = self._records.drop_off(email.drop_off_id)
            studio = self._studio()  # the settings in force now (#6)
        except Unavailable as error:
            return self._fail(email, RECORDS_UNAVAILABLE, error_code=error.code)
        if drop_off is None:
            return self._fail(email, DROP_OFF_MISSING)
        if is_history(drop_off, email):
            # Closed (the address is gone), or the rejection was undone: never sent.
            try:
                self._records.commit([Update(mark_cancelled(email))])
            except Conflict:
                return EmailStatus.CANCELLED  # the undo cancelled it first: nothing went
            log_event("email_cancelled", kind=email.kind.value, drop_off_id=str(email.drop_off_id))
            return EmailStatus.CANCELLED
        try:
            message = self._message(email, drop_off, studio, now)
        except _NotSentError as refused:
            return self._fail(email, refused.code)
        try:
            self._mailer.send(message)
        except SendFailed as failed:
            return self._fail(email, failed.code)
        window = studio.pickup_window_days if email.kind is EmailKind.READY else None
        try:
            self._records.commit([Update(mark_sent(email, now, pickup_window_days=window))])
        except Exception as error:  # it went: never mark it failed
            # It stays sending; after STALE_SENDING_AFTER staff see it and may retry it,
            # which may send it twice. A duplicate is better than a lost email.
            log_event(
                "email_unrecorded",
                level=logging.ERROR,
                kind=email.kind.value,
                drop_off_id=str(email.drop_off_id),
                error_code=_code(error),
            )
            return EmailStatus.SENDING
        log_event("email_sent", kind=email.kind.value, drop_off_id=str(email.drop_off_id))
        return EmailStatus.SENT

    def _message(self, email: Email, drop_off: DropOff, studio: Studio, now: datetime) -> OutgoingEmail:
        """The message to the drop-off's own address with its own photos, both read by
        `email.drop_off_id`; `_NotSentError` for anything that stops it before the send."""
        try:
            photos = [(ref, self._photos.read(ref, PhotoSize.FULL)) for ref in drop_off.photos]
        except UploadMissing:
            raise _NotSentError(PHOTO_MISSING) from None
        except Unavailable:
            raise _NotSentError(PHOTOS_UNAVAILABLE) from None
        try:
            composed = self._compose(email.kind, drop_off, studio, now)
            to = drop_off.contact.email if drop_off.contact is not None else ""
            return outgoing(composed, to=to, sending_address=studio.sending_address, photos=photos)
        except ValueError:
            raise _NotSentError(COMPOSE_FAILED) from None

    def _compose(self, kind: EmailKind, drop_off: DropOff, studio: Studio, now: datetime) -> ComposedEmail:
        match kind:
            case EmailKind.RECEIVED:
                return self._composer.received(drop_off, studio, cid)
            case EmailKind.READY:
                return self._composer.ready(drop_off, studio, now, cid)
            case EmailKind.REJECTED:
                return self._composer.rejected(drop_off, studio, cid)

    def _fail(
        self, email: Email, code: str, *, error_code: str | None = None, unexpected: bool = False
    ) -> EmailStatus:
        """Log the failure (the alarm's line) first, then store it by code."""
        fields: dict[str, str] = {
            "kind": email.kind.value,
            "drop_off_id": str(email.drop_off_id),
            "error_code": error_code or code,
        }
        if unexpected:
            fields["reason"] = "unexpected"
        log_event("email_failed", level=logging.ERROR, **fields)
        try:
            self._records.commit([Update(mark_failed(email, code))])
        except Exception as error:  # logged; it shows as stuck sending
            log_event(
                "email_unrecorded",
                level=logging.ERROR,
                kind=email.kind.value,
                drop_off_id=str(email.drop_off_id),
                error_code=_code(error),
            )
        return EmailStatus.FAILED


class RetryEmail:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str, staff: StaffMember) -> Email:
        """Puts a failed email, or one stuck sending, back in the queue; the stream then
        hands it to `SendPendingEmail`. It goes only to that drop-off: the key names it.
        One pending and not stuck (a second click) is returned unchanged; one stuck
        pending (the stream gave up) is written again, so the stream delivers it again. `NotFound`,
        `EmailNotRetryable` (sent, cancelled, missing, or past acting on: the drop-off is
        closed or the rejection undone), `Conflict`."""
        email = self._records.email(drop_off_id, kind, occasion)
        if email is None:
            raise EmailNotRetryable()
        drop_off = self._records.drop_off(drop_off_id)
        if drop_off is None:
            raise NotFound(drop_off_id)
        if is_history(drop_off, email):
            raise EmailNotRetryable()
        now = self._clock.now()
        if email.status is EmailStatus.PENDING and not needs_attention(email, now):
            return email  # queued and not stuck: a second click changes nothing
        retried = retry(email, now)
        self._records.commit([Update(retried)])
        log_event("email_retried", kind=kind.value, drop_off_id=str(drop_off_id), user=staff.username)
        return replace(retried, version=retried.version + 1)


@dataclass(frozen=True, slots=True)
class EmailNeedingAttention:
    """One row of the console's needs-attention list: keys and states only, never an
    address, a name or a message. The key is what "Try sending again" (`RetryEmail`)
    takes."""

    drop_off_id: DropOffId
    kind: EmailKind
    occasion: str
    status: EmailStatus
    error_code: str | None
    created_at: datetime


class EmailsNeedingAttention:
    """Every email the console must show as needing attention, studio-wide, oldest first:
    `needs_acting_on` (failed, or stuck pending or sending, and not history). Without it,
    a fired drop-off whose ready email never went out would never close (#7) and no page
    would show it once its load fell off `ListLoads`. A read: nothing is logged."""

    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self) -> tuple[EmailNeedingAttention, ...]:
        now = self._clock.now()
        candidates = self._records.emails_in(_UNFINISHED)
        rows: list[EmailNeedingAttention] = []
        for email in candidates:
            if not needs_attention(email, now):
                continue
            drop_off = self._records.drop_off(email.drop_off_id)
            # A drop-off record is never deleted (closing keeps it), so a missing one is a
            # broken record: shown rather than hidden.
            if drop_off is not None and is_history(drop_off, email):
                continue
            rows.append(
                EmailNeedingAttention(
                    email.drop_off_id,
                    email.kind,
                    email.occasion,
                    email.status,
                    email.error_code,
                    email.created_at,
                )
            )
        return tuple(rows)


_UNFINISHED = frozenset({EmailStatus.PENDING, EmailStatus.SENDING, EmailStatus.FAILED})
