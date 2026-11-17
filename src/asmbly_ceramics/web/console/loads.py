"""Kiln loads (#4): the list and "Start a load", one load's page, adding (by ID, by name,
from the waiting list), removing, changing, firing, retrying a ready email, and deleting
a load started by mistake. The load page also shows the load's notes (#17), whose
handlers are in `notes.py`.

The use cases decide every rule and log every change; a page turns their result or
refusal into a response, and after a change answers 303 to the load (Post/Redirect/Get)
with a fixed word in the address, never anything typed. The add field's text is often
part of a person's name: it travels only in a POST body and is never logged or put in a
URL.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import EmailKind
from asmbly_ceramics.domain.errors import (
    AlreadyFired,
    AlreadyInLoad,
    EmailNotRetryable,
    EmptyLoad,
    FiredLoadNotDeletable,
    FiringTypeLocked,
    FiringTypeMismatch,
    InvalidRecord,
    ItemRetired,
    LoadFull,
    LoadNotLoading,
    NotFound,
    NotInLoad,
    NotWaiting,
    StepNotReached,
    StepTimeInFuture,
    StepTimeOutOfOrder,
    StepTimeTooEarly,
    TooManyNotesToMove,
    UnknownItem,
    WrongLoadStatus,
)
from asmbly_ceramics.domain.firing import (
    CONE_READING_TEXT_MAX,
    COST_TEXT_MAX,
    EMPTY_RECORD,
    FIRING_TIME_TEXT_MAX,
    NO_CONE,
    RECORD_FIELDS,
    RECORD_LABELS,
    WHOLE_RANGES,
    WITNESS_CONES,
    Speed,
    cone_bends,
    is_no_cone,
    record_shown,
    record_summary,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId, NoteId, is_item_id
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.load import (
    Load,
    LoadStatus,
    Step,
    accepts_drop_offs,
    require_correctable,
    require_deletable,
    require_firing,
    require_loading,
    step_time,
)
from asmbly_ceramics.domain.search import QUERY_MAX, parse_query
from asmbly_ceramics.domain.studio import CatalogItem, CatalogList, Studio
from asmbly_ceramics.mail.compose import austin_day, austin_time
from asmbly_ceramics.ports.records import CommitOutcomeUnknown, Conflict
from asmbly_ceramics.use_cases.loads import RECENT_LOADS, LoadView
from asmbly_ceramics.use_cases.studio import active_items, item_name
from asmbly_ceramics.use_cases.waiting import Found
from asmbly_ceramics.web.console.auth import require_staff, require_staff_post
from asmbly_ceramics.web.console.common import Staff, form_version, parse_date, render, services
from asmbly_ceramics.web.console.dropoffs import email_status
from asmbly_ceramics.web.console.note_views import NoteForm, section_context
from asmbly_ceramics.web.errors import PageError

PICK_KILN = "Pick a kiln from the list."
PICK_FIRING_TYPE = "Pick a firing type from the list."
BAD_DATE = "Enter a date like 2026-11-13."
NO_MATCH = "No waiting drop-off matches that. Check the ID, or try part of the name."
TYPE_SOMETHING = "Scan a slip, or type an ID or name."
MAYBE_SAVED = "That may or may not have been saved. Reload the load to check before trying again."
START_CLASHED = "Another load was started at the same moment, and this one wasn't saved. Try again."
TYPE_THE_ID = "Type {id} exactly to delete this load."
DELETED = "Load {id} deleted. Its drop-offs are back in the waiting list."
BAD_TIME = "Enter a date and time."
SKIPPED_TIME = "The clocks went forward an hour then, so that time didn't happen. Enter another."
CHANGED_ELSEWHERE = "Someone else changed this load. Check it and save again."
NO_CONE_SUFFIX = "_none"  # "<witness cone>_none=1": the "No cone" box, sent as `none`
_LOCAL_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}", flags=re.ASCII)
_STEP_PROMPTS = {
    Step.STARTED: "When it was started",
    Step.FIRING: "When it started firing",
    Step.FIRED: "When it was fired",
}
_CURRENT_STEP = {
    LoadStatus.LOADING: Step.STARTED,
    LoadStatus.FIRING: Step.FIRING,
    LoadStatus.FIRED: Step.FIRED,
}
# After a change the page says what happened from a fixed word in its address, and the
# drop-off's ID when there is one (parsed again, so nothing else is ever echoed).
DONE = {
    "started": "Load started. Add drop-offs below.",
    "added": "{id} added.",
    "removed": "{id} is back in the waiting list.",
    "changed": "Load changed.",
    "firing": "Firing started. Nothing can be added or removed now.",
    "fired": "Marked fired. The “Ready for pickup” emails are on their way.",
    "retried": "The email to {id} will be sent again.",
    "record": "Firing record saved.",
    "time": "Time corrected.",
}
# After a note's change the page opens at its notes (`#notes`): the notice shows there.
NOTE_DONE = {
    "note-added": "Note added.",
    "note-saved": "Note saved.",
    "note-removed": "Note removed.",
}


def load_id(request: Request) -> LoadId:
    """The path's `L-n`, or a 404 page before any use case runs."""
    try:
        return LoadId.parse(request.path_params["load"])
    except ValueError:
        raise PageError(404) from None


