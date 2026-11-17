"""Firing notes (#17): what staff note about a firing, to find again later.

A note is written on a load at any stage but deleted, can be tagged with the studio's
glaze types and clay bodies, and can carry a ruling on whether what it is about may be
tested. It records who wrote it and when, and who last edited or removed it and when;
a removed note is kept, as a deleted load is, but listed nowhere again.

A note holds no personal details: its text is refused when it holds something shaped
like an email address or a phone number, and no message quotes it. The close (#7)
never touches a note.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Literal

from asmbly_ceramics.domain.errors import InvalidNote, LoadNotNotable, NotFound
from asmbly_ceramics.domain.ids import ItemId, LoadId, NoteId
from asmbly_ceramics.domain.limits import NOTE_TAGS_MAX, NOTE_TEXT_MAX, PHONE_DIGITS_MIN
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.studio import CatalogItem, CatalogList, ItemStatus, Studio, kind_name, kinds_name

_ALLOWED_CONTROLS = frozenset("\n\t")
# What people put between a phone number's digit groups, after `_for_phone_check`: any
# number of spaces, dots, dashes, slashes, colons, underscores and brackets.
_SEP = r"[ .\-/:_()]*"
# A clock time (`10:30`, `9:05:12`) is never part of a phone number: it is cut out first.
# Only an hour of one or two digits counts, so `NNNNNNNNNN:N` stays a phone number.
_CLOCK_TIME = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)", flags=re.ASCII)
_PHONE_SHAPES = re.compile(
    "|".join(
        (
            # A North American number, 3-3-4, with an optional leading 1. Its area code and
            # exchange start with 2 to 9, and an area code is never N00 or N11 (toll-free
            # N00 numbers are left out on purpose), so a ramp of 200, 250 and 1000 degrees
            # is kept. A ramp shaped 3-3-4 (three numbers of 3, 3 and 4 digits, with spaces
            # or slashes between) is refused as a phone number would be: a decision. Written
            # with units or commas it is kept.
            rf"(?<!\d)(?:1{_SEP})?[2-9](?!00|11)\d\d{_SEP}[2-9]\d\d{_SEP}\d{{4}}(?!\d)",
            # One unbroken group of as many digits as the drop-off form's shortest phone.
            rf"\d{{{PHONE_DIGITS_MIN},}}",
            # A leading +, then that many digits, however they are grouped.
            rf"\+{_SEP}\d(?:{_SEP}\d){{{PHONE_DIGITS_MIN - 1},}}",
        )
    ),
    flags=re.ASCII,
)
_MINUS = "\u2212"  # the minus sign, a math symbol rather than a dash (Pd)

TEXT_REQUIRED = "Write the note."
TEXT_PLAIN = "Write the note as plain text."
TEXT_TOO_LONG = f"The note is longer than {NOTE_TEXT_MAX:,} characters."
TEXT_PERSONAL = "Notes can't hold an email address or phone number."


class Ruling(StrEnum):
    ALLOWED = "allowed"
    ALLOWED_WITH_CONDITIONS = "allowed_with_conditions"
    NOT_ALLOWED = "not_allowed"


@dataclass(frozen=True, slots=True)
class FiringNote:
    id: NoteId
    load_id: LoadId
    kiln: ItemId  # the load's kiln when written, for the search
    text: str = field(repr=False)  # never in a log line or a traceback
    glaze_types: tuple[ItemId, ...]
    clay_bodies: tuple[ItemId, ...]
    ruling: Ruling | None
    written_by: str  # staff username
    written_at: datetime
    edited_by: str | None = None  # staff username
    edited_at: datetime | None = None
    removed_by: str | None = None  # staff username
    removed_at: datetime | None = None
    version: int = 0

    @property
    def removed(self) -> bool:
        return self.removed_at is not None


def check_note_text(text: str) -> str:
    """The text to store: CRLF to LF, a line or paragraph separator as LF, invisible
    characters (Cf, Co, Cn, Cs) dropped, stripped, NFC. `InvalidNote({"text": message})` when
    empty, longer than NOTE_TEXT_MAX, holding a control character but newline or tab, or
    holding something shaped like an email address or a phone number. A phone number's
    shape, looked for on an NFKC copy with Unicode digits, dashes, spaces and newlines
    made ASCII (the email shape is looked for on the same copy): a
    North American 3-3-4 number with an optional leading 1, one unbroken group of 10 or
    more digits, or a + and 10 or more digits; groups joined by any spaces, dots,
    dashes, slashes, colons, underscores or brackets. A clock time (`10:30`) is never
    part of one. The message never quotes the text."""
    clean, message = _check_text(text)
    if message is not None:
        raise InvalidNote({"text": message})
    return clean


def write_note(
    id: NoteId,
    load: Load,
    text: str,
    glaze_types: Sequence[ItemId],
    clay_bodies: Sequence[ItemId],
    ruling: Ruling | None,
    by: str,
    at: datetime,
    studio: Studio,
) -> FiringNote:
    """A new note on `load`, at any stage but deleted (`LoadNotNotable`). The text's, the
    repeated tags' and the tag counts' refusals come together in one `InvalidNote`, keyed
    `text`, `glaze_types` and `clay_bodies`. Each tag must then be an active item of its
    list (`UnknownItem`, `ItemRetired`: only a tampered form sends one)."""
    _check_change(by, at)
    if load.status is LoadStatus.DELETED:
        raise LoadNotNotable(load.id)
    clean, glazes, clays = _check_fields(text, glaze_types, clay_bodies, frozenset(), frozenset(), studio)
    return FiringNote(
        id=id,
        load_id=load.id,
        kiln=load.kiln,
        text=clean,
        glaze_types=glazes,
        clay_bodies=clays,
        ruling=ruling,
        written_by=by,
        written_at=at,
    )


def edit_note(
    note: FiringNote,
    text: str,
    glaze_types: Sequence[ItemId],
    clay_bodies: Sequence[ItemId],
    ruling: Ruling | None,
    by: str,
    at: datetime,
    studio: Studio,
) -> FiringNote:
    """Text, tags and ruling replaced, stamped `edited_by`/`edited_at`; `written_*` kept.
    A tag already on the note may be retired since; a new one must be active. Checked as
    `write_note` checks. `NotFound(note.id)` for a removed note. When nothing changes,
    the note comes back as it was, with no stamp."""
    _check_change(by, at)
    if note.removed:
        raise NotFound(note.id)
    clean, glazes, clays = _check_fields(
        text, glaze_types, clay_bodies, frozenset(note.glaze_types), frozenset(note.clay_bodies), studio
    )
    if (clean, ruling, frozenset(glazes), frozenset(clays)) == (
        note.text,
        note.ruling,
        frozenset(note.glaze_types),
        frozenset(note.clay_bodies),
    ):
        return note  # the same tags in another order are no change
    return replace(
        note,
        text=clean,
        glaze_types=glazes,
        clay_bodies=clays,
        ruling=ruling,
        edited_by=by,
        edited_at=at,
    )


def remove_note(note: FiringNote, by: str, at: datetime) -> FiringNote:
    """Stamped removed; listed nowhere again. `NotFound` if removed already."""
    _check_change(by, at)
    if note.removed:
        raise NotFound(note.id)
    return replace(note, removed_by=by, removed_at=at)


def move_note(note: FiringNote, kiln: ItemId) -> FiringNote:
    """The note filed under its load's new kiln, so the search by kiln finds it where the
    load now is. Not an edit: its text, tags and stamps stay as they are."""
    return replace(note, kiln=kiln)


@dataclass(frozen=True, slots=True)
class NoteFilter:
    kiln: ItemId | None = None
    glaze_type: ItemId | None = None
    clay_body: ItemId | None = None
    ruling: Ruling | Literal["any"] | None = "any"  # None means "no ruling"


def matches(note: FiringNote, f: NoteFilter) -> bool:
    """Not removed, and every set part of the filter holds. The date range is the
    store's (phase 4 reads by `written_at`)."""
    if note.removed:
        return False
    if f.kiln is not None and note.kiln != f.kiln:
        return False
    if f.glaze_type is not None and f.glaze_type not in note.glaze_types:
        return False
    if f.clay_body is not None and f.clay_body not in note.clay_bodies:
        return False
    return f.ruling == "any" or note.ruling == f.ruling


