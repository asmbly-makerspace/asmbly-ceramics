"""A drop-off: what the public form sends (#2), its rejection and the same-day undo (#5).

Everything the form sends is hostile until `DropOffDetails.create` has checked it, on the
server, every field at once. The person's name, email, phone and a rejection's message
are personal details: they never appear in a `repr`, an error or a message key.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Self

from asmbly_ceramics.domain.errors import (
    InvalidDetails,
    ItemRetired,
    MessageRequired,
    MessageTooLong,
    NotRejected,
    NotWaiting,
    UndoTooLate,
    UnknownItem,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import (
    MESSAGE_MAX,
    NAME_MAX,
    PHONE_DIGITS_MAX,
    PHONE_DIGITS_MIN,
    PHOTOS_MAX,
    PHOTOS_MIN,
    PIECES_MAX,
    PIECES_MIN,
    STUDIO_TZ,
)
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.domain.studio import CatalogItem, CatalogList, ItemStatus, Studio, is_valid_email

# What a phone number may be typed with: ASCII digits, spaces and + - . ( ).
_PHONE_TYPED = re.compile(r"[0-9 +\-.()]+", flags=re.ASCII)
# Pieces as ASCII digits only; the length bound comes before int().
_PIECES = re.compile(r"[0-9]{1,3}", flags=re.ASCII)
_MESSAGE_ALLOWED_CONTROLS = frozenset("\n\t")


class DropOffState(StrEnum):
    WAITING = "waiting"
    IN_LOAD = "in_load"
    FIRED = "fired"
    REJECTED = "rejected"
    CLOSED = "closed"

    @property
    def label(self) -> str:
        """The state as words, for messages: `in load`."""
        return self.value.replace("_", " ")


@dataclass(frozen=True, slots=True)
class Contact:
    name: str = field(repr=False)
    email: str = field(repr=False)
    phone: str = field(repr=False)  # the digits typed; the page formats them


@dataclass(frozen=True, slots=True)
class Rejection:
    reason: ItemId
    message: str | None = field(repr=False)  # None once closed, or when none was written
    by: str  # staff username
    at: datetime


@dataclass(frozen=True, slots=True)
class DropOffDetails:
    contact: Contact
    pieces: int
    firing_type: ItemId
    glaze_type: ItemId | None

    @classmethod
    def create(
        cls,
        *,
        name: str,
        email: str,
        phone: str,
        pieces: str,
        firing_type: str,
        glaze_type: str | None,
        photo_count: int,
        studio: Studio,
    ) -> Self:
        """Check every field at once; raise `InvalidDetails` with every bad field's key."""
        errors: dict[str, str] = {}

        # Control and format characters, and the line and paragraph separators, go.
        name = "".join(c for c in name if not _is_dropped_from_name(c)).strip()
        if not name:
            errors["name"] = "name.required"
        elif len(name) > NAME_MAX:
            errors["name"] = "name.too_long"

        email = email.strip()
        if not email:
            errors["email"] = "email.required"
        elif not is_valid_email(email):
            errors["email"] = "email.invalid"

        phone = phone.strip()
        digits = "".join(c for c in phone if "0" <= c <= "9")
        if not phone:
            errors["phone"] = "phone.required"
        elif not _PHONE_TYPED.fullmatch(phone) or not PHONE_DIGITS_MIN <= len(digits) <= PHONE_DIGITS_MAX:
            errors["phone"] = "phone.invalid"

        count = 0
        pieces = pieces.strip()
        if _PIECES.fullmatch(pieces):
            count = int(pieces)
        if not PIECES_MIN <= count <= PIECES_MAX:
            errors["pieces"] = "pieces.invalid"

        firing_type = firing_type.strip()
        glaze_type = (glaze_type or "").strip()
        firing: CatalogItem | None = None
        if not firing_type:
            errors["firing_type"] = "firing_type.required"
        else:
            firing = _active(studio, CatalogList.FIRING_TYPES, firing_type)
            if firing is None:
                errors["firing_type"] = "firing_type.unknown"

        glaze: CatalogItem | None = None
        if firing is not None and not firing.needs_glaze_type:
            if glaze_type:
                errors["glaze_type"] = "glaze_type.not_allowed"
        elif not glaze_type:
            if firing is not None:
                errors["glaze_type"] = "glaze_type.required"
        else:
            # Checked when the firing type needs it, or when the firing type was refused.
            glaze = _active(studio, CatalogList.GLAZE_TYPES, glaze_type)
            if glaze is None:
                errors["glaze_type"] = "glaze_type.unknown"

        if (
            isinstance(photo_count, bool)
            or not isinstance(photo_count, int)
            or not PHOTOS_MIN <= photo_count <= PHOTOS_MAX
        ):
            errors["photos"] = "photos.count"

        if errors or firing is None:  # no firing type always comes with its error
            raise InvalidDetails(errors)
        return cls(
            contact=Contact(name=name, email=email, phone=digits),
            pieces=count,
            firing_type=firing.id,
            glaze_type=glaze.id if glaze is not None else None,
        )


