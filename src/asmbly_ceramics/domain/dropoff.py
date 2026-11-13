"""A drop-off: what a person left, and its states."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
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
from asmbly_ceramics.domain.studio import CatalogItem, CatalogList, ItemStatus, Studio
from asmbly_ceramics.domain.text import is_valid_email, strip_controls

_PHONE_CHARS = frozenset("0123456789 +-.()")
_DIGITS = frozenset("0123456789")


class DropOffState(StrEnum):
    WAITING = "waiting"
    IN_LOAD = "in_load"
    FIRED = "fired"
    REJECTED = "rejected"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class Contact:
    name: str
    email: str
    phone: str  # digits only; shown formatted by the page


@dataclass(frozen=True, slots=True)
class Rejection:
    reason: ItemId
    message: str | None  # None once closed, or when none was written
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
        """Check every field at once; raise InvalidDetails with every field's key, or return."""
        errors: dict[str, str] = {}

        clean_name = strip_controls(name)
        if not clean_name:
            errors["name"] = "name.required"
        elif len(clean_name) > NAME_MAX:
            errors["name"] = "name.too_long"

        clean_email = email.strip()
        if not clean_email:
            errors["email"] = "email.required"
        elif not is_valid_email(clean_email):
            errors["email"] = "email.invalid"

        digits = "".join(c for c in phone if c in _DIGITS)
        if not phone.strip():
            errors["phone"] = "phone.required"
        elif not set(phone) <= _PHONE_CHARS or not PHONE_DIGITS_MIN <= len(digits) <= PHONE_DIGITS_MAX:
            errors["phone"] = "phone.invalid"

        count = pieces.strip()
        piece_count = int(count) if count and set(count) <= _DIGITS and len(count) <= 4 else 0
        if not PIECES_MIN <= piece_count <= PIECES_MAX:
            errors["pieces"] = "pieces.invalid"

        firing = _active(studio, CatalogList.FIRING_TYPES, firing_type.strip())
        if not firing_type.strip():
            errors["firing_type"] = "firing_type.required"
        elif firing is None:
            errors["firing_type"] = "firing_type.unknown"

        glaze_id = (glaze_type or "").strip()
        glaze = _active(studio, CatalogList.GLAZE_TYPES, glaze_id)
        if firing is not None:
            if firing.needs_glaze_type and not glaze_id:
                errors["glaze_type"] = "glaze_type.required"
            elif firing.needs_glaze_type and glaze is None:
                errors["glaze_type"] = "glaze_type.unknown"
            elif not firing.needs_glaze_type and glaze_id:
                errors["glaze_type"] = "glaze_type.not_allowed"

        if not PHOTOS_MIN <= photo_count <= PHOTOS_MAX:
            errors["photos"] = "photos.count"

        if errors:
            raise InvalidDetails(errors)
        assert firing is not None  # noqa: S101 - no errors means the firing type was valid
        return cls(
            contact=Contact(name=clean_name, email=clean_email, phone=digits),
            pieces=piece_count,
            firing_type=firing.id,
            glaze_type=glaze.id if glaze is not None and firing.needs_glaze_type else None,
        )


def _active(studio: Studio, which: CatalogList, id: str) -> CatalogItem | None:
    try:
        return studio.active_item(which, ItemId(id))
    except UnknownItem, ItemRetired:
        return None


@dataclass(frozen=True, slots=True)
class DropOff:
    id: DropOffId
    contact: Contact | None
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
    return DropOff(
        id=id,
        contact=details.contact,
        pieces=details.pieces,
        firing_type=details.firing_type,
        glaze_type=details.glaze_type,
        photos=tuple(photos),
        created_at=at,
        state=DropOffState.WAITING,
    )


def reject(drop_off: DropOff, reason: CatalogItem, message: str | None, by: str, at: datetime) -> DropOff:
    if drop_off.state is not DropOffState.WAITING:
        raise NotWaiting(f"{drop_off.id} isn't waiting: it is {_words(drop_off.state)}.")
    if reason.status is ItemStatus.RETIRED:
        raise ItemRetired(f"{reason.name} is retired and can't be picked.")
    text = (message or "").strip() or None
    if text is None and reason.needs_message:
        raise MessageRequired("This reason needs a message.")
    if text is not None and len(text) > MESSAGE_MAX:
        raise MessageTooLong(f"The message is longer than {MESSAGE_MAX:,} characters.")
    return replace(
        drop_off,
        state=DropOffState.REJECTED,
        rejection=Rejection(reason=reason.id, message=text, by=by, at=at),
    )


def undo_rejection(drop_off: DropOff, at: datetime) -> DropOff:
    if drop_off.state is not DropOffState.REJECTED or drop_off.rejection is None:
        raise NotRejected(f"{drop_off.id} isn't rejected.")
    if at.astimezone(STUDIO_TZ).date() != drop_off.rejection.at.astimezone(STUDIO_TZ).date():
        raise UndoTooLate(f"{drop_off.id} was rejected on an earlier day; undo works only the same day.")
    return replace(drop_off, state=DropOffState.WAITING, rejection=None)


def _words(state: DropOffState) -> str:
    return state.value.replace("_", " ")
