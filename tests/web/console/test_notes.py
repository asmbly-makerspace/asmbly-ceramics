"""Firing notes in the console (#17): adding, editing and removing a load's notes, the
notes search, every field checked on the server, the text escaped, and only for
signed-in ceramics staff. Note text is made up and holds no person's details."""

import html
import re
from datetime import timedelta

import httpx2
import pytest

from asmbly_ceramics.domain.ids import ItemId, LoadId, NoteId
from asmbly_ceramics.domain.limits import NOTE_TAGS_MAX, NOTE_TEXT_MAX
from asmbly_ceramics.domain.notes import TEXT_PERSONAL, TEXT_REQUIRED, FiringNote, Ruling
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.records import CommitOutcomeUnknown
from asmbly_ceramics.use_cases.loads import ViewLoad
from asmbly_ceramics.use_cases.notes import NoteInput, SearchNotes
from asmbly_ceramics.web.console.note_views import (
    NOTE_FORM_FIELDS_MAX,
    NOTE_HINT,
    RULING_CHOICES,
    RULING_CLASSES,
    RULING_TAGS,
    NoteForm,
)
from asmbly_ceramics.web.console.notes import (
    NOTE_CHANGED,
    NOTE_CHANGED_NOT_REMOVED,
    PICK_RULING,
    SEARCH_RULINGS,
    _Posted,
)
from tests.domain.builders import TEST_NOTE_TEXT, TEST_PHONE, an_address
from tests.use_cases.flows import ATHENA, BISQUE, HELIOS, STAFF_MEMBER, version
from tests.web.console.conftest import OUTSIDER, Console

L_1, L_2 = LoadId(1), LoadId(2)
N_1 = NoteId(1)
HOUSE_DIP = ItemId("house-dip-glaze")
COMMERCIAL = ItemId("commercial-glaze")
CINCO = ItemId("cinco-blanco")
BUFFALO = ItemId("buffalo-wallow")
NOTES = "/console/loads/L-1/notes"
SEARCH = "/console/notes"
NO_PERSONAL = "No names, emails, phone numbers or photos."


@pytest.fixture
def staff(console: Console) -> Console:
    console.sign_in()
    return console


def text(answer: httpx2.Response) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", answer.text)).split())


def a_load(console: Console, *, kiln: ItemId = ATHENA, fired: bool = False) -> LoadId:
    world = console.world
    load_id = world.start_load(kiln, BISQUE, None, STAFF_MEMBER, test=True).id
    if fired:
        world.start_firing(load_id, version(world, load_id), STAFF_MEMBER)
        world.mark_fired(load_id, version(world, load_id), STAFF_MEMBER)
    return load_id


def a_note(
    console: Console,
    load_id: LoadId = L_1,
    *,
    text: str = TEST_NOTE_TEXT,
    glaze_types: tuple[ItemId, ...] = (HOUSE_DIP,),
    clay_bodies: tuple[ItemId, ...] = (CINCO,),
    ruling: Ruling | None = Ruling.ALLOWED,
) -> NoteId:
    note = NoteInput(text, glaze_types, clay_bodies, ruling)
    return console.world.write_note(load_id, note, STAFF_MEMBER).id


def stored(console: Console, load_id: LoadId = L_1, note_id: NoteId = N_1) -> FiringNote:
    note = console.world.records.note(load_id, note_id)
    assert note is not None
    return note


def fields(
    note_text: str = TEST_NOTE_TEXT,
    ruling: str = "not_allowed",
    glaze_types: list[str] | None = None,
    clay_bodies: list[str] | None = None,
) -> dict[str, str | list[str]]:
    return {
        "text": note_text,
        "ruling": ruling,
        "glaze_types": [HOUSE_DIP] if glaze_types is None else glaze_types,
        "clay_bodies": [CINCO, BUFFALO] if clay_bodies is None else clay_bodies,
    }


def edit_fields(console: Console, **changes: str | list[str]) -> dict[str, str | list[str]]:
    return {**fields(), "version": str(stored(console).version), **changes}


