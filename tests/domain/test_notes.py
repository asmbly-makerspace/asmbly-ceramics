import contextlib
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Literal

import pytest

from asmbly_ceramics.domain.errors import InvalidNote, ItemRetired, LoadNotNotable, NotFound, UnknownItem
from asmbly_ceramics.domain.ids import ItemId, LoadId, NoteId
from asmbly_ceramics.domain.limits import NOTE_TAGS_MAX, NOTE_TEXT_MAX
from asmbly_ceramics.domain.load import LoadStatus
from asmbly_ceramics.domain.notes import (
    TEXT_PERSONAL,
    TEXT_PLAIN,
    TEXT_REQUIRED,
    TEXT_TOO_LONG,
    FiringNote,
    NoteFilter,
    Ruling,
    check_note_text,
    edit_note,
    matches,
    move_note,
    remove_note,
    write_note,
)
from asmbly_ceramics.domain.studio import CatalogItem, CatalogList, Studio, retire_item
from tests.domain.builders import NOW, STAFF, TEST_NOTE_TEXT, a_load, a_note, a_studio, an_address

LATER = NOW + timedelta(hours=2)
OTHER_STAFF = "glaze-lead"
HOUSE_DIP = ItemId("house-dip-glaze")
COMMERCIAL = ItemId("commercial-glaze")
CINCO = ItemId("cinco-blanco")
PORCELAIN = ItemId("cone-5-porcelain")


def _text_error(text: str) -> str:
    with pytest.raises(InvalidNote) as refused:
        check_note_text(text)
    return refused.value.errors["text"]


def _retired(which: CatalogList, id: ItemId) -> Studio:
    studio, _ = retire_item(a_studio(), which, id, STAFF, NOW)
    return studio


# Writing


@pytest.mark.parametrize("status", [LoadStatus.LOADING, LoadStatus.FIRING, LoadStatus.FIRED])
def test_write_note_on_loading_firing_and_fired_loads(status: LoadStatus) -> None:
    load = a_load(4, status, kiln="helios")
    note = a_note(12, load)
    assert note == FiringNote(
        id=NoteId(12),
        load_id=LoadId(4),
        kiln=ItemId("helios"),
        text=TEST_NOTE_TEXT,
        glaze_types=(HOUSE_DIP,),
        clay_bodies=(CINCO,),
        ruling=Ruling.ALLOWED,
        written_by=STAFF,
        written_at=NOW,
    )
    assert not note.removed


def test_no_note_on_deleted_load() -> None:
    with pytest.raises(LoadNotNotable, match="Load L-4 was deleted"):
        a_note(load=a_load(4, LoadStatus.DELETED))


@pytest.mark.parametrize("ruling", [*Ruling, None])
def test_a_note_has_one_ruling_or_none(ruling: Ruling | None) -> None:
    assert a_note(ruling=ruling).ruling is ruling


def test_a_note_may_have_no_tags() -> None:
    note = a_note(glaze_types=(), clay_bodies=())
    assert (note.glaze_types, note.clay_bodies) == ((), ())


def test_write_note_needs_a_username_and_an_aware_time() -> None:
    with pytest.raises(ValueError, match="staff username"):
        a_note(by="")
    with pytest.raises(ValueError, match="aware time"):
        a_note(at=datetime(2026, 11, 13, 18, 30))  # noqa: DTZ001 - the naive time the check refuses


# The text


def test_text_required() -> None:
    assert _text_error("") == TEXT_REQUIRED
    assert _text_error(" \r\n\t ") == TEXT_REQUIRED


def test_text_max_length() -> None:
    assert check_note_text("a" * NOTE_TEXT_MAX) == "a" * NOTE_TEXT_MAX
    assert _text_error("a" * (NOTE_TEXT_MAX + 1)) == TEXT_TOO_LONG
    assert "2,000" in TEXT_TOO_LONG


def test_text_length_is_checked_after_nfc() -> None:
    decomposed = "e\u0301"  # e and a combining acute accent: one character once composed
    assert check_note_text(decomposed * NOTE_TEXT_MAX) == "\u00e9" * NOTE_TEXT_MAX
    assert _text_error(decomposed * (NOTE_TEXT_MAX + 1)) == TEXT_TOO_LONG


def test_text_crlf_to_lf() -> None:
    assert (
        check_note_text("  First line\r\nSecond\rThird\n\tindented  ")
        == "First line\nSecond\nThird\n\tindented"
    )


def test_text_is_nfc() -> None:
    assert check_note_text("Créme glaze") == "Créme glaze"


