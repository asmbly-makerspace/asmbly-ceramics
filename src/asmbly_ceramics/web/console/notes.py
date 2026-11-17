"""Firing notes in the console (#17): adding, editing and removing a load's notes, and the
notes search.

The use cases decide every rule and log every change, by note ID, load ID and username.
A note's text is typed by staff: it travels only in a POST body, is shown only through
autoescape, and is never logged or put in an address. After a change a page answers 303
to the load's notes with a fixed word in the address (Post/Redirect/Get); a refusal
shows the form again with what was typed and the messages (422). The search is a read:
a GET form with no CSRF token, every query parameter checked by its shape and never
echoed.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from asmbly_ceramics.domain.errors import (
    InvalidLogRange,
    InvalidNote,
    ItemRetired,
    NotFound,
    UnknownItem,
)
from asmbly_ceramics.domain.ids import ItemId, LoadId, NoteId, is_item_id
from asmbly_ceramics.domain.notes import NoteFilter, Ruling, check_note_text
from asmbly_ceramics.domain.studio import CatalogList, Studio, kind_name
from asmbly_ceramics.mail.compose import austin_date
from asmbly_ceramics.ports.records import CommitOutcomeUnknown, Conflict
from asmbly_ceramics.use_cases.notes import NoteInput, NoteRow, NoteSearchView
from asmbly_ceramics.web.console.auth import require_staff, require_staff_post
from asmbly_ceramics.web.console.common import PostedForm, Staff, form_version, parse_date, render, services
from asmbly_ceramics.web.console.loads import MAYBE_SAVED, load_id, load_page_for
from asmbly_ceramics.web.console.note_views import (
    NOTE_FORM_FIELDS_MAX,
    RULING_CHOICES,
    NoteForm,
    card,
    form_context,
)
from asmbly_ceramics.web.errors import PageError

PICK_RULING = "Pick a ruling from the list."
NOTE_CHANGED = "Someone else changed this note. Check it and save again."
NOTE_CHANGED_NOT_REMOVED = (
    "Someone else changed this note, so it wasn't removed. "
    "Check it, and remove it again if you still want to."
)
LOAD_CHANGED = "Someone else changed this load while you wrote. Your note wasn't saved: save it again."
BAD_DATES = "Enter dates like 2026-11-13."
PICK = "Pick a {kind} from the list."
_RULINGS = {value for value, _ in RULING_CHOICES}
# The search's ruling filter: any ruling, no ruling, or one ruling.
SEARCH_RULINGS: tuple[tuple[str, str], ...] = (
    ("any", "Any"),
    ("none", "No ruling"),
    (Ruling.ALLOWED.value, "Allowed"),
    (Ruling.ALLOWED_WITH_CONDITIONS.value, "Allowed with conditions"),
    (Ruling.NOT_ALLOWED.value, "Not allowed"),
)
_SEARCH_RULING: dict[str, Ruling | Literal["any"] | None] = {"any": "any", "none": None} | {
    ruling.value: ruling for ruling in Ruling
}


def note_id(request: Request) -> NoteId:
    """The path's `N-n`, or a 404 page before any use case runs."""
    try:
        return NoteId.parse(request.path_params["note"])
    except ValueError:
        raise PageError(404) from None


def _not_found(load: LoadId, note: NoteId | None = None) -> PageError:
    if note is None:
        return PageError(404, f"There's no load {load}.")
    return PageError(404, f"There's no note {note} on load {load}.")


def _back_to_notes(load: LoadId, word: str) -> Response:
    return RedirectResponse(f"/console/loads/{load}?done={word}#notes", status_code=303)


# --- the posted note -------------------------------------------------------------------------


@dataclass(frozen=True)
class _Posted:
    """The note as posted: what to show again, and what to send the use case, or None when
    the page refused it before the use case ran."""

    form: NoteForm
    note: NoteInput | None = field(repr=False)  # holds the text typed by staff: never logged


def _read_note(form: PostedForm) -> _Posted:
    """The note's fields, each checked by its shape; the domain checks the rest. A ruling
    not on the list is refused here, with the text's own refusal beside it; a tag that
    isn't an item's shape is refused as an item the studio doesn't have."""
    text = form.get("text", "")
    glazes = tuple(form.getlist("glaze_types"))
    clays = tuple(form.getlist("clay_bodies"))
    raw_ruling = form.get("ruling", "")
    typed = NoteForm(text=text, glaze_types=glazes, clay_bodies=clays, ruling=raw_ruling)
    if raw_ruling not in _RULINGS:
        errors = {"ruling": PICK_RULING}
        try:
            check_note_text(text)
        except InvalidNote as refused:
            errors = dict(refused.errors) | errors
        return _Posted(NoteForm(text, glazes, clays, raw_ruling, errors, InvalidNote(errors).message), None)
    for tags, which in ((glazes, CatalogList.GLAZE_TYPES), (clays, CatalogList.CLAY_BODIES)):
        if not all(is_item_id(tag) for tag in tags):
            return _Posted(
                NoteForm(text, glazes, clays, raw_ruling, problem=UnknownItem(kind_name(which)).message), None
            )
    ruling = Ruling(raw_ruling) if raw_ruling else None
    note = NoteInput(text, tuple(ItemId(t) for t in glazes), tuple(ItemId(t) for t in clays), ruling)
    return _Posted(typed, note)


