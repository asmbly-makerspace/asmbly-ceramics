"""The email outbox: one entry per email a drop-off is owed (decision 0002).

An entry's key is (`drop_off_id`, `kind`, `occasion`). The `Records` port (phase 1d)
refuses a second entry with the same key, so a received or ready email is queued once,
and a new rejection after an undo, with its own time as the occasion, queues a new one.
Sending is at least once: a send that was claimed and never finished can be retried,
which may send a second copy.

A move the status doesn't allow is a `ValueError` (a bug: the use case reads the entry
first), except `retry`, which staff ask for and which raises `EmailNotRetryable`.
"""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from asmbly_ceramics.domain.errors import EmailNotRetryable
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import STALE_SENDING_AFTER

ERROR_CODE_MAX = 64
# An error code only (`MessageRejected`, `Throttling`): never AWS's message, which can
# quote what was sent.
_ERROR_CODE = re.compile(rf"[A-Za-z0-9_.-]{{1,{ERROR_CODE_MAX}}}", flags=re.ASCII)


def is_error_code(code: str) -> bool:
    """1 to 64 of `[A-Za-z0-9_.-]`: the shape of a provider's error code, never a message."""
    return _ERROR_CODE.fullmatch(code) is not None


class EmailKind(StrEnum):
    RECEIVED = "received"
    READY = "ready"
    REJECTED = "rejected"


class EmailStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Email:
    drop_off_id: DropOffId
    kind: EmailKind
    occasion: str  # "" for received and ready; the rejection's time, ISO, for rejected
    status: EmailStatus
    created_at: datetime
    attempts: int = 0
    claimed_at: datetime | None = None
    sent_at: datetime | None = None
    error_code: str | None = None
    version: int = 0


def new_email(drop_off_id: DropOffId, kind: EmailKind, at: datetime, occasion: str = "") -> Email:
    _check_aware(at)
    if (kind is EmailKind.REJECTED) != bool(occasion):
        raise ValueError("only a rejected email has an occasion, and it always has one")
    return Email(drop_off_id, kind, occasion, EmailStatus.PENDING, created_at=at)


def claim(email: Email, at: datetime) -> Email:
    """PENDING to SENDING, counting the attempt."""
    _check_aware(at)
    _require(email, EmailStatus.PENDING)
    return replace(email, status=EmailStatus.SENDING, attempts=email.attempts + 1, claimed_at=at)


def mark_sent(email: Email, at: datetime) -> Email:
    _check_aware(at)
    _require(email, EmailStatus.SENDING)
    return replace(email, status=EmailStatus.SENT, sent_at=at, error_code=None)


def mark_failed(email: Email, code: str) -> Email:
    """SENDING to FAILED, keeping the error code: at most 64 of `[A-Za-z0-9_.-]`."""
    _require(email, EmailStatus.SENDING)
    if not is_error_code(code):
        raise ValueError("an email's error is stored as a code, not a message")
    return replace(email, status=EmailStatus.FAILED, error_code=code)


def mark_cancelled(email: Email) -> Email:
    _require(email, EmailStatus.PENDING, EmailStatus.SENDING)
    return replace(email, status=EmailStatus.CANCELLED)


def retry(email: Email, at: datetime) -> Email:
    """A failed email, or one stuck sending, back to PENDING."""
    _check_aware(at)
    if email.status is not EmailStatus.FAILED and not _is_stale(email, at):
        raise EmailNotRetryable()
    return replace(email, status=EmailStatus.PENDING, error_code=None, claimed_at=None)


def needs_attention(email: Email, now: datetime) -> bool:
    """Failed, or sending for longer than `STALE_SENDING_AFTER`: staff see it in the console."""
    _check_aware(now)
    return email.status is EmailStatus.FAILED or _is_stale(email, now)


def _is_stale(email: Email, now: datetime) -> bool:
    return (
        email.status is EmailStatus.SENDING
        and email.claimed_at is not None
        and now - email.claimed_at > STALE_SENDING_AFTER
    )


def _require(email: Email, *allowed: EmailStatus) -> None:
    if email.status not in allowed:
        raise ValueError(f"{email.drop_off_id}'s {email.kind} email is {email.status}")


def _check_aware(at: datetime) -> None:
    if at.utcoffset() is None:
        raise ValueError("an email's times are aware")
