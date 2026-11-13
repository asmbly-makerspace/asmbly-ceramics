"""The outbox: one email per drop-off, kind and occasion."""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from asmbly_ceramics.domain.errors import EmailNotRetryable
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import STALE_SENDING_AFTER

_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


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
    """Keyed by (drop_off_id, kind, occasion): the Records port refuses a second Put of a key."""

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
    return Email(drop_off_id, kind, occasion, EmailStatus.PENDING, at)


def _need(email: Email, *allowed: EmailStatus) -> None:
    if email.status not in allowed:
        raise ValueError(f"A {email.kind} email can't do that while {email.status}.")


def claim(email: Email, at: datetime) -> Email:
    _need(email, EmailStatus.PENDING)
    return replace(email, status=EmailStatus.SENDING, attempts=email.attempts + 1, claimed_at=at)


def mark_sent(email: Email, at: datetime) -> Email:
    _need(email, EmailStatus.SENDING)
    return replace(email, status=EmailStatus.SENT, sent_at=at, error_code=None)


def mark_failed(email: Email, code: str) -> Email:
    _need(email, EmailStatus.SENDING)
    if not _CODE.fullmatch(code):
        raise ValueError("An error code is at most 64 of letters, digits, '_', '.' and '-'.")
    return replace(email, status=EmailStatus.FAILED, error_code=code)


def mark_cancelled(email: Email) -> Email:
    _need(email, EmailStatus.PENDING, EmailStatus.SENDING)
    return replace(email, status=EmailStatus.CANCELLED)


def _stale(email: Email, now: datetime) -> bool:
    return (
        email.status is EmailStatus.SENDING
        and email.claimed_at is not None
        and now - email.claimed_at > STALE_SENDING_AFTER
    )


def retry(email: Email, at: datetime) -> Email:
    if email.status is not EmailStatus.FAILED and not _stale(email, at):
        raise EmailNotRetryable("That email isn't failed.")
    return replace(email, status=EmailStatus.PENDING, claimed_at=None, error_code=None)


def needs_attention(email: Email, now: datetime) -> bool:
    return email.status is EmailStatus.FAILED or _stale(email, now)
