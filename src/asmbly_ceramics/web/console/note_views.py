"""Firing notes (#17) as the console shows them: a note's card, the note form's state and
choices, read by the load page (`loads.py`) and the note pages (`notes.py`).

A note's text is typed by staff: it is shown only through Jinja2's autoescape, never
logged, never put in an address. Nothing here logs.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from asmbly_ceramics.domain.ids import ItemId, NoteId
from asmbly_ceramics.domain.limits import NOTE_TAGS_MAX, NOTE_TEXT_MAX
from asmbly_ceramics.domain.notes import FiringNote, Ruling, taggable_items
from asmbly_ceramics.domain.studio import CatalogList, Studio
from asmbly_ceramics.mail.compose import austin_time
from asmbly_ceramics.use_cases.notes import NoteRow

# The ruling as a tag: a glyph and words, never colour alone.
RULING_TAGS: Mapping[Ruling | None, str] = {
    Ruling.NOT_ALLOWED: "\N{MULTIPLICATION X} Not allowed",
    Ruling.ALLOWED_WITH_CONDITIONS: "! Allowed with conditions",
    Ruling.ALLOWED: "\N{CHECK MARK} Allowed",
    None: "No ruling",
}
RULING_CLASSES: Mapping[Ruling | None, str] = {
    Ruling.NOT_ALLOWED: "ruling-not-allowed",
    Ruling.ALLOWED_WITH_CONDITIONS: "ruling-conditions",
    Ruling.ALLOWED: "ruling-allowed",
    None: "ruling-none",
}
# The form's radio buttons: the posted value and its label. "" is "No ruling".
RULING_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "No ruling"),
    (Ruling.ALLOWED.value, "Allowed"),
    (Ruling.ALLOWED_WITH_CONDITIONS.value, "Allowed with conditions"),
    (Ruling.NOT_ALLOWED.value, "Not allowed"),
)
NOTE_HINT = (
    f"No names, emails, phone numbers or photos. {NOTE_TEXT_MAX:,} characters at most. "
    "Write a ramp with units or commas (250 °F, 400 °F, 2232 °F)."
)
# A checkbox list sends one field per box ticked: the text, the ruling, the version, the
# CSRF token and `confirm`, beside at most `NOTE_TAGS_MAX` of each list, with room to spare.
NOTE_FORM_FIELDS_MAX = 2 * NOTE_TAGS_MAX + 8


@dataclass(frozen=True)
class NoteForm:
    """What the note form shows: the values typed (after a refusal) or stored, each field's
    message, and the message above the form."""

    text: str = field(default="", repr=False)  # typed by staff: never logged
    glaze_types: tuple[str, ...] = ()
    clay_bodies: tuple[str, ...] = ()
    ruling: str = ""
    errors: Mapping[str, str] = field(default_factory=dict)
    problem: str | None = None

    @classmethod
    def of(cls, note: FiringNote) -> NoteForm:
        """The form for editing `note`, as it is stored."""
        return cls(
            text=note.text,
            glaze_types=tuple(note.glaze_types),
            clay_bodies=tuple(note.clay_bodies),
            ruling="" if note.ruling is None else note.ruling.value,
        )


def _tag_choices(studio: Studio, which: CatalogList, kept: Sequence[ItemId]) -> list[dict[str, Any]]:
    """`taggable_items`: the active items, then any retired one the note already carries,
    marked so."""
    items = taggable_items(studio, which, kept)
    return [
        {"id": item.id, "name": f"{item.name} (retired)" if item.retired else item.name} for item in items
    ]


def form_context(studio: Studio, form: NoteForm, note: FiringNote | None = None) -> dict[str, Any]:
    """The note form's state and choices; `note` is the one being edited, whose retired
    tags stay listed."""
    kept_glazes = note.glaze_types if note else ()
    kept_clays = note.clay_bodies if note else ()
    return {
        "form": form,
        "glaze_choices": _tag_choices(studio, CatalogList.GLAZE_TYPES, kept_glazes),
        "clay_choices": _tag_choices(studio, CatalogList.CLAY_BODIES, kept_clays),
        "ruling_choices": RULING_CHOICES,
        "text_max": NOTE_TEXT_MAX,
        "tags_max": NOTE_TAGS_MAX,
        "hint": NOTE_HINT,
    }


def card(row: NoteRow, *, year: bool = False) -> dict[str, Any]:
    """One note as a card: its ruling tag, tags, text, who wrote it and when, and who last
    edited it; with `year` (the notes search, which reaches back years), each "when"
    carries its year."""
    note = row.note
    edited = None
    if note.edited_by is not None and note.edited_at is not None:
        edited = f"edited by {note.edited_by}, {austin_time(note.edited_at, year=year)}"
    return {
        "id": note.id,
        "load_id": note.load_id,
        "version": note.version,
        "ruling": RULING_TAGS[note.ruling],
        "ruling_class": RULING_CLASSES[note.ruling],
        "glaze_types": row.glaze_types,
        "clay_bodies": row.clay_bodies,
        "text": note.text,
        "written": f"{note.written_by} · {austin_time(note.written_at, year=year)}",
        "edited": edited,
        "kiln": row.kiln,
        "firing_type": row.firing_type,
    }


def section_context(
    studio: Studio,
    rows: Sequence[NoteRow],
    form: NoteForm | None,
    confirm_remove: NoteId | None,
    notice: str | None = None,
) -> dict[str, Any]:
    """The load page's notes: the cards, the add form, a remove waiting for "Yes", and the
    notice after a note was added, saved or removed, shown in the section the page opens at."""
    return {
        "notice": notice,
        "cards": [card(row) for row in rows],
        "add": form_context(studio, form or NoteForm()),
        "add_open": not rows or form is not None,
        "confirm_remove": confirm_remove,
    }
