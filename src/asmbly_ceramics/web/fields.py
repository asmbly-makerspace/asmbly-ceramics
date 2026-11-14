"""The posted form, read into the use case's request, and the domain's message keys as
the sentences the page shows next to each field.

Every value stays a string here: the domain does the checking (`DropOffDetails.create`,
`SubmitDropOff`). A name posted twice keeps its first value; slots keep every value, in
order, for the use case to count.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import parse_qsl

from asmbly_ceramics.domain.errors import FORM_EXPIRED_KEY, FieldErrors
from asmbly_ceramics.domain.limits import (
    NAME_MAX,
    PHOTO_MAX_BYTES,
    PHOTOS_MAX,
    PHOTOS_MIN,
    PIECES_MAX,
    PIECES_MIN,
)
from asmbly_ceramics.domain.photos import PHOTO_COUNT_KEY, PhotoRefusal
from asmbly_ceramics.use_cases.submit import SubmitRequest

FORM_FIELDS = ("name", "email", "phone", "pieces", "firing_type", "glaze_type")
MAX_MB = PHOTO_MAX_BYTES // (1024 * 1024)
TOO_MANY_VALUES = 64  # far more than the form sends: a body of junk names is refused early

MESSAGES: Mapping[str, str] = MappingProxyType(
    {
        "name.required": "Enter your name.",
        "name.too_long": f"Enter a name of up to {NAME_MAX} characters.",
        "email.required": "Enter an email address, like the one you check most.",
        "email.invalid": "Enter an email address, like the one you check most.",
        "phone.required": "Enter a phone number with its area code.",
        "phone.invalid": "Enter a phone number with its area code.",
        "pieces.invalid": f"Enter how many pieces, from {PIECES_MIN} to {PIECES_MAX}.",
        "firing_type.required": "Choose a firing type.",
        "firing_type.unknown": "Choose a firing type.",
        "glaze_type.required": "Choose the glaze you used.",
        "glaze_type.unknown": "Choose the glaze you used.",
        "glaze_type.not_allowed": "This firing type doesn't take a glaze. Clear the glaze choice.",
        PHOTO_COUNT_KEY: f"Add {PHOTOS_MIN} to {PHOTOS_MAX} photos.",
        FORM_EXPIRED_KEY: (
            "Something went wrong. Please submit again. If this keeps happening, allow cookies for this site."
        ),
    }
)
"""Each field key's message. Photo keys (`photo.<n>`) are in `PHOTO_MESSAGES`."""

PHOTO_MESSAGES: Mapping[PhotoRefusal, str] = MappingProxyType(
    {
        PhotoRefusal.MISSING: f"Photo {{n}} didn't arrive. Check it is under {MAX_MB} MB and add it again.",
        PhotoRefusal.NOT_IMAGE: "Photo {n} isn't a photo we can read. Use a JPEG, PNG or WebP photo.",
        PhotoRefusal.UNSUPPORTED_TYPE: (
            "Photo {n} is in a format we can't take (such as HEIC). Use a JPEG, PNG or WebP photo."
        ),
        PhotoRefusal.TOO_LARGE: f"Photo {{n}} is over {MAX_MB} MB.",
        PhotoRefusal.TOO_MANY_PIXELS: "Photo {n} is too big to read. Use a smaller photo.",
    }
)
UNKNOWN_MESSAGE = "Check this and try again."
COOKIES_NEEDED = "This form needs cookies. Allow them for this site and reload the page."
UPLOAD_FAILED = f"Photo {{n}} couldn't be uploaded. Check it is under {MAX_MB} MB and try again."
_PHOTO_KEY = re.compile(r"photo\.([1-9][0-9]?)", flags=re.ASCII)


@dataclass(frozen=True, slots=True)
class PostedForm:
    """What the browser sent, as text; shown back escaped when the form is refused."""

    values: Mapping[str, str] = field(repr=False)  # FORM_FIELDS' first values ("" when absent)
    slots: tuple[str, ...] = field(repr=False)  # bearer handles
    submission: str = field(repr=False)


class MalformedForm(Exception):  # noqa: N818 - named for what happened, as the domain's errors are
    """The body isn't a form the page could have sent (bad encoding, junk)."""


def read_form(body: bytes) -> PostedForm:
    """`application/x-www-form-urlencoded`, strictly UTF-8. `MalformedForm` otherwise."""
    try:
        text = body.decode("utf-8", errors="strict")
        pairs = parse_qsl(
            text,
            keep_blank_values=True,
            strict_parsing=False,
            encoding="utf-8",
            errors="strict",
            max_num_fields=TOO_MANY_VALUES,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise MalformedForm() from error
    first: dict[str, str] = {}
    slots: list[str] = []
    for name, value in pairs:
        if name == "slot":
            slots.append(value)
        else:
            first.setdefault(name, value)
    return PostedForm(
        values=MappingProxyType({name: first.get(name, "") for name in FORM_FIELDS}),
        slots=tuple(slots),
        submission=first.get("submission", ""),
    )


def submit_request(form: PostedForm, *, device: str, source_address: str) -> SubmitRequest:
    glaze_type = form.values["glaze_type"]
    return SubmitRequest(
        name=form.values["name"],
        email=form.values["email"],
        phone=form.values["phone"],
        pieces=form.values["pieces"],
        firing_type=form.values["firing_type"],
        glaze_type=glaze_type or None,
        upload_slots=form.slots,
        submission_token=form.submission,
        device=device,
        source_address=source_address,
    )


def message_for(key: str) -> str:
    """The sentence for a message key; a key the page doesn't know gets a generic one
    (`test_every_message_key_has_a_message` keeps that from happening)."""
    if key in MESSAGES:
        return MESSAGES[key]
    photo = key.removeprefix("photo.")
    if photo in PhotoRefusal.__members__.values():
        return PHOTO_MESSAGES[PhotoRefusal(photo)]
    return UNKNOWN_MESSAGE


@dataclass(frozen=True, slots=True)
class FieldMessages:
    """The messages the form shows: one per field, and the photos' in their order."""

    by_field: Mapping[str, str]
    photos: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.by_field) + len(self.photos)


def field_messages(errors: FieldErrors) -> FieldMessages:
    """`InvalidDetails.errors` as the page shows them. A `photo.<n>` field's key is
    `photo.<kind>`, shown as "Photo <n> …", in the photos' order."""
    by_field: dict[str, str] = {}
    photos: list[tuple[int, str]] = []
    for name, key in errors.items():
        match = _PHOTO_KEY.fullmatch(name)
        if match is not None:
            n = int(match.group(1))
            kind = key.removeprefix("photo.")
            template = (
                PHOTO_MESSAGES[PhotoRefusal(kind)]
                if kind in PhotoRefusal.__members__.values()
                else "Photo {n}: " + UNKNOWN_MESSAGE
            )
            photos.append((n, template.format(n=n)))
        else:
            by_field[name] = message_for(key)
    return FieldMessages(
        by_field=MappingProxyType(by_field), photos=tuple(message for _, message in sorted(photos))
    )