@pytest.mark.parametrize("control", ["\x00", "\x1b", "\x08", "\x7f"])
def test_text_control_characters_refused(control: str) -> None:
    assert _text_error(f"Glaze{control} test") == TEXT_PLAIN


def test_text_with_email_refused() -> None:
    assert _text_error("Ask " + an_address("someone") + " about it") == TEXT_PERSONAL


@pytest.mark.parametrize(
    ("text", "refused"),
    [
        ("x@y.z", True),
        ("@" + "x@y.z", True),
        ("(" + an_address("someone") + ")", True),
        ("^6@2,236.5 °F", True),
        ("@y.z", False),
        ("x@.z", False),
        ("x@y.", False),
        ("x @ y.z", False),
        ("Fired @ 2,236 °F.", False),
    ],
)
def test_email_shape_is_any_word_with_text_at_text_dot_text(text: str, refused: bool) -> None:
    if refused:
        assert _text_error(text) == TEXT_PERSONAL
    else:
        assert check_note_text(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "@" * NOTE_TEXT_MAX,
        "a@" * (NOTE_TEXT_MAX // 2),
        "x" * (NOTE_TEXT_MAX - 1) + "@",
        "1(" * 1000,
        "+" + "1 " * 999,
        "2 " * 1000,
        "1:" * 1000,
    ],
)
def test_text_checks_stay_fast_on_hostile_text(text: str) -> None:
    """A backtracking pattern takes seconds or more on these; the checks take about a
    millisecond. The limit is far above that, so a slow test machine doesn't fail it."""
    started = time.perf_counter()
    with contextlib.suppress(InvalidNote):
        check_note_text(text)
    assert time.perf_counter() - started < 2.0


def _phone(area: str, exchange: str, line: str, shape: str) -> str:
    """A made-up ten-digit number in `shape`, put together from its digit groups."""
    return shape.format(area=area, exchange=exchange, line=line)


AREA, EXCHANGE, LINE = "512", "555", "01" + "00"  # made-up: 555-0100 to 0199 are fiction's


@pytest.mark.parametrize(
    "shape",
    [
        "{area} {exchange} {line}",
        "({area}) {exchange}-{line}",
        "+1.{area}.{exchange}.{line}",
        "{area}{exchange}{line}",
        "1-{area}-{exchange}-{line}",
        "{area} - {exchange} - {line}",
        "({area})  {exchange} {line}",
        "{area}\u00a0{exchange}\u00a0{line}",  # non-breaking space
        "{area}\u1680{exchange}\u1680{line}",  # a space NFKC leaves as it is
        "{area}\u2011{exchange}\u2011{line}",  # non-breaking hyphen
        "{area}\u2012{exchange}\u2012{line}",  # figure dash
        "{area}\u2013{exchange}\u2013{line}",  # en dash
        "{area}\u2212{exchange}\u2212{line}",  # minus sign
        "{area}/{exchange}-{line}",
        "{area}:{exchange}:{line}",
        "{area}\t{exchange}\t{line}",
        "{area}_{exchange}_{line}",
        "\uff08{area}\uff09{exchange}\uff0d{line}",  # fullwidth brackets and hyphen
        "{area}\u200b{exchange}\u200b{line}",  # zero-width space between groups
        "{area}\u00ad{exchange}\u00ad{line}",  # soft hyphen between groups
        "{area}\u2060{exchange}\u2060{line}",  # word joiner between groups
        "{area} {exchange} 01\u200b00",  # inside the line number
        "5\u00ad12{exchange}{line}",  # inside the area code
        "{area}\n{exchange}\n{line}",  # a newline between groups
        "{area}\u2028{exchange}\u2028{line}",  # line separator between groups
        "{area}\u2029{exchange}-{line}",  # paragraph separator
        "\u202e{area} {exchange} {line}",  # bidi override before it
    ],
)
def test_text_with_phone_refused(shape: str) -> None:
    number = _phone(AREA, EXCHANGE, LINE, shape)
    assert _text_error(f"Call {number} before testing.") == TEXT_PERSONAL


def _digits_as(text: str, zero: str) -> str:
    """`text` with its ASCII digits written in another script, `zero` being its 0."""
    return "".join(chr(ord(zero) + int(c)) if c.isdigit() else c for c in text)


