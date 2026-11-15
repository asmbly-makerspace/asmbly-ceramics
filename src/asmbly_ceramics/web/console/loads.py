"""Kiln loads (#4): the list and "Start a load", one load's page, adding (by ID, by name,
from the waiting list), removing, changing, firing, retrying a ready email, and deleting
a load started by mistake.

The use cases decide every rule and log every change; a page turns their result or
refusal into a response, and after a change answers 303 to the load (Post/Redirect/Get)
with a fixed word in the address, never anything typed. The add field's text is often
part of a person's name: it travels only in a POST body and is never logged or put in a
URL.
"""

from dataclasses import dataclass, field
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
    ItemRetired,
    LoadFull,
    LoadNotLoading,
    NotFound,
    NotInLoad,
    NotWaiting,
    UnknownItem,
    WrongLoadStatus,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId, is_item_id
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.load import (
    Load,
    LoadStatus,
    accepts_drop_offs,
    require_deletable,
    require_firing,
    require_loading,
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
STEPS = (("Loading", LoadStatus.LOADING), ("Firing", LoadStatus.FIRING), ("Fired", LoadStatus.FIRED))
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
    typed = StartForm(form.get("kiln", ""), form.get("firing_type", ""), form.get("date", ""))
    kiln, firing_type, day = _item(typed.kiln), _item(typed.firing_type), parse_date(typed.date)

    def refused(error: str, status: int = 400) -> Response:
        typed_with_error = StartForm(typed.kiln, typed.firing_type, typed.date, error)
        return _loads_page(request, staff, add=add, form=typed_with_error, status=status)

    if day is None:
        return refused(BAD_DATE)
    if kiln is None:
        return refused(PICK_KILN)
    if firing_type is None:
        return refused(PICK_FIRING_TYPE)
    try:
        load = console.start_load(kiln, firing_type, day, staff.member)
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
    status: int = 200,
) -> Response:
    studio = services(request).studio()
    load = view.load
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
        "steps": STEPS,
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
    }
    return render(request, "console/load.html", context, staff, status=status)


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
    return _load_page(request, staff, view, all_types=all_types, notice=notice, prefill=prefill)


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
        console.change_load(id, kiln, firing_type, day, version, staff.member)
    except NotFound:
        raise _load_not_found(id) from None
    except UnknownItem, ItemRetired:
        current = _view(request, id).load
        return _refused(request, staff, id, problem=_item_problem(console.studio(), kiln, current.kiln))
    except (FiringTypeLocked, LoadNotLoading) as refused:
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
    except FiredLoadNotDeletable as refused:
        return _refused(request, staff, id, problem=refused.message)
    except Conflict as conflict:
        return _conflicted(request, staff, id, conflict)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return RedirectResponse(f"/console/loads?done=deleted&load={id}", status_code=303)