def _refused_form(typed: NoteForm, refused: InvalidNote | UnknownItem | ItemRetired) -> NoteForm:
    if isinstance(refused, InvalidNote):
        return NoteForm(
            typed.text, typed.glaze_types, typed.clay_bodies, typed.ruling, refused.errors, refused.message
        )
    return NoteForm(typed.text, typed.glaze_types, typed.clay_bodies, typed.ruling, problem=refused.message)


# --- POST /console/loads/{load}/notes ---------------------------------------------------------


async def write_note(request: Request) -> Response:
    staff, form = await require_staff_post(request, max_fields=NOTE_FORM_FIELDS_MAX)
    id = load_id(request)
    posted = _read_note(form)

    def again(note_form: NoteForm, status: int) -> Response:
        return load_page_for(request, staff, id, note_form=note_form, status=status)

    if posted.note is None:
        return again(posted.form, 422)
    try:
        services(request).write_note(id, posted.note, staff.member)
    except NotFound:  # a deleted load is `NotFound` before the domain's `LoadNotNotable`
        raise _not_found(id) from None
    except (InvalidNote, UnknownItem, ItemRetired) as refused:
        return again(_refused_form(posted.form, refused), 422)
    except Conflict:
        return again(replace(posted.form, problem=LOAD_CHANGED), 409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _back_to_notes(id, "note-added")


# --- GET and POST /console/loads/{load}/notes/{note}/edit -------------------------------------


def _row(request: Request, load: LoadId, note: NoteId) -> NoteRow:
    """The note on its live load, as the load page lists it, or a 404 page."""
    try:
        rows = services(request).load_notes(load)
    except NotFound:
        raise _not_found(load) from None
    for row in rows:
        if row.note.id == note:
            return row
    raise _not_found(load, note)


def _edit_page(
    request: Request,
    staff: Staff,
    row: NoteRow,
    form: NoteForm,
    *,
    status: int = 200,
    changed: bool = False,
    version: int | None = None,
) -> Response:
    """The edit form; `changed` (after a `Conflict`) also shows the note as it is stored
    now. Only the note's row is read: its kiln and firing type names make the title.
    `version` is the one the form sends next: after a refusal, the version the text and
    ruling were typed against (so a change made meanwhile is a `Conflict` on the next
    save, not overwritten); otherwise the note's stored one."""
    studio = services(request).studio()
    context = {
        "tab": "loads",
        "load_id": row.note.load_id,
        "title": f"{row.kiln} · {row.firing_type}",
        "note": card(row),
        "changed": changed,
        "version": row.note.version if version is None else version,
        "fields": form_context(studio, form, row.note),
    }
    return render(request, "console/note_edit.html", context, staff, status=status)


async def edit_page(request: Request) -> Response:
    staff = require_staff(request)
    load, note = load_id(request), note_id(request)
    row = _row(request, load, note)
    return _edit_page(request, staff, row, NoteForm.of(row.note))


async def edit_note(request: Request) -> Response:
    staff, form = await require_staff_post(request, max_fields=NOTE_FORM_FIELDS_MAX)
    load, note = load_id(request), note_id(request)
    version = form_version(form)
    posted = _read_note(form)
    if posted.note is None:
        return _edit_page(request, staff, _row(request, load, note), posted.form, status=422, version=version)
    try:
        services(request).edit_note(load, note, posted.note, version, staff.member)
    except NotFound:
        raise _not_found(load, note) from None
    except (InvalidNote, UnknownItem, ItemRetired) as refused:
        row = _row(request, load, note)
        return _edit_page(
            request, staff, row, _refused_form(posted.form, refused), status=422, version=version
        )
    except Conflict:
        row = _row(request, load, note)  # as it is now, so the version sent next is current
        again = replace(posted.form, problem=NOTE_CHANGED)
        return _edit_page(request, staff, row, again, status=409, changed=True)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _back_to_notes(load, "note-saved")


# --- POST /console/loads/{load}/notes/{note}/remove -------------------------------------------


async def remove_note(request: Request) -> Response:
    """Asks first: without `confirm=1` the load page shows "Remove this note?" at the note
    and changes nothing."""
    staff, form = await require_staff_post(request)
    load, note = load_id(request), note_id(request)
    version = form_version(form)
    if form.get("confirm") != "1":
        _row(request, load, note)
        return load_page_for(request, staff, load, confirm_remove=note)
    try:
        services(request).remove_note(load, note, version, staff.member)
    except NotFound:
        raise _not_found(load, note) from None
    except Conflict:
        return load_page_for(request, staff, load, problem=NOTE_CHANGED_NOT_REMOVED, status=409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _back_to_notes(load, "note-removed")


# --- GET /console/notes -----------------------------------------------------------------------


@dataclass(frozen=True)
class SearchQuery:
    """The query parameters after their checks: what was refused is None (or "any"), with a
    message for each refusal."""

    kiln: ItemId | None
    glaze: ItemId | None
    clay: ItemId | None
    ruling: str  # a key of `_SEARCH_RULING`
    start: date | None
    end: date | None
    problems: tuple[str, ...]


_ITEM_FILTERS = (
    ("kiln", CatalogList.KILNS),
    ("glaze", CatalogList.GLAZE_TYPES),
    ("clay", CatalogList.CLAY_BODIES),
)


def _search_query(params: Mapping[str, str], studio: Studio) -> SearchQuery:
    """Each filter checked by its shape and then against the studio, so a message can name
    the one dropped; nothing typed is ever echoed."""
    problems: list[str] = []
    items: dict[str, ItemId | None] = {}
    for name, which in _ITEM_FILTERS:
        raw = params.get(name, "")
        items[name] = None
        if not raw:
            continue
        if is_item_id(raw):
            try:
                studio.item(which, ItemId(raw))
                items[name] = ItemId(raw)
                continue
            except UnknownItem:
                pass
        problems.append(PICK.format(kind=kind_name(which)))
    raw_ruling = params.get("ruling", "any") or "any"
    ruling = raw_ruling if raw_ruling in _SEARCH_RULING else "any"
    if ruling != raw_ruling:
        problems.append(PICK_RULING)
    raw_from, raw_to = params.get("from", ""), params.get("to", "")
    start, end = parse_date(raw_from or None), parse_date(raw_to or None)
    if (raw_from and start is None) or (raw_to and end is None):
        problems.append(BAD_DATES)
        start = end = None
    return SearchQuery(items["kiln"], items["glaze"], items["clay"], ruling, start, end, tuple(problems))


def _without_gone_items(query: SearchQuery, studio: Studio) -> SearchQuery:
    """`query` without the kiln, glaze type or clay body `studio` no longer has, each with
    its message; with none gone, without all three (the search can't fail on them again)."""
    items = {"kiln": query.kiln, "glaze": query.glaze, "clay": query.clay}
    problems = list(query.problems)
    for name, which in _ITEM_FILTERS:
        id = items[name]
        if id is None:
            continue
        try:
            studio.item(which, id)
        except UnknownItem:
            items[name] = None
            problems.append(PICK.format(kind=kind_name(which)))
    if items == {"kiln": query.kiln, "glaze": query.glaze, "clay": query.clay}:
        items = {"kiln": None, "glaze": None, "clay": None}
    return replace(
        query, kiln=items["kiln"], glaze=items["glaze"], clay=items["clay"], problems=tuple(problems)
    )


def _search(request: Request, query: SearchQuery) -> tuple[SearchQuery, NoteSearchView]:
    """The notes for `query`. An item deleted since the page checked it falls back to the
    search without it, and a refused range to the default one, each with its message;
    each can happen once (the default range is never refused, and a search with no item
    filters never raises `UnknownItem`), so this reads at most three times."""
    console = services(request)
    f = NoteFilter(
        kiln=query.kiln, glaze_type=query.glaze, clay_body=query.clay, ruling=_SEARCH_RULING[query.ruling]
    )
    try:
        return query, console.search_notes(f, query.start, query.end)
    except UnknownItem:
        return _search(request, _without_gone_items(query, console.studio()))
    except InvalidLogRange as refused:
        return _search(
            request, replace(query, start=None, end=None, problems=(*query.problems, refused.message))
        )


async def search_page(request: Request) -> Response:
    staff = require_staff(request)
    studio = services(request).studio()
    query, view = _search(request, _search_query(request.query_params, studio))
    context = {
        "tab": "firing-log",
        "log_view": "notes",
        "query": query,
        "problems": query.problems,
        "kilns": studio.kilns,
        "glaze_types": studio.items(CatalogList.GLAZE_TYPES),
        "clay_bodies": studio.items(CatalogList.CLAY_BODIES),
        "rulings": SEARCH_RULINGS,
        "cards": [card(row, year=True) for row in view.rows],
        "from_value": "" if query.start is None else query.start.isoformat(),
        "to_value": "" if query.end is None else query.end.isoformat(),
        "range": f"Written {austin_date(view.start)} to {austin_date(view.end)}",
    }
    return render(request, "console/notes.html", context, staff)