@pytest.mark.parametrize(
    "zero",
    [
        "\uff10",  # fullwidth
        "\u0660",  # Arabic-Indic
        "\u0966",  # Devanagari
    ],
)
def test_text_with_phone_in_other_digits_refused(zero: str) -> None:
    number = _digits_as(_phone(AREA, EXCHANGE, LINE, "{area}-{exchange}-{line}"), zero)
    assert _text_error(f"Call {number}.") == TEXT_PERSONAL


@pytest.mark.parametrize(
    "shape",
    [
        "+44 20 {exchange}{line}",  # a + and ten digits, grouped any way
        "Batch {area}{exchange}{line}9",  # one unbroken group of eleven
        "{area}{exchange}{line}:5",  # a clock time's hour has one or two digits
        "3:{area} {exchange} {line}",  # minutes have two
        "Ramp done at 10:30 {area} {exchange} {line}",
    ],
)
def test_text_with_phone_beside_other_numbers_refused(shape: str) -> None:
    assert _text_error(_phone(AREA, EXCHANGE, LINE, shape)) == TEXT_PERSONAL


@pytest.mark.parametrize(
    "text",
    [
        "^6 at 2,236 °F for 7 min",
        "Fired 2026-11-16 10:30, cones 1, 2, 3, 4, 5 and 6",
        "Fired 2026-11-16 10:30 and again 2026-11-17 09:15",
        "L-4, L-5 and L-6: 48% full",
        "Board 180 °F; 11:42 firing time",
        "Fired 2026-11-16 (48% full)",
        "Fired 2026-11-16 12 hr soak",
        "11-16-2026 48% full",
        "Peak temps 2236 2190 2150",
        "2236-2190-2150",
        "Ramp " + " ".join(("200", "250", "1000")) + " then 400 1900",  # parts: no phone in a file
        "Segments 1 2 3 4 5 6 7 8 9 10",
        "Firing #1042, 9:05:12 total",
    ],
)
def test_text_with_cone_and_temperature_numbers_kept(text: str) -> None:
    assert check_note_text(text) == text


@pytest.mark.parametrize(
    "parts",
    [
        ("Ramp ", "250", " ", "400", " ", "2232"),
        ("350", "/", "250", "/", "2232"),
        ("Ramp ", "250", "\n", "400", "\n", "2232"),
    ],
)
def test_ramp_shaped_like_a_phone_number_refused(parts: Sequence[str]) -> None:
    """A decision (phase 3): three numbers shaped 3-3-4 read as a phone number, so a ramp
    written that way is refused; the note form's hint says to write units or commas."""
    assert _text_error("".join(parts)) == TEXT_PERSONAL


@pytest.mark.parametrize(
    "parts",
    [
        ("Ramp ", "250", "°F ", "400", "°F ", "2232", "°F"),
        ("Ramp ", "250", ", ", "400", ", ", "2232"),
    ],
)
def test_ramp_with_units_or_commas_kept(parts: Sequence[str]) -> None:
    text = "".join(parts)
    assert check_note_text(text) == text


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("Glaze\u200b test", "Glaze test"),
        ("Re\u00adfire", "Refire"),
        ("\u202eCone 6\u202c", "Cone 6"),
        ("Cone\u20606", "Cone6"),
        ("First\u2028second\u2029third", "First\nsecond\nthird"),
        ("Glaze \ue000 test", "Glaze  test"),  # private use
    ],
)
def test_invisible_characters_dropped_and_separators_made_newlines(raw: str, kept: str) -> None:
    assert check_note_text(raw) == kept


@pytest.mark.parametrize(
    ("at", "dot"),
    [
        ("\uff20", "."),  # fullwidth commercial at
        ("\ufe6b", "."),  # small commercial at
        ("@", "\uff0e"),  # fullwidth full stop
        ("\uff20", "\uff0e"),
    ],
)
def test_text_with_email_in_other_forms_refused(at: str, dot: str) -> None:
    address = "someone" + at + "example" + dot + "org"
    assert _text_error(f"Ask {address} about it") == TEXT_PERSONAL


def test_text_with_date_and_time_kept() -> None:
    assert check_note_text("2026-11-16 10:30") == "2026-11-16 10:30"


def test_nine_digits_kept_and_ten_refused() -> None:
    nine = _phone(AREA, EXCHANGE, LINE[:3], "{area} {exchange} {line}")
    assert check_note_text("Batch " + nine) == "Batch " + nine
    assert _text_error("Batch " + _phone(AREA, EXCHANGE, LINE, "{area} {exchange} {line}")) == TEXT_PERSONAL