def _check_fields(
    text: str,
    glaze_types: Sequence[ItemId],
    clay_bodies: Sequence[ItemId],
    kept_glaze_types: frozenset[ItemId],
    kept_clay_bodies: frozenset[ItemId],
    studio: Studio,
) -> tuple[str, tuple[ItemId, ...], tuple[ItemId, ...]]:
    errors: dict[str, str] = {}
    clean, message = _check_text(text)
    if message is not None:
        errors["text"] = message
    for key, tags, which in (
        ("glaze_types", glaze_types, CatalogList.GLAZE_TYPES),
        ("clay_bodies", clay_bodies, CatalogList.CLAY_BODIES),
    ):
        if (tag_message := _tags_message(tags, which)) is not None:
            errors[key] = tag_message
    if errors:
        raise InvalidNote(errors)
    _check_items(studio, CatalogList.GLAZE_TYPES, glaze_types, kept_glaze_types)
    _check_items(studio, CatalogList.CLAY_BODIES, clay_bodies, kept_clay_bodies)
    return clean, tuple(glaze_types), tuple(clay_bodies)


def _tags_message(tags: Sequence[ItemId], which: CatalogList) -> str | None:
    if len(set(tags)) != len(tags):
        return f"Pick each {kind_name(which)} once."
    if len(tags) > NOTE_TAGS_MAX:
        return f"Pick at most {NOTE_TAGS_MAX} {kinds_name(which)}."
    return None