@dataclass(frozen=True, slots=True)
class DropOff:
    id: DropOffId
    contact: Contact | None  # None once closed
    pieces: int
    firing_type: ItemId
    glaze_type: ItemId | None
    photos: tuple[PhotoRef, ...]
    created_at: datetime
    state: DropOffState
    load_id: LoadId | None = None
    rejection: Rejection | None = None
    fired_at: datetime | None = None
    closed_at: datetime | None = None
    version: int = 0


def new_drop_off(id: DropOffId, details: DropOffDetails, photos: Sequence[PhotoRef], at: datetime) -> DropOff:
    """A waiting drop-off; `photos` are this ID's refs, indexed 1 to n."""
    _check_aware(at)
    photos = tuple(photos)
    if not PHOTOS_MIN <= len(photos) <= PHOTOS_MAX:
        raise ValueError(f"a drop-off has {PHOTOS_MIN} to {PHOTOS_MAX} photos")
    if photos != tuple(PhotoRef(id, index) for index in range(1, len(photos) + 1)):
        raise ValueError(f"{id}'s photos must be its own, indexed from 1")
    return DropOff(
        id=id,
        contact=details.contact,
        pieces=details.pieces,
        firing_type=details.firing_type,
        glaze_type=details.glaze_type,
        photos=photos,
        created_at=at,
        state=DropOffState.WAITING,
    )


def reject(drop_off: DropOff, reason: CatalogItem, message: str | None, by: str, at: datetime) -> DropOff:
    """Reject a waiting drop-off (#5). `reason` comes from `studio.item(CatalogList.REASONS, id)`."""
    _check_aware(at)
    if not by:
        raise ValueError("a rejection needs the staff username")
    if drop_off.state is not DropOffState.WAITING:
        raise NotWaiting(drop_off.id, drop_off.state.label)
    if reason.status is not ItemStatus.ACTIVE:
        raise ItemRetired(reason.name)
    # A browser's textarea posts CRLF; the stored text holds LF only. Other control
    # characters (NUL, ESC, backspace) go: the message is put into an email.
    lines = (message or "").replace("\r\n", "\n").replace("\r", "\n")
    plain = "".join(c for c in lines if unicodedata.category(c) != "Cc" or c in _MESSAGE_ALLOWED_CONTROLS)
    text = plain.strip() or None
    if text is None and reason.needs_message:
        raise MessageRequired()
    if text is not None and len(text) > MESSAGE_MAX:
        raise MessageTooLong(MESSAGE_MAX)
    return replace(drop_off, state=DropOffState.REJECTED, rejection=Rejection(reason.id, text, by, at))


def undo_rejection(drop_off: DropOff, at: datetime) -> DropOff:
    """Put a rejected drop-off back to waiting, on the same Austin day only (#5)."""
    _check_aware(at)
    if drop_off.state is not DropOffState.REJECTED or drop_off.rejection is None:
        raise NotRejected(drop_off.id)
    if at.astimezone(STUDIO_TZ).date() != drop_off.rejection.at.astimezone(STUDIO_TZ).date():
        raise UndoTooLate(drop_off.id)
    return replace(drop_off, state=DropOffState.WAITING, rejection=None)


def _active(studio: Studio, which: CatalogList, id: str) -> CatalogItem | None:
    try:
        return studio.active_item(which, ItemId(id))
    except UnknownItem, ItemRetired:
        return None


def _is_dropped_from_name(c: str) -> bool:
    category = unicodedata.category(c)
    return category.startswith("C") or category in ("Zl", "Zp")


def _check_aware(at: datetime) -> None:
    if at.utcoffset() is None:
        raise ValueError("a drop-off's times are aware")