# --- adding ----------------------------------------------------------------------------------


def test_add_note(staff: Console) -> None:
    a_load(staff)

    answer = staff.post(NOTES, fields())

    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/loads/L-1?done=note-added#notes"
    note = stored(staff)
    assert (note.text, note.ruling, note.glaze_types, note.clay_bodies) == (
        TEST_NOTE_TEXT,
        Ruling.NOT_ALLOWED,
        (HOUSE_DIP,),
        (CINCO, BUFFALO),
    )
    assert note.written_by == STAFF_MEMBER.username
    page = text(staff.get("/console/loads/L-1?done=note-added"))
    assert "Note added." in page
    section = staff.get("/console/loads/L-1?done=note-added").text.split('id="notes"', 1)[1]
    assert '<div class="notice" role="status"><p>Note added.</p></div>' in section
    assert "Notes (1)" in page
    assert "✕ Not allowed" in page
    assert "Glaze: House dip glaze" in page
    assert "Clay: Cinco Blanco Clay: Buffalo Wallow" in page
    assert TEST_NOTE_TEXT in page
    assert f"{STAFF_MEMBER.username} · Fri Nov 13," in page


def test_add_note_on_fired_load(staff: Console) -> None:
    a_load(staff, fired=True)

    answer = staff.post(NOTES, fields(ruling=""))

    assert answer.status_code == 303
    assert stored(staff).ruling is None
    assert "No ruling" in text(staff.get("/console/loads/L-1"))


def test_load_page_lists_notes_newest_first(staff: Console) -> None:
    a_load(staff)
    a_note(staff, text="Earlier made-up note about crawling.")
    staff.world.clock.advance(timedelta(minutes=5))
    a_note(staff, text="Later made-up note about pinholes.")

    page = text(staff.get("/console/loads/L-1"))

    assert page.index("Later made-up note") < page.index("Earlier made-up note")
    assert "Add a note" in page


def test_add_form_is_open_only_when_there_are_no_notes(staff: Console) -> None:
    a_load(staff)
    assert "<details open>\n    <summary>Add a note" in staff.get("/console/loads/L-1").text
    a_note(staff)
    assert "<details>\n    <summary>Add a note" in staff.get("/console/loads/L-1").text


def test_add_note_text_required(staff: Console) -> None:
    a_load(staff)

    answer = staff.post(NOTES, fields(note_text="   "))

    assert answer.status_code == 422
    assert TEXT_REQUIRED in text(answer)
    assert not staff.world.records.notes_for(L_1)


@pytest.mark.parametrize(
    "typed",
    [
        "Ask " + an_address("glaze.tester") + " about this glaze.",
        "Call " + TEST_PHONE + " about the shelf.",
    ],
    ids=["email", "phone"],
)
def test_add_note_with_personal_details_refused(staff: Console, typed: str) -> None:
    a_load(staff)

    answer = staff.post(NOTES, fields(note_text=typed))

    assert answer.status_code == 422
    assert TEXT_PERSONAL in text(answer)
    assert not staff.world.records.notes_for(L_1)
    assert staff.world.ids.next_note_id() == N_1  # no number spent


def test_add_note_bad_ruling(staff: Console) -> None:
    a_load(staff)

    answer = staff.post(NOTES, fields(note_text="", ruling="maybe"))

    assert answer.status_code == 422
    assert PICK_RULING in text(answer)
    assert TEXT_REQUIRED in text(answer)  # both refusals at once
    assert 'value="maybe"' not in answer.text  # never echoed
    assert not staff.world.records.notes_for(L_1)


def test_add_note_keeps_what_was_typed(staff: Console) -> None:
    a_load(staff)

    answer = staff.post(NOTES, fields(note_text="Made-up note, then a bad ruling.", ruling="maybe"))

    assert "Made-up note, then a bad ruling.</textarea>" in answer.text
    assert f'name="glaze_types" value="{HOUSE_DIP}" checked' in answer.text
    assert f'name="clay_bodies" value="{BUFFALO}" checked' in answer.text