def test_messages_never_quote_text() -> None:
    secret = "Unmistakable words " + an_address("someone")
    with pytest.raises(InvalidNote) as refused:
        a_note(text=secret, glaze_types=(HOUSE_DIP, HOUSE_DIP))
    shown = [refused.value.message, str(refused.value), *refused.value.errors.values()]
    assert all("Unmistakable" not in message and "@" not in message for message in shown)


def test_errors_gathered_in_one() -> None:
    tags = [f"glaze-{n}" for n in range(NOTE_TAGS_MAX + 1)]
    with pytest.raises(InvalidNote) as refused:
        a_note(text="", glaze_types=tags, clay_bodies=(CINCO, CINCO))
    assert dict(refused.value.errors) == {
        "text": TEXT_REQUIRED,
        "glaze_types": f"Pick at most {NOTE_TAGS_MAX} glaze types.",
        "clay_bodies": "Pick each clay body once.",
    }


# Tags


def test_tags_must_be_active_items() -> None:
    with pytest.raises(UnknownItem, match="glaze type"):
        a_note(glaze_types=("no-such-glaze",))
    with pytest.raises(UnknownItem, match="clay body"):
        a_note(clay_bodies=("no-such-clay",))
    with pytest.raises(ItemRetired, match="Cinco Blanco"):
        a_note(studio=_retired(CatalogList.CLAY_BODIES, CINCO))
    with pytest.raises(ItemRetired, match="House dip glaze"):
        a_note(studio=_retired(CatalogList.GLAZE_TYPES, HOUSE_DIP))


def test_a_cone_is_not_a_clay_body() -> None:
    with pytest.raises(UnknownItem, match="clay body"):
        a_note(clay_bodies=(a_studio().cones[0].id,))


def test_repeated_tag_refused() -> None:
    with pytest.raises(InvalidNote) as refused:
        a_note(glaze_types=(HOUSE_DIP, COMMERCIAL, HOUSE_DIP))
    assert dict(refused.value.errors) == {"glaze_types": "Pick each glaze type once."}


def test_too_many_tags() -> None:
    many = tuple(CatalogItem(ItemId(f"clay-{n}"), f"Clay {n}") for n in range(NOTE_TAGS_MAX + 1))
    studio = replace(a_studio(), clay_bodies=many)
    ids = [item.id for item in many]
    assert len(a_note(clay_bodies=ids[:NOTE_TAGS_MAX], studio=studio).clay_bodies) == NOTE_TAGS_MAX
    with pytest.raises(InvalidNote) as refused:
        a_note(clay_bodies=ids, studio=studio)
    assert dict(refused.value.errors) == {"clay_bodies": f"Pick at most {NOTE_TAGS_MAX} clay bodies."}


# Editing and removing


def _edit(
    note: FiringNote,
    studio: Studio | None = None,
    *,
    text: str | None = None,
    glaze_types: Sequence[str] | None = None,
    clay_bodies: Sequence[str] | None = None,
    ruling: Ruling | Literal["same"] | None = "same",
) -> FiringNote:
    """`note` edited by `OTHER_STAFF` at `LATER`, each part left out kept as it was."""
    return edit_note(
        note,
        note.text if text is None else text,
        note.glaze_types if glaze_types is None else [ItemId(tag) for tag in glaze_types],
        note.clay_bodies if clay_bodies is None else [ItemId(tag) for tag in clay_bodies],
        note.ruling if ruling == "same" else ruling,
        OTHER_STAFF,
        LATER,
        studio or a_studio(),
    )


def test_edit_note_keeps_written_and_stamps_edited() -> None:
    note = a_note()
    edited = _edit(note, text="Crawled at the foot.\r\n", clay_bodies=(PORCELAIN,), ruling=Ruling.NOT_ALLOWED)
    assert edited == replace(
        note,
        text="Crawled at the foot.",
        clay_bodies=(PORCELAIN,),
        ruling=Ruling.NOT_ALLOWED,
        edited_by=OTHER_STAFF,
        edited_at=LATER,
    )
    assert (edited.written_by, edited.written_at) == (STAFF, NOW)


def test_edit_keeps_retired_tag() -> None:
    note = a_note()
    studio = _retired(CatalogList.CLAY_BODIES, CINCO)
    edited = _edit(note, studio, text="Still fine on this clay.")
    assert edited.clay_bodies == (CINCO,)
    with pytest.raises(ItemRetired, match="Cinco Blanco"):
        _edit(a_note(clay_bodies=()), studio, clay_bodies=(CINCO,))