def _load_not_found(id: LoadId) -> PageError:
    return PageError(404, f"There's no load {id}.")


def load_title(studio: Studio, load: Load) -> str:
    """`Athena · Glaze · Fri Nov 13`; a deleted item shows as `DELETED_ITEM`."""
    return " · ".join(
        (
            item_name(studio, CatalogList.KILNS, load.kiln),
            item_name(studio, CatalogList.FIRING_TYPES, load.firing_type),
            austin_day(load.date),
        )
    )


def _choices(studio: Studio, which: CatalogList, current: ItemId | None) -> list[CatalogItem]:
    """The active items, and the current one if it is retired, so a form that keeps it
    doesn't silently submit another."""
    items = list(active_items(studio.items(which)))
    if current is not None and all(item.id != current for item in items):
        items.extend(item for item in studio.items(which) if item.id == current)
    return items


def _test(form: Mapping[str, str]) -> bool:
    """ "This is a test firing" ticked: `test=1` exactly; anything else is not a test."""
    return form.get("test") == "1"


def _item(raw: str) -> ItemId | None:
    return ItemId(raw) if is_item_id(raw) else None


def _drop_off_param(raw: str | None) -> DropOffId | None:
    try:
        return DropOffId.parse(raw or "")
    except ValueError:
        return None


def _item_problem(studio: Studio, kiln: ItemId | None, keep_kiln: ItemId | None = None) -> str:
    """Which select was refused: the kiln when it is neither active nor the one kept."""
    if kiln is None:
        return PICK_KILN
    if kiln != keep_kiln:
        try:
            studio.active_item(CatalogList.KILNS, kiln)
        except UnknownItem, ItemRetired:
            return PICK_KILN
    return PICK_FIRING_TYPE


def _conflict_text(conflict: Conflict, id: LoadId) -> str:
    names = ", ".join(conflict.ids) if conflict.ids else str(id)
    return f"{names} changed while you were working. Here it is now; try again."


# --- GET and POST /console/loads ---------------------------------------------------------


@dataclass(frozen=True)
class StartForm:
    kiln: str = ""
    firing_type: str = ""
    date: str = ""
    test: bool = False
    error: str | None = None


def _loads_page(
    request: Request, staff: Staff, *, add: DropOffId | None, form: StartForm | None, status: int = 200
) -> Response:
    console = services(request)
    studio = console.studio()
    open_loads, fired = console.list_loads()
    today = console.clock.now().astimezone(STUDIO_TZ).date()

    def row(load: Load) -> dict[str, Any]:
        return {
            "load": load,
            "title": load_title(studio, load),
            "count": len(load.members),
            "accepts_drop_offs": accepts_drop_offs(load),
        }

    context = {
        "tab": "loads",
        "open_loads": [row(load) for load in open_loads],
        "fired_loads": [row(load) for load in fired],
        "kilns": active_items(studio.kilns),
        "firing_types": active_items(studio.firing_types),
        "form": form or StartForm(date=today.isoformat()),
        "add": add,
        "recent_weeks": RECENT_LOADS.days // 7,
        "notice": _deleted_notice(request),
    }
    return render(request, "console/loads.html", context, staff, status=status)