@pytest.mark.parametrize("tag", ["no-such-glaze", "Not An Item!"])
def test_add_note_unknown_tag(staff: Console, tag: str) -> None:
    a_load(staff)

    answer = staff.post(NOTES, fields(glaze_types=[tag]))

    assert answer.status_code == 422
    assert "That glaze type doesn't exist." in text(answer)
    assert "Not An Item!" not in answer.text
    assert not staff.world.records.notes_for(L_1)


def test_add_note_retired_tag_refused(staff: Console) -> None:
    a_load(staff)
    world = staff.world
    world.retire_item(CatalogList.GLAZE_TYPES, COMMERCIAL, world.studio().version, STAFF_MEMBER)

    answer = staff.post(NOTES, fields(glaze_types=[COMMERCIAL]))

    assert answer.status_code == 422
    assert "Commercial glaze is retired and can't be picked." in text(answer)


def test_add_note_too_many_tags(staff: Console) -> None:
    a_load(staff)
    tags = [f"glaze-{n}" for n in range(NOTE_TAGS_MAX + 1)]

    answer = staff.post(NOTES, fields(glaze_types=tags, clay_bodies=[]))

    assert answer.status_code == 422
    assert f"Pick at most {NOTE_TAGS_MAX} glaze types." in text(answer)


def test_the_note_form_takes_every_tag_box_but_not_more_fields(staff: Console) -> None:
    a_load(staff)
    full = fields(
        glaze_types=[f"glaze-{n}" for n in range(NOTE_TAGS_MAX)],
        clay_bodies=[f"clay-{n}" for n in range(NOTE_TAGS_MAX)],
    )
    assert staff.post(NOTES, full).status_code == 422  # read, then refused as unknown items

    flood = fields(glaze_types=[f"glaze-{n}" for n in range(NOTE_FORM_FIELDS_MAX)])
    assert staff.post(NOTES, flood).status_code == 400


def test_add_note_text_escaped(staff: Console) -> None:
    a_load(staff)

    staff.post(NOTES, fields(note_text="<script>alert(1)</script> & <b>bold</b>"))
    page = staff.get("/console/loads/L-1").text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;" in page


HOSTILE = "Made-up </textarea><script>alert(1)</script> note."
HOSTILE_ESCAPED = "Made-up &lt;/textarea&gt;&lt;script&gt;alert(1)&lt;/script&gt; note."


def assert_escaped(page: str) -> None:
    assert "<script>alert(1)</script>" not in page
    assert "</textarea><script>" not in page
    assert HOSTILE_ESCAPED in page


def test_typed_text_echoed_into_the_textarea_is_escaped(staff: Console) -> None:
    a_load(staff)

    refused = staff.post(NOTES, fields(note_text=HOSTILE, ruling="maybe"))

    assert refused.status_code == 422
    assert_escaped(refused.text)
    assert f"{HOSTILE_ESCAPED}</textarea>" in refused.text


def test_stored_text_on_the_edit_page_and_its_refusal_is_escaped(staff: Console) -> None:
    a_load(staff)
    a_note(staff, text=HOSTILE)

    form = staff.get("/console/loads/L-1/notes/N-1/edit")
    refused = staff.post(
        "/console/loads/L-1/notes/N-1/edit", edit_fields(staff, text=HOSTILE, ruling="maybe")
    )

    for answer in (form, refused):
        assert_escaped(answer.text)
        assert f"{HOSTILE_ESCAPED}</textarea>" in answer.text
    assert refused.status_code == 422


def test_search_card_text_is_escaped(staff: Console) -> None:
    a_load(staff)
    a_note(staff, text=HOSTILE)

    answer = staff.get(SEARCH)

    assert listed(answer) == ["N-1"]
    assert_escaped(answer.text)


def test_posted_note_repr_holds_no_text() -> None:
    note = NoteInput("Made-up secret glaze words.", (HOUSE_DIP,), (), None)
    posted = _Posted(NoteForm(text=note.text), note)
    for shown in (repr(note), repr(posted)):
        assert "Made-up secret glaze words." not in shown