def taggable_items(studio: Studio, which: CatalogList, kept: Sequence[ItemId]) -> tuple[CatalogItem, ...]:
    """The glaze types or clay bodies a note may carry: the active ones, in the studio's
    order, then those of `kept` (the tags the note already has) retired since. The one
    rule `add_note`, `edit_note` and the note form all follow."""
    items = studio.items(which)
    active = tuple(item for item in items if item.status is ItemStatus.ACTIVE)
    return active + tuple(item for item in items if item.status is not ItemStatus.ACTIVE and item.id in kept)


def _check_items(studio: Studio, which: CatalogList, tags: Sequence[ItemId], kept: frozenset[ItemId]) -> None:
    """Each tag must be one of `taggable_items`; any other is `UnknownItem` or, when it is
    retired and the note didn't already carry it, `ItemRetired`."""
    allowed = {item.id for item in taggable_items(studio, which, tuple(kept))}
    for tag in tags:
        if tag not in allowed:
            studio.active_item(which, tag)  # raises: unknown, or retired and not kept


def _check_text(text: str) -> tuple[str, str | None]:
    """The cleaned text and the refusal's message, or None when it is fine."""
    clean = "".join(_plain(c) for c in text.replace("\r\n", "\n").replace("\r", "\n"))
    clean = unicodedata.normalize("NFC", clean.strip())
    if not clean:
        return clean, TEXT_REQUIRED
    if any(unicodedata.category(c) == "Cc" and c not in _ALLOWED_CONTROLS for c in clean):
        return clean, TEXT_PLAIN
    if len(clean) > NOTE_TEXT_MAX:
        return clean, TEXT_TOO_LONG
    folded = _for_phone_check(clean)
    if _holds_email_address(folded) or _holds_phone_number(folded):
        return clean, TEXT_PERSONAL
    return clean, None


def _plain(c: str) -> str:
    """`c` as the note keeps it: a line or paragraph separator (Zl, Zp) as a newline, and
    an invisible character (format, private use, unassigned, surrogate: Cf, Co, Cn, Cs)
    dropped, as a drop-off's name drops them, so a zero-width space, soft hyphen, word
    joiner or bidi override never hides a phone number or reorders what staff read. A
    control character (Cc) is kept here, for `_check_text` to refuse."""
    category = unicodedata.category(c)
    if category in ("Zl", "Zp"):
        return "\n"
    if category.startswith("C") and category != "Cc":
        return ""
    return c


def _holds_email_address(text: str) -> bool:
    """Something shaped like `\\S+@\\S+\\.\\S+` in `text` (`_for_phone_check`'s copy, so a
    fullwidth or small `@` and a fullwidth dot count), found in one pass per word: that
    regex backtracks for seconds on a text of 2,000 `@`."""
    for word in text.split():
        at = word.find("@", 1)
        if at != -1 and "." in word[at + 2 : -1]:
            return True
    return False


def _holds_phone_number(text: str) -> bool:
    """Something shaped like a phone number (`check_note_text`) in `text`
    (`_for_phone_check`'s copy), clock times cut out."""
    return _PHONE_SHAPES.search(_CLOCK_TIME.sub(";", text)) is not None


def _for_phone_check(text: str) -> str:
    """A copy of `text` written as a phone check reads it: NFKC (fullwidth digits and
    brackets, a non-breaking space, a fullwidth or small `@`), then every other decimal
    digit as its ASCII digit, every dash as `-` and every space, tab or newline as ` `, so
    a number split over lines is still one. Never stored."""
    return "".join(_ascii_for_phone(c) for c in unicodedata.normalize("NFKC", text))


def _ascii_for_phone(c: str) -> str:
    if c.isascii():
        return " " if c in "\t\n" else c
    if c.isdecimal():
        return str(unicodedata.decimal(c))
    category = unicodedata.category(c)
    if category == "Pd" or c == _MINUS:
        return "-"
    if category == "Zs":
        return " "
    return c


def _check_change(by: str, at: datetime) -> None:
    if not by:
        raise ValueError("a note change needs the staff username")
    if at.utcoffset() is None:
        raise ValueError("a note change needs an aware time")