def _deleted_notice(request: Request) -> str | None:
    """After a delete, "Load L-4 deleted.", from the ID parsed again, never echoed."""
    if request.query_params.get("done") != "deleted":
        return None
    try:
        return DELETED.format(id=LoadId.parse(request.query_params.get("load", "")))
    except ValueError:
        return None


async def loads_page(request: Request) -> Response:
    staff = require_staff(request)
    return _loads_page(request, staff, add=_drop_off_param(request.query_params.get("add")), form=None)


async def start_load(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    console = services(request)
    add = _drop_off_param(form.get("add"))
    typed = StartForm(
        form.get("kiln", ""), form.get("firing_type", ""), form.get("date", ""), test=_test(form)
    )
    kiln, firing_type, day = _item(typed.kiln), _item(typed.firing_type), parse_date(typed.date)

    def refused(error: str, status: int = 400) -> Response:
        typed_with_error = replace(typed, error=error)
        return _loads_page(request, staff, add=add, form=typed_with_error, status=status)

    if day is None:
        return refused(BAD_DATE)
    if kiln is None:
        return refused(PICK_KILN)
    if firing_type is None:
        return refused(PICK_FIRING_TYPE)
    try:
        load = console.start_load(kiln, firing_type, day, staff.member, test=typed.test)
    except UnknownItem, ItemRetired:
        return refused(_item_problem(console.studio(), kiln))
    except Conflict:  # the load's new number was taken first: nothing was saved
        return refused(START_CLASHED, status=409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    target = f"/console/loads/{load.id}?done=started"
    if add is not None:
        target += f"&add={add}"
    return RedirectResponse(target, status_code=303)


# --- the steps and the firing record, as the load page shows them (#42) --------------------


@dataclass(frozen=True)
class StepForm:
    """A refused "Correct time": which step, the text typed (kept), and why."""

    step: Step
    typed: str
    error: str


@dataclass(frozen=True)
class RecordForm:
    """A refused "Save firing record": what was typed (kept), each field's message, and the
    message above the form."""

    values: Mapping[str, str]
    errors: Mapping[str, str] = field(default_factory=dict)
    problem: str | None = None
    changed: bool = False  # refused by a `Conflict`: the page also shows the record as stored now


def _local_input(at: datetime) -> str:
    """`at` as a `datetime-local` field's value, in Austin time: `2026-11-13T12:30`."""
    return at.astimezone(STUDIO_TZ).strftime("%Y-%m-%dT%H:%M")


def parse_local_time(raw: str) -> datetime | None:
    """A `datetime-local` field's `YYYY-MM-DDTHH:MM` as a naive Austin wall time, or None
    for anything malformed or that has no instant (the page says "Enter a date and time.").
    The domain refuses a year that is a typo (`StepTimeTooEarly`)."""
    if not _LOCAL_TIME.fullmatch(raw):
        return None
    try:
        local = datetime.fromisoformat(raw)
        local.replace(tzinfo=STUDIO_TZ).astimezone(UTC)  # 9999-12-31T23:59 has no UTC instant
    except ValueError, OverflowError:
        return None
    return local


def austin_instant(local: datetime) -> datetime | None:
    """A naive Austin wall time as a UTC instant, or None for one the clocks skip (2:30 am
    on a spring-forward day). In the repeated hour of a fall-back day it is the first."""
    at = local.replace(tzinfo=STUDIO_TZ, fold=0).astimezone(UTC)
    if at.astimezone(STUDIO_TZ).replace(tzinfo=None) != local:
        return None
    return at


def _step_rows(view: LoadView, refused: StepForm | None) -> list[dict[str, Any]]:
    current = _CURRENT_STEP.get(view.load.status)
    rows = []
    for step in view.steps:
        mine = refused if refused is not None and refused.step is step.step else None
        rows.append(
            {
                "view": step,
                "current": step.step is current,
                "prompt": _STEP_PROMPTS[step.step],
                "when": austin_time(step.at) if step.at else "",
                "value": mine.typed if mine else (_local_input(step.at) if step.at else ""),
                "error": mine.error if mine else None,
            }
        )
    return rows


def _record_context(view: LoadView, refused: RecordForm | None, studio: Studio) -> dict[str, Any]:
    """The readout of the saved record (its values as shown and its cones' bends) and the
    record form: the values typed (after a refusal) or stored, the numbers
    suggested while the record has none, and every bound from `domain.limits`. After a
    `Conflict`, also the record as it is stored now (`stored`), so the next save, sent
    with the load's new version, replaces it only once staff have seen it."""
    values = dict(refused.values if refused else view.record_fields)

    def cone_name(id: ItemId) -> str:
        return item_name(studio, CatalogList.CONES, id)

    stored: tuple[tuple[str, str], ...] | None = None
    if refused is not None and refused.changed:
        stored = record_summary(view.load.record, cone_name)
    saved = view.load.record != EMPTY_RECORD
    suggested: set[str] = set()
    if refused is None:
        for name, number in zip(("firing_number", "all_time_number"), view.suggested, strict=True):
            if number is not None and not values.get(name):
                values[name] = str(number)
                suggested.add(name)
    return {
        "fields": values,
        "no_cone": {name for name in WITNESS_CONES if is_no_cone(values.get(name, ""))},
        "errors": refused.errors if refused else {},
        "problem": refused.problem if refused else None,
        "stored": stored,
        "saved": saved,  # the readout shows, with the form behind "Edit firing record"
        "open": refused is not None or not saved,  # the form shows without a tap
        "shown": record_shown(view.load.record, cone_name),
        "bends": cone_bends(view.load.record),
        "labels": RECORD_LABELS,
        "suggested": suggested,
        "whole": WHOLE_RANGES,
        "cone_reading_max": CONE_READING_TEXT_MAX,
        "firing_time_max": FIRING_TIME_TEXT_MAX,
        "cost_max": COST_TEXT_MAX,
        "cone_options": [
            (cone.id, f"{cone.name} (retired)" if cone.retired else cone.name) for cone in view.cones
        ],
        "speed_options": [(speed.value, speed.value.capitalize()) for speed in Speed],
        "witness": WITNESS_CONES,
        "no_cone_suffix": NO_CONE_SUFFIX,
    }


def posted_record(form: Mapping[str, str]) -> dict[str, str]:
    """The record's fields from the posted form; a ticked "No cone" box sends `none` for its
    witness cone, whatever the number field holds."""
    values = {name: form.get(name, "") for name in RECORD_FIELDS}
    for name in WITNESS_CONES:
        if form.get(name + NO_CONE_SUFFIX) == "1":
            values[name] = NO_CONE.value
    return values


# --- GET /console/loads/{load} -------------------------------------------------------------


@dataclass(frozen=True)
class AddState:
    """The add field as the page shows it: the typed text, what a name search found, and a
    firing-type mismatch waiting for "Add anyway"."""

    text: str = field(default="", repr=False)  # often part of a name: never logged
    found: Found | None = None
    mismatch: FiringTypeMismatch | None = None
    mismatch_id: DropOffId | None = None
    error: str | None = None
    detail: str | None = None


def _member_row(drop_off: DropOff) -> dict[str, Any]:
    return {
        "drop_off": drop_off,
        "name": drop_off.contact.name if drop_off.contact else "Closed",
        "thumb": f"/console/drop-offs/{drop_off.id}/photos/1/thumb"
        if drop_off.contact and drop_off.photos
        else None,
    }


def _load_page(
    request: Request,
    staff: Staff,
    view: LoadView,
    *,
    all_types: bool = False,
    notice: str | None = None,
    problem: str | None = None,
    add: AddState | None = None,
    prefill: str = "",
    confirm_fire: bool = False,
    confirm_delete: bool = False,
    delete_error: str | None = None,
    record: RecordForm | None = None,
    step_form: StepForm | None = None,
    note_form: NoteForm | None = None,
    confirm_remove: NoteId | None = None,
    note_notice: str | None = None,
    status: int = 200,
) -> Response:
    console = services(request)
    studio = console.studio()
    load = view.load
    try:
        note_rows = console.load_notes(load.id)
    except NotFound:
        raise _load_not_found(load.id) from None
    emails = []
    attention = {email.drop_off_id for email in view.needing_attention}
    for drop_off in view.members:
        email = view.emails.get(drop_off.id)
        emails.append(
            {
                "id": drop_off.id,
                "state": email_status(email) if email is not None else "No email",
                "retry": drop_off.id in attention,
            }
        )
    mismatch = add.mismatch if add else None
    context: dict[str, Any] = {
        "tab": "loads",
        "view": view,
        "load": load,
        "title": load_title(studio, load),
        "firing_name": item_name(studio, CatalogList.FIRING_TYPES, load.firing_type),
        "started": austin_time(load.started_at),
        "fired_on": austin_time(load.fired_at) if load.fired_at else "",
        "loading": load.status is LoadStatus.LOADING,
        "firing": load.status is LoadStatus.FIRING,
        "fired": load.status is LoadStatus.FIRED,
        "steps": _step_rows(view, step_form),
        "record": _record_context(view, record, studio),
        "history": [(austin_time(e.at), e.by, e.what) for e in view.history],
        "members": [_member_row(d) for d in view.members],
        "kilns": _choices(studio, CatalogList.KILNS, load.kiln),
        "firing_types": _choices(studio, CatalogList.FIRING_TYPES, load.firing_type),
        "waiting": view.waiting,
        "all_types": all_types,
        "emails": emails,
        "notice": notice,
        "problem": problem,
        "add": add or AddState(text=prefill),
        "mismatch_names": (
            item_name(studio, CatalogList.FIRING_TYPES, mismatch.drop_off_firing_type),
            item_name(studio, CatalogList.FIRING_TYPES, mismatch.load_firing_type),
        )
        if mismatch
        else None,
        "confirm_fire": confirm_fire and load.status is LoadStatus.FIRING,
        "confirm_delete": confirm_delete and view.can_delete,
        "delete_error": delete_error,
        "query_max": QUERY_MAX,
        "notes": section_context(studio, note_rows, note_form, confirm_remove, note_notice),
    }
    return render(request, "console/load.html", context, staff, status=status)


def load_page_for(
    request: Request,
    staff: Staff,
    id: LoadId,
    *,
    problem: str | None = None,
    note_form: NoteForm | None = None,
    confirm_remove: NoteId | None = None,
    status: int = 200,
) -> Response:
    """The load as it is now, for the note pages: with the note form as typed, a remove
    waiting for "Yes", or a refusal above."""
    view = _view(request, id)
    return _load_page(
        request,
        staff,
        view,
        problem=problem,
        note_form=note_form,
        confirm_remove=confirm_remove,
        status=status,
    )


def _view(request: Request, id: LoadId, *, all_types: bool = False) -> LoadView:
    try:
        return services(request).view_load(id, all_firing_types=all_types)
    except NotFound:
        raise _load_not_found(id) from None


async def load_page(request: Request) -> Response:
    staff = require_staff(request)
    id = load_id(request)
    all_types = request.query_params.get("all") == "1"
    view = _view(request, id, all_types=all_types)
    done = request.query_params.get("done", "")
    notice = None
    if done in DONE:
        about = _drop_off_param(request.query_params.get("id"))
        if "{id}" not in DONE[done]:
            notice = DONE[done]
        elif about is not None:
            notice = DONE[done].format(id=about)
    prefill = ""
    add = _drop_off_param(request.query_params.get("add"))
    if add is not None and view.load.status is LoadStatus.LOADING:
        prefill = str(add)
    return _load_page(
        request,
        staff,
        view,
        all_types=all_types,
        notice=notice,
        prefill=prefill,
        note_notice=NOTE_DONE.get(done),
    )


def _done(id: LoadId, word: str, drop_off: DropOffId | None = None, *, all_types: bool = False) -> Response:
    target = f"/console/loads/{id}?done={word}"
    if drop_off is not None:
        target += f"&id={drop_off}"
    if all_types:
        target += "&all=1"  # no fragment: the add field keeps its focus and the notice shows
    return RedirectResponse(target, status_code=303)


def _refused(
    request: Request,
    staff: Staff,
    id: LoadId,
    *,
    problem: str | None = None,
    add: AddState | None = None,
    status: int = 400,
    all_types: bool = False,
) -> Response:
    """The load as it is now, with the refusal; nothing was stored."""
    view = _view(request, id, all_types=all_types)
    return _load_page(request, staff, view, all_types=all_types, problem=problem, add=add, status=status)


def _conflicted(request: Request, staff: Staff, id: LoadId, conflict: Conflict) -> Response:
    return _refused(request, staff, id, problem=_conflict_text(conflict, id), status=409)


# --- POST .../add and .../remove -----------------------------------------------------------


def _not_waiting_detail(request: Request, drop_off_id: DropOffId) -> str | None:
    """For a fired drop-off, "Fired in Vulcan on Nov 9.", from the records, never from the
    error's message."""
    console = services(request)
    try:
        view = console.view_drop_off(drop_off_id)
    except NotFound:
        return None
    drop_off, load = view.drop_off, view.load
    if drop_off.state is not DropOffState.FIRED or load is None or drop_off.fired_at is None:
        return None
    kiln = item_name(console.studio(), CatalogList.KILNS, load.kiln)
    day = drop_off.fired_at.astimezone(STUDIO_TZ).date()
    return f"Fired in {kiln} on {austin_day(day).split(' ', 1)[1]}."


async def add_to_load(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    id = load_id(request)
    console = services(request)
    text = form.get("drop_off", "")[:QUERY_MAX]
    confirmed = form.get("confirm") == "1"
    all_types = form.get("all") == "1"  # the waiting list stays as it was shown
    query = parse_query(text)
    if query.id is None:
        current = _view(request, id, all_types=all_types)
        try:
            require_loading(current.load)  # a stale page: the add field is gone
        except LoadNotLoading as refused:
            return _load_page(
                request, staff, current, all_types=all_types, problem=refused.message, status=400
            )
        if not text.strip():
            state = AddState(error=TYPE_SOMETHING)
            return _load_page(request, staff, current, all_types=all_types, add=state, status=400)
        found = console.find_drop_offs(text, waiting_only=True)
        if not found.rows:
            state = AddState(text=text, error=NO_MATCH)
            return _load_page(request, staff, current, all_types=all_types, add=state, status=400)
        return _load_page(request, staff, current, all_types=all_types, add=AddState(text=text, found=found))
    drop_off_id = query.id
    try:
        console.add_to_load(id, drop_off_id, confirmed=confirmed, staff=staff.member)
    except NotFound as missing:
        if isinstance(missing.id, LoadId):
            raise _load_not_found(id) from None
        return _refused(request, staff, id, add=AddState(text=text, error=NO_MATCH), all_types=all_types)
    except FiringTypeMismatch as mismatch:
        state = AddState(text=text, mismatch=mismatch, mismatch_id=drop_off_id)
        view = _view(request, id, all_types=all_types)
        return _load_page(request, staff, view, all_types=all_types, add=state, status=409)
    except NotWaiting as refused:
        detail = _not_waiting_detail(request, drop_off_id)
        state = AddState(text=text, error=refused.message, detail=detail)
        return _refused(request, staff, id, add=state, all_types=all_types)
    except (AlreadyInLoad, LoadFull) as refused:
        return _refused(
            request, staff, id, add=AddState(text=text, error=refused.message), all_types=all_types
        )
    except LoadNotLoading as refused:  # the add field is gone once firing: say it above
        return _refused(request, staff, id, problem=refused.message, all_types=all_types)
    except Conflict as conflict:
        return _conflicted(request, staff, id, conflict)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _done(id, "added", drop_off_id, all_types=all_types)


async def remove_from_load(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    id = load_id(request)
    drop_off_id = _drop_off_param(form.get("drop_off"))
    if drop_off_id is None:
        raise PageError(400)
    try:
        services(request).remove_from_load(id, drop_off_id, staff.member)
    except NotFound as missing:
        if isinstance(missing.id, LoadId):
            raise _load_not_found(id) from None
        return _refused(request, staff, id, problem=missing.message)
    except (LoadNotLoading, NotInLoad) as refused:
        return _refused(request, staff, id, problem=refused.message)
    except Conflict as conflict:
        return _conflicted(request, staff, id, conflict)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _done(id, "removed", drop_off_id)


# --- POST .../edit -------------------------------------------------------------------------


async def change_load(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    id = load_id(request)
    console = services(request)
    kiln, firing_type, day = (
        _item(form.get("kiln", "")),
        _item(form.get("firing_type", "")),
        parse_date(form.get("date", "")),
    )
    version = form_version(form)
    if day is None:
        return _refused(request, staff, id, problem=BAD_DATE)
    if kiln is None:
        return _refused(request, staff, id, problem=PICK_KILN)
    if firing_type is None:
        return _refused(request, staff, id, problem=PICK_FIRING_TYPE)
    try:
        console.change_load(id, kiln, firing_type, day, version, staff.member, test=_test(form))
    except NotFound:
        raise _load_not_found(id) from None
    except UnknownItem, ItemRetired:
        current = _view(request, id).load
        return _refused(request, staff, id, problem=_item_problem(console.studio(), kiln, current.kiln))
    except (FiringTypeLocked, LoadNotLoading, TooManyNotesToMove) as refused:
        return _refused(request, staff, id, problem=refused.message)
    except Conflict as conflict:
        return _conflicted(request, staff, id, conflict)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _done(id, "changed")


# --- POST .../start-firing and .../fire ----------------------------------------------------


async def start_firing(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    id = load_id(request)
    try:
        services(request).start_firing(id, form_version(form), staff.member)
    except NotFound:
        raise _load_not_found(id) from None
    except (EmptyLoad, WrongLoadStatus) as refused:
        return _refused(request, staff, id, problem=refused.message)
    except Conflict as conflict:
        return _conflicted(request, staff, id, conflict)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _done(id, "firing")


async def mark_fired(request: Request) -> Response:
    """Asks first: without `confirm=1` the page shows "Mark L-4 fired?" and changes
    nothing, so a double tap on "Start firing" can't email everyone."""
    staff, form = await require_staff_post(request)
    id = load_id(request)
    version = form_version(form)
    if form.get("confirm") != "1":
        view = _view(request, id)
        try:
            require_firing(view.load)
        except (AlreadyFired, WrongLoadStatus) as refused:
            return _load_page(request, staff, view, problem=refused.message, status=400)
        return _load_page(request, staff, view, confirm_fire=True)
    try:
        services(request).mark_fired(id, version, staff.member)
    except NotFound:
        raise _load_not_found(id) from None
    except (AlreadyFired, WrongLoadStatus) as refused:
        return _refused(request, staff, id, problem=refused.message)
    except Conflict as conflict:
        return _conflicted(request, staff, id, conflict)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _done(id, "fired")


# --- POST .../emails/{drop_off}/retry ------------------------------------------------------


async def retry_email(request: Request) -> Response:
    staff, _ = await require_staff_post(request)
    id = load_id(request)
    drop_off_id = _drop_off_param(request.path_params["drop_off"])
    if drop_off_id is None:
        raise PageError(404)
    view = _view(request, id)
    if drop_off_id not in view.load.members:
        raise PageError(404, f"{drop_off_id} isn't in load {id}.")
    try:
        services(request).retry_email(drop_off_id, EmailKind.READY, "", staff.member)
    except NotFound:
        raise PageError(404) from None
    except EmailNotRetryable as refused:
        return _refused(request, staff, id, problem=refused.message)
    except Conflict as conflict:
        return _conflicted(request, staff, id, conflict)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _done(id, "retried", drop_off_id)


# --- POST .../delete -----------------------------------------------------------------------


async def delete_load(request: Request) -> Response:
    """Asks first and asks hard: without `confirm=1` the page shows "Delete L-4?" and
    changes nothing, and the delete runs only when the load's ID is typed into that
    question exactly, so neither a stray tap nor a reflexive "Yes" deletes a load."""
    staff, form = await require_staff_post(request)
    id = load_id(request)
    version = form_version(form)
    view = _view(request, id)
    try:
        require_deletable(view.load)
    except FiredLoadNotDeletable as refused:
        return _load_page(request, staff, view, problem=refused.message, status=400)
    if form.get("confirm") != "1":
        return _load_page(request, staff, view, confirm_delete=True)
    if form.get("typed_id", "").strip().upper() != str(id):
        error = TYPE_THE_ID.format(id=id)
        return _load_page(request, staff, view, confirm_delete=True, delete_error=error, status=400)
    try:
        services(request).delete_load(id, version, staff.member)
    except NotFound:
        raise _load_not_found(id) from None
    except (FiredLoadNotDeletable, TooManyNotesToMove) as refused:
        return _refused(request, staff, id, problem=refused.message)
    except Conflict as conflict:
        return _conflicted(request, staff, id, conflict)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return RedirectResponse(f"/console/loads?done=deleted&load={id}", status_code=303)


# --- POST .../record and .../steps/{step}/time (#42) ------------------------------------------


async def save_record(request: Request) -> Response:
    """The firing record, on a loading, firing or fired load: it changes nothing else."""
    staff, form = await require_staff_post(request)
    id = load_id(request)
    version = form_version(form)
    values = posted_record(form)
    try:
        services(request).save_firing_record(id, values, version, staff.member)
    except NotFound:
        raise _load_not_found(id) from None
    except InvalidRecord as refused:
        typed = RecordForm(values, refused.errors, refused.message)
        return _load_page(request, staff, _view(request, id), record=typed, status=422)
    except Conflict:
        typed = RecordForm(values, problem=CHANGED_ELSEWHERE, changed=True)
        return _load_page(request, staff, _view(request, id), record=typed, status=409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _done(id, "record")


def _stored_step_time(request: Request, id: LoadId, step: Step) -> datetime | None:
    """The step's stored time, to tell a "Save time" with the text unchanged from a change:
    in the repeated hour of a fall-back day the text alone can't say which hour it was."""
    return step_time(_view(request, id).load, step)


def _step(request: Request) -> Step:
    try:
        return Step(request.path_params["step"])
    except ValueError:
        raise PageError(404) from None


async def correct_step_time(request: Request) -> Response:
    """A reached step's time, typed as Austin time; who reached it never changes."""
    staff, form = await require_staff_post(request)
    id = load_id(request)
    step = _step(request)
    version = form_version(form)
    typed = form.get("at", "")[:32]

    def refused(error: str, status: int) -> Response:
        view = _view(request, id)
        try:
            require_correctable(view.load, step)
        except StepNotReached as wrong:  # a stale page or a crafted post: no field to show it by
            return _load_page(request, staff, view, problem=wrong.message, status=status)
        return _load_page(request, staff, view, step_form=StepForm(step, typed, error), status=status)

    local = parse_local_time(typed)
    if local is None:
        return refused(BAD_TIME, 422)
    stored = _stored_step_time(request, id, step)
    if stored is not None and _local_input(stored) == typed:
        at: datetime | None = stored  # unchanged at the minute: the stored instant, not a guess
    else:
        at = austin_instant(local)
    if at is None:
        return refused(SKIPPED_TIME, 422)
    try:
        services(request).correct_step_time(id, step, at, version, staff.member)
    except NotFound:
        raise _load_not_found(id) from None
    except StepNotReached as wrong:  # a stale page: the step has no "Correct time" to show it by
        return _load_page(request, staff, _view(request, id), problem=wrong.message, status=422)
    except (StepTimeInFuture, StepTimeTooEarly, StepTimeOutOfOrder) as wrong:
        return refused(wrong.message, 422)
    except Conflict:
        return refused(CHANGED_ELSEWHERE, 409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return _done(id, "time")