def test_add_note_to_a_missing_load_is_404(staff: Console) -> None:
    assert staff.post("/console/loads/L-9/notes", fields()).status_code == 404


def test_add_note_after_the_load_changed_keeps_the_text(staff: Console) -> None:
    """`WriteNote` commits with the load as read: a kiln change in between is a `Conflict`,
    and the page keeps what was typed."""
    a_load(staff)
    world = staff.world
    real_load = world.records.load

    def kiln_changed_after_the_read(id: LoadId) -> object:
        read = real_load(id)
        world.records.load = real_load  # type: ignore[method-assign]  # once
        assert read is not None
        world.change_load(id, HELIOS, BISQUE, read.date, read.version, STAFF_MEMBER, test=True)
        return read

    world.records.load = kiln_changed_after_the_read  # type: ignore[method-assign,assignment]
    answer = staff.post(NOTES, fields(note_text="Made-up note that clashed."))

    assert answer.status_code == 409
    assert "Your note wasn't saved" in text(answer)
    assert "Made-up note that clashed.</textarea>" in answer.text
    assert not world.records.notes_for(L_1)


def test_notes_form_limits_match_domain(staff: Console) -> None:
    a_load(staff)
    page = staff.get("/console/loads/L-1").text
    assert f'name="text" rows="5" maxlength="{NOTE_TEXT_MAX}" required' in page
    assert f"{NOTE_TEXT_MAX:,} characters at most." in NOTE_HINT
    assert f"{NOTE_TEXT_MAX:,} characters at most." in html.unescape(page)
    assert f"Glaze types (at most {NOTE_TAGS_MAX})" in page


def test_note_form_says_no_personal_details(staff: Console) -> None:
    a_load(staff)
    a_note(staff)
    for path in ("/console/loads/L-1", "/console/loads/L-1/notes/N-1/edit"):
        page = text(staff.get(path))
        assert NO_PERSONAL in page, path
        assert html.unescape(NOTE_HINT) in page, path
        assert "Write a ramp with units or commas" in page, path


# --- editing -----------------------------------------------------------------------------------


def test_edit_note(staff: Console) -> None:
    a_load(staff)
    a_note(staff)

    form = staff.get("/console/loads/L-1/notes/N-1/edit")
    assert form.status_code == 200
    assert f"{TEST_NOTE_TEXT}</textarea>" in form.text
    assert 'name="ruling" value="allowed" checked' in form.text

    answer = staff.post(
        "/console/loads/L-1/notes/N-1/edit", edit_fields(staff, text="Made-up edit.", ruling="")
    )

    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/loads/L-1?done=note-saved#notes"
    note = stored(staff)
    assert (note.text, note.ruling, note.edited_by) == ("Made-up edit.", None, STAFF_MEMBER.username)
    assert note.written_by == STAFF_MEMBER.username
    page = text(staff.get("/console/loads/L-1?done=note-saved"))
    assert "Note saved." in page
    assert f"edited by {STAFF_MEMBER.username}, Fri Nov 13," in page


def test_edit_refused_keeps_what_was_typed(staff: Console) -> None:
    a_load(staff)
    a_note(staff)

    answer = staff.post("/console/loads/L-1/notes/N-1/edit", edit_fields(staff, text=""))

    assert answer.status_code == 422
    assert TEXT_REQUIRED in text(answer)
    assert stored(staff).text == TEST_NOTE_TEXT


def test_edit_shows_retired_tag_checked(staff: Console) -> None:
    a_load(staff)
    a_note(staff, glaze_types=(COMMERCIAL,))
    world = staff.world
    world.retire_item(CatalogList.GLAZE_TYPES, COMMERCIAL, world.studio().version, STAFF_MEMBER)

    form = staff.get("/console/loads/L-1/notes/N-1/edit")

    assert (
        f'name="glaze_types" value="{COMMERCIAL}" checked> <span>Commercial glaze (retired)</span>'
        in form.text
    )
    kept = staff.post("/console/loads/L-1/notes/N-1/edit", edit_fields(staff, glaze_types=[COMMERCIAL]))
    assert kept.status_code == 303