def test_edit_checks_as_write_does() -> None:
    with pytest.raises(InvalidNote) as refused:
        _edit(a_note(), text=" ", glaze_types=(HOUSE_DIP, HOUSE_DIP))
    assert set(refused.value.errors) == {"text", "glaze_types"}
    with pytest.raises(UnknownItem):
        _edit(a_note(), glaze_types=("no-such-glaze",))


def test_edit_with_no_change_is_unchanged() -> None:
    note = a_note()
    assert _edit(note) is note
    assert _edit(note, text=f"  {note.text}\r\n") is note


def test_edit_with_tags_reordered_is_unchanged() -> None:
    note = a_note(glaze_types=(HOUSE_DIP, COMMERCIAL), clay_bodies=(CINCO, PORCELAIN))
    assert _edit(note, glaze_types=(COMMERCIAL, HOUSE_DIP), clay_bodies=(PORCELAIN, CINCO)) is note


def test_note_text_not_in_repr() -> None:
    note = a_note(text="Unmistakable words")
    assert "Unmistakable" not in repr(note)


def test_edit_removed_not_found() -> None:
    removed = remove_note(a_note(12), STAFF, LATER)
    with pytest.raises(NotFound, match="Note N-12 doesn't exist"):
        _edit(removed, text="Changed.")


def test_remove_note() -> None:
    note = a_note()
    removed = remove_note(note, OTHER_STAFF, LATER)
    assert removed == replace(note, removed_by=OTHER_STAFF, removed_at=LATER)
    assert removed.removed


def test_move_note_changes_only_its_kiln() -> None:
    note = _edit(a_note(12, a_load(4, LoadStatus.LOADING, kiln="helios")), text="Crawled at the foot.")
    moved = move_note(note, ItemId("athena"))
    assert moved == replace(note, kiln=ItemId("athena"))


def test_remove_twice_not_found() -> None:
    removed = remove_note(a_note(12), STAFF, LATER)
    with pytest.raises(NotFound, match="Note N-12"):
        remove_note(removed, STAFF, LATER)


def test_edit_and_remove_need_a_username_and_an_aware_time() -> None:
    with pytest.raises(ValueError, match="staff username"):
        remove_note(a_note(), "", LATER)
    with pytest.raises(ValueError, match="aware time"):
        remove_note(a_note(), STAFF, datetime(2026, 11, 13, 18, 30))  # noqa: DTZ001 - refused
    with pytest.raises(ValueError, match="staff username"):
        edit_note(a_note(), "Changed.", (), (), None, "", LATER, a_studio())


# Filtering


def test_matches_each_filter_part() -> None:
    note = a_note(load=a_load(status=LoadStatus.FIRED, kiln="helios"))
    assert matches(note, NoteFilter())
    assert matches(note, NoteFilter(kiln=ItemId("helios")))
    assert not matches(note, NoteFilter(kiln=ItemId("athena")))
    assert matches(note, NoteFilter(glaze_type=HOUSE_DIP))
    assert not matches(note, NoteFilter(glaze_type=COMMERCIAL))
    assert matches(note, NoteFilter(clay_body=CINCO))
    assert not matches(note, NoteFilter(clay_body=PORCELAIN))
    assert matches(note, NoteFilter(ruling=Ruling.ALLOWED))
    assert not matches(note, NoteFilter(ruling=Ruling.NOT_ALLOWED))
    assert matches(note, NoteFilter(ItemId("helios"), HOUSE_DIP, CINCO, Ruling.ALLOWED))
    assert not matches(note, NoteFilter(ItemId("helios"), HOUSE_DIP, PORCELAIN, Ruling.ALLOWED))


def test_matches_no_ruling() -> None:
    assert matches(a_note(ruling=None), NoteFilter(ruling=None))
    assert not matches(a_note(ruling=Ruling.ALLOWED), NoteFilter(ruling=None))
    assert matches(a_note(ruling=None), NoteFilter(ruling="any"))


def test_removed_never_matches() -> None:
    removed = remove_note(a_note(), STAFF, LATER)
    assert not matches(removed, NoteFilter())
    assert not matches(removed, NoteFilter(kiln=removed.kiln, ruling="any"))


def test_write_note_takes_the_loads_id_and_kiln() -> None:
    load = a_load(7, LoadStatus.LOADING, kiln="vulcan")
    note = write_note(NoteId(3), load, "Testing a new clay.", [], [PORCELAIN], None, STAFF, NOW, a_studio())
    assert (note.load_id, note.kiln, note.clay_bodies) == (LoadId(7), ItemId("vulcan"), (PORCELAIN,))