def test_edit_conflict(staff: Console) -> None:
    a_load(staff)
    a_note(staff)
    stale = str(stored(staff).version)
    staff.post("/console/loads/L-1/notes/N-1/edit", edit_fields(staff, text="Made-up first edit."))

    answer = staff.post(
        "/console/loads/L-1/notes/N-1/edit", edit_fields(staff, text="Made-up second.", version=stale)
    )

    assert answer.status_code == 409
    assert NOTE_CHANGED in text(answer)
    assert "Made-up second.</textarea>" in answer.text
    assert f'name="version" value="{stored(staff).version}"' in answer.text
    assert stored(staff).text == "Made-up first edit."
    now = answer.text.split('id="note-now"', 1)[1].split("</section>", 1)[0]
    assert '<p class="note-text">Made-up first edit.</p>' in now
    assert f"edited by {STAFF_MEMBER.username}" in now


def version_sent(answer: httpx2.Response) -> str:
    found = re.search(r'name="version" value="([0-9]+)"', answer.text)
    assert found is not None
    return found.group(1)


@pytest.mark.parametrize("refusal", [{"text": ""}, {"ruling": "perhaps"}])
def test_a_refused_edit_then_saved_over_a_newer_version_is_a_conflict(
    staff: Console, refusal: dict[str, str]
) -> None:
    """A opens the edit, B changes the ruling, A's save is refused and fixed: the refusal
    sends back the version A typed against, so A's next save is a `Conflict`, not an
    overwrite of B's change."""
    a_load(staff)
    a_note(staff)
    opened = version_sent(staff.get("/console/loads/L-1/notes/N-1/edit"))
    b_saved = staff.post(
        "/console/loads/L-1/notes/N-1/edit", edit_fields(staff, ruling="allowed_with_conditions")
    )
    assert b_saved.status_code == 303

    refused = staff.post("/console/loads/L-1/notes/N-1/edit", edit_fields(staff, version=opened, **refusal))
    assert refused.status_code == 422
    assert version_sent(refused) == opened

    fixed = staff.post(
        "/console/loads/L-1/notes/N-1/edit",
        edit_fields(staff, text="Made-up fix.", ruling="not_allowed", version=version_sent(refused)),
    )

    assert fixed.status_code == 409
    assert NOTE_CHANGED in text(fixed)
    assert stored(staff).ruling is Ruling.ALLOWED_WITH_CONDITIONS
    assert stored(staff).text == TEST_NOTE_TEXT


def test_the_ruling_labels_cover_every_ruling() -> None:
    for table in (RULING_TAGS, RULING_CLASSES):
        assert set(table) == {*Ruling, None}
    assert {value for value, _ in RULING_CHOICES} == {"", *(ruling.value for ruling in Ruling)}
    assert {value for value, _ in SEARCH_RULINGS} == {"any", "none", *(ruling.value for ruling in Ruling)}


def test_edit_page_shows_the_stored_note_only_after_a_conflict(staff: Console) -> None:
    a_load(staff)
    a_note(staff)

    assert 'id="note-now"' not in staff.get("/console/loads/L-1/notes/N-1/edit").text
    refused = staff.post("/console/loads/L-1/notes/N-1/edit", edit_fields(staff, text=""))
    assert 'id="note-now"' not in refused.text


def test_edit_page_reads_only_the_note_not_the_whole_load(
    staff: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The title comes from the note's row: the edit page never reads the load's members,
    emails, history or waiting list, so a load deleted in between can't make it fail."""
    a_load(staff)
    a_note(staff)

    def no_view(*_: object, **__: object) -> object:
        raise AssertionError("the edit page read the whole load")

    monkeypatch.setattr(ViewLoad, "__call__", no_view)
    form = staff.get("/console/loads/L-1/notes/N-1/edit")
    refused = staff.post("/console/loads/L-1/notes/N-1/edit", edit_fields(staff, text=""))

    assert form.status_code == 200
    assert refused.status_code == 422
    assert '<a href="/console/loads/L-1#notes" class="mono">L-1</a> · Athena · Bisque ·' in form.text


def test_edit_unknown_note_404(staff: Console) -> None:
    a_load(staff)
    assert staff.get("/console/loads/L-1/notes/N-7/edit").status_code == 404
    assert staff.get("/console/loads/L-1/notes/nope/edit").status_code == 404
    assert staff.post("/console/loads/L-1/notes/N-7/edit", fields() | {"version": "0"}).status_code == 404


def test_edit_note_of_other_load_404(staff: Console) -> None:
    a_load(staff)
    a_load(staff)
    a_note(staff, L_1)

    assert staff.get("/console/loads/L-2/notes/N-1/edit").status_code == 404
    answer = staff.post("/console/loads/L-2/notes/N-1/edit", fields() | {"version": "1"})
    assert answer.status_code == 404
    assert stored(staff).text == TEST_NOTE_TEXT


# --- removing --------------------------------------------------------------------------------


def test_remove_needs_confirm(staff: Console) -> None:
    a_load(staff)
    a_note(staff)

    answer = staff.post("/console/loads/L-1/notes/N-1/remove", {"version": str(stored(staff).version)})

    assert answer.status_code == 200
    page = text(answer)
    assert "Remove this note? It disappears from this load and from the notes search." in page
    assert "Yes, remove" in page
    assert "Keep it" in page
    assert not stored(staff).removed


def test_remove_note(staff: Console) -> None:
    a_load(staff)
    a_note(staff)

    answer = staff.post(
        "/console/loads/L-1/notes/N-1/remove", {"version": str(stored(staff).version), "confirm": "1"}
    )

    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/loads/L-1?done=note-removed#notes"
    assert stored(staff).removed_by == STAFF_MEMBER.username
    page = text(staff.get("/console/loads/L-1?done=note-removed"))
    assert "Note removed." in page
    assert "Notes (0)" in page
    assert TEST_NOTE_TEXT not in page


def test_remove_with_a_stale_version_changes_nothing(staff: Console) -> None:
    a_load(staff)
    a_note(staff)

    answer = staff.post("/console/loads/L-1/notes/N-1/remove", {"version": "99", "confirm": "1"})

    assert answer.status_code == 409
    assert NOTE_CHANGED_NOT_REMOVED in text(answer)
    assert "save again" not in text(answer)
    assert not stored(staff).removed


def test_remove_unknown_note_404(staff: Console) -> None:
    a_load(staff)
    assert staff.post("/console/loads/L-1/notes/N-4/remove", {"version": "0"}).status_code == 404
    assert (
        staff.post("/console/loads/L-1/notes/N-4/remove", {"version": "0", "confirm": "1"}).status_code == 404
    )


@pytest.mark.parametrize(
    ("path", "data"),
    [
        (NOTES, fields()),
        ("/console/loads/L-1/notes/N-1/edit", {**fields(note_text="Made-up edit."), "version": "1"}),
        ("/console/loads/L-1/notes/N-1/remove", {"version": "1", "confirm": "1"}),
    ],
    ids=["write", "edit", "remove"],
)
def test_a_commit_that_may_have_landed_says_to_check(
    staff: Console, path: str, data: dict[str, str | list[str]]
) -> None:
    a_load(staff)
    a_note(staff)
    staff.world.records.fail_next_commit_with = CommitOutcomeUnknown("RequestTimeout")

    answer = staff.post(path, data)

    assert answer.status_code == 503
    assert "That may or may not have been saved." in text(answer)


def test_notes_of_a_deleted_load_are_gone(staff: Console) -> None:
    a_load(staff)
    a_note(staff)
    world = staff.world
    world.delete_load(L_1, version(world, L_1), STAFF_MEMBER)

    assert staff.get("/console/loads/L-1/notes/N-1/edit").status_code == 404
    assert staff.post(NOTES, fields()).status_code == 404
    assert listed(staff.get(SEARCH)) == []


# --- the search ------------------------------------------------------------------------------


def listed(answer: httpx2.Response) -> list[str]:
    return re.findall(r'<li class="note-card" id="note-(N-[0-9]+)"', answer.text)


def test_search_each_filter(staff: Console) -> None:
    athena = a_load(staff)
    helios = a_load(staff, kiln=HELIOS)
    a_note(staff, athena, glaze_types=(HOUSE_DIP,), clay_bodies=(CINCO,), ruling=Ruling.ALLOWED)
    a_note(staff, helios, glaze_types=(COMMERCIAL,), clay_bodies=(BUFFALO,), ruling=Ruling.NOT_ALLOWED)
    a_note(staff, helios, glaze_types=(), clay_bodies=(), ruling=None)

    assert listed(staff.get(SEARCH)) == ["N-3", "N-2", "N-1"]
    assert listed(staff.get(f"{SEARCH}?kiln=helios")) == ["N-3", "N-2"]
    assert listed(staff.get(f"{SEARCH}?glaze=house-dip-glaze")) == ["N-1"]
    assert listed(staff.get(f"{SEARCH}?clay=buffalo-wallow")) == ["N-2"]
    assert listed(staff.get(f"{SEARCH}?ruling=not_allowed")) == ["N-2"]
    assert listed(staff.get(f"{SEARCH}?ruling=none")) == ["N-3"]
    assert listed(staff.get(f"{SEARCH}?ruling=any")) == ["N-3", "N-2", "N-1"]
    assert listed(staff.get(f"{SEARCH}?from=2026-11-14&to=2026-11-20")) == []
    assert listed(staff.get(f"{SEARCH}?from=2026-11-13&to=2026-11-13")) == ["N-3", "N-2", "N-1"]
    chosen = staff.get(f"{SEARCH}?kiln=helios&ruling=none")
    assert '<option value="helios" selected>' in chosen.text
    assert '<option value="none" selected>' in chosen.text


def test_search_bad_values_messages(staff: Console) -> None:
    a_load(staff)
    a_note(staff)

    answer = staff.get(
        f"{SEARCH}?kiln=nowhere-kiln&glaze=Bad!Glaze&clay=no-such-clay&ruling=perhaps&from=13/11/2026"
    )

    assert answer.status_code == 200
    page = text(answer)
    for message in (
        "Pick a kiln from the list.",
        "Pick a glaze type from the list.",
        "Pick a clay body from the list.",
        PICK_RULING,
        "Enter dates like 2026-11-13.",
    ):
        assert message in page
    for typed in ("nowhere-kiln", "Bad!Glaze", "no-such-clay", "perhaps", "13/11/2026"):
        assert typed not in answer.text
    assert listed(answer) == ["N-1"]  # each refused filter is ignored


def test_search_too_long_a_range_falls_back(staff: Console) -> None:
    a_load(staff)
    a_note(staff)

    answer = staff.get(f"{SEARCH}?from=2000-01-01&to=2026-11-13")

    assert "Choose a date range of at most 5 years" in text(answer)
    assert listed(answer) == ["N-1"]


def test_search_falls_back_when_an_item_is_deleted_meanwhile(
    staff: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clay body deleted between the page's check and the search's own: the search runs
    again without it and says so, rather than failing."""
    a_load(staff)
    a_note(staff)
    world = staff.world
    search = SearchNotes.__call__
    calls: list[object] = []

    def deleted_meanwhile(self: SearchNotes, *args: object, **kwargs: object) -> object:
        calls.append(args)
        if len(calls) == 1:
            world.retire_item(CatalogList.CLAY_BODIES, BUFFALO, world.studio().version, STAFF_MEMBER)
            world.delete_item(CatalogList.CLAY_BODIES, BUFFALO, world.studio().version, STAFF_MEMBER)
        return search(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SearchNotes, "__call__", deleted_meanwhile)
    answer = staff.get(f"{SEARCH}?clay=buffalo-wallow")

    assert answer.status_code == 200
    assert "Pick a clay body from the list." in text(answer)
    assert listed(answer) == ["N-1"]
    assert len(calls) == 2


def test_search_cards_show_the_year_and_the_load_page_s_don_t(staff: Console) -> None:
    """The search reaches back years: its cards' "when" carries the year."""
    a_load(staff)
    a_note(staff)
    staff.post("/console/loads/L-1/notes/N-1/edit", edit_fields(staff, text="Made-up edit."))
    user = STAFF_MEMBER.username

    search = text(staff.get(SEARCH))
    load_page = text(staff.get("/console/loads/L-1"))

    assert re.search(rf"{user} · Fri Nov 13, 2026, [0-9]+:[0-9]{{2}} [AP]M", search)
    assert re.search(rf"edited by {user}, Fri Nov 13, 2026, [0-9]+:[0-9]{{2}} [AP]M", search)
    assert re.search(rf"{user} · Fri Nov 13, [0-9]+:[0-9]{{2}} [AP]M", load_page)
    assert f"{user} · Fri Nov 13, 2026" not in load_page


def test_search_links_to_load(staff: Console) -> None:
    a_load(staff)
    a_note(staff)

    answer = staff.get(SEARCH)

    assert '<a href="/console/loads/L-1#notes" class="mono">L-1</a> · Athena · Bisque' in answer.text
    assert TEST_NOTE_TEXT in text(answer)


def test_search_no_notes_match(staff: Console) -> None:
    assert "No notes match." in text(staff.get(SEARCH))


def test_firing_log_and_notes_link_to_each_other(staff: Console) -> None:
    notes = staff.get(SEARCH).text
    log = staff.get("/console/firing-log").text
    assert '<a href="/console/notes" aria-current="page">Notes</a>' in notes
    assert '<a href="/console/firing-log">Firings</a>' in notes
    assert '<a href="/console/firing-log" aria-current="page">Firings</a>' in log
    assert '<a href="/console/notes">Notes</a>' in log
    assert 'href="/console/firing-log" aria-current="page">Firing log</a>' in notes  # the tab


# --- who may -----------------------------------------------------------------------------------


def test_outside_the_group_can_t_read_or_write_notes(console: Console) -> None:
    a_load(console)
    a_note(console)
    console.sign_in(groups=("front-desk",), username=OUTSIDER)

    for answer in (
        console.get(SEARCH),
        console.get("/console/loads/L-1/notes/N-1/edit"),
        console.post(NOTES, fields(note_text="Made-up outsider note.")),
        console.post("/console/loads/L-1/notes/N-1/edit", edit_fields(console, text="Made-up.")),
        console.post("/console/loads/L-1/notes/N-1/remove", {"version": "1", "confirm": "1"}),
    ):
        assert answer.status_code == 403
        assert "don&#39;t have access to the ceramics console" in answer.text
        assert TEST_NOTE_TEXT not in answer.text
    assert [note.id for note in console.world.records.notes_for(L_1)] == [N_1]
    assert stored(console).text == TEST_NOTE_TEXT
    assert not stored(console).removed


def test_signed_out_can_t_read_notes(console: Console) -> None:
    a_load(console)
    a_note(console)
    for path in (SEARCH, "/console/loads/L-1/notes/N-1/edit"):
        answer = console.get(path)
        assert answer.status_code == 302
        assert TEST_NOTE_TEXT not in answer.text


def test_note_posts_need_the_csrf_token(staff: Console) -> None:
    a_load(staff)
    a_note(staff)
    for path, data in (
        (NOTES, fields()),
        ("/console/loads/L-1/notes/N-1/edit", edit_fields(staff, text="Made-up.")),
        ("/console/loads/L-1/notes/N-1/remove", {"version": "1", "confirm": "1"}),
    ):
        assert staff.post(path, data, csrf=False).status_code == 403, path
    assert [note.id for note in staff.world.records.notes_for(L_1)] == [N_1]
    assert stored(staff).text == TEST_NOTE_TEXT
