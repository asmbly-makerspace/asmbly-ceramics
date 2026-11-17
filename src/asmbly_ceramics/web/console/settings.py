"""The studio's settings (#6): the emails card (the sending address, the test email, the
pickup window and hours), the studio's lists, each firing type's default program and each
kiln's firing counts and new elements (#42), and the change history.

The domain decides every rule (an address only at asmbly.org, the window's range, unique
names, retire before delete, a used item kept) and the use cases log every change by
username and item ID. A page never logs the address or the hours text, and puts no typed
value in a URL.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from asmbly_ceramics.domain.errors import (
    DuplicateItem,
    InvalidRecord,
    InvalidSetting,
    ItemInUse,
    NoStaffEmail,
    SendingAddressOutsideAsmbly,
    TestEmailFailed,
    UnknownItem,
)
from asmbly_ceramics.domain.firing import RECORD_LABELS, WHOLE_RANGES, Program, Speed
from asmbly_ceramics.domain.ids import ItemId, is_item_id
from asmbly_ceramics.domain.limits import (
    EMAIL_MAX,
    FIRING_NUMBER_MAX,
    HOURS_TEXT_MAX,
    ITEM_NAME_MAX,
    PICKUP_WINDOW_MAX,
    PICKUP_WINDOW_MIN,
    RECEIVED_CAP_WINDOW,
    RECEIVED_EMAILS_PER_DAY_MAX,
    RECEIVED_EMAILS_PER_DAY_MIN,
    STUDIO_TZ,
)
from asmbly_ceramics.domain.studio import (
    CatalogItem,
    CatalogList,
    SettingChange,
    Studio,
    can_delete_item,
    describe_program,
    nameable_cones,
)
from asmbly_ceramics.mail.compose import austin_date, austin_time
from asmbly_ceramics.ports.records import BadCursor, CommitOutcomeUnknown, Conflict
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.settings import HISTORY_PAGE as HISTORY_PAGE  # 50 a page, one constant
from asmbly_ceramics.use_cases.settings import StudioView
from asmbly_ceramics.web.console.auth import require_staff, require_staff_post
from asmbly_ceramics.web.console.common import Staff, form_version, render, services
from asmbly_ceramics.web.errors import PageError

RECENT_CHANGES = 10
LISTS = {
    "kilns": CatalogList.KILNS,
    "firing-types": CatalogList.FIRING_TYPES,
    "glaze-types": CatalogList.GLAZE_TYPES,
    "reasons": CatalogList.REASONS,
    "cones": CatalogList.CONES,
    "clay-bodies": CatalogList.CLAY_BODIES,
}
SLUGS = {which: slug for slug, which in LISTS.items()}
TITLES = {
    CatalogList.KILNS: "Kilns",
    CatalogList.FIRING_TYPES: "Firing types",
    CatalogList.GLAZE_TYPES: "Glaze types",
    CatalogList.REASONS: "Rejection reasons",
    CatalogList.CONES: "Cones",
    CatalogList.CLAY_BODIES: "Clay bodies",
}
CHANGED_ELSEWHERE = "The settings changed while you were working. Here they are now; try again."
MAYBE_SAVED = "That may or may not have been saved. Reload the settings to check before trying again."
TEST_SENT = "A test email is on its way to you from the new address."
DONE = {
    "email": "Email settings saved.",
    "added": "Added.",
    "retired": "Retired.",
    "restored": "Brought back.",
    "deleted": "Deleted.",
    "program": "Default program saved.",
    "counts": "Firing counts saved.",
    "elements": "New elements recorded. The next firing is number 1.",
}
CHECK_PROGRAM = "Check the default program: the fields marked need fixing."
CHECK_COUNTS = "Check the firing counts: the form shows what needs fixing."
PROGRAM_FIELDS = ("cone", "speed", "preheat_hours", "hold_minutes")
COUNT_FIELDS = ("since_elements", "all_time")


@dataclass(frozen=True)
class EmailForm:
    """The emails card as typed; staff-typed text is never logged."""

    sending_address: str = field(default="", repr=False)
    pickup_window_days: str = ""
    pickup_hours_text: str = field(default="", repr=False)
    received_emails_per_day: str = ""
    error_field: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ListForm:
    which: CatalogList
    name: str = ""
    error: str | None = None


@dataclass(frozen=True)
class ProgramForm:
    """A firing type's default program as typed, after `InvalidRecord` or a `Conflict`."""

    item: ItemId
    values: Mapping[str, str]
    errors: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CountsForm:
    """A kiln's firing counts as typed, after `InvalidSetting` or a `Conflict`."""

    item: ItemId
    values: Mapping[str, str]
    error_field: str | None = None
    error: str | None = None


def program_values(program: Program | None) -> dict[str, str]:
    """A default program as its four fields show it ("" when not set)."""
    if program is None:
        return dict.fromkeys(PROGRAM_FIELDS, "")
    return {
        "cone": program.cone or "",
        "speed": "" if program.speed is None else program.speed.value,
        "preheat_hours": "" if program.preheat_hours is None else str(program.preheat_hours),
        "hold_minutes": "" if program.hold_minutes is None else str(program.hold_minutes),
    }


def _program_row(studio: Studio, item: CatalogItem, refused: ProgramForm | None) -> dict[str, Any]:
    """The "Default program" form of one firing type: its cones are the domain's
    `nameable_cones`, the ones `set_default_program` takes."""
    program = item.default_program
    cones = nameable_cones(studio, None if program is None else program.cone)
    mine = refused is not None and refused.item == item.id
    return {
        "summary": None if program is None else describe_program(studio, program),
        "fields": dict(refused.values) if mine and refused else program_values(program),
        "errors": dict(refused.errors) if mine and refused else {},
        "open": mine,
        "cones": [(cone.id, f"{cone.name} (retired)" if cone.retired else cone.name) for cone in cones],
    }


def _counts_row(item: CatalogItem, refused: CountsForm | None) -> dict[str, Any]:
    """The "Firing counts" form of one kiln. Its fields start blank, not with the stored
    counts: those are as of their own day, and saving them again unchanged would date
    them today and lose the firings since. The summary shows them, with their day."""
    counts = item.counts
    mine = refused is not None and refused.item == item.id
    values = dict(refused.values) if mine and refused else dict.fromkeys(COUNT_FIELDS, "")
    summary = None
    if counts is not None:
        as_of = austin_date(counts.as_of.astimezone(STUDIO_TZ).date())
        summary = f"{counts.since_elements:,} since new elements, {counts.all_time:,} all time, as of {as_of}"
    return {
        "fields": values,
        "summary": summary,
        "error_field": refused.error_field if mine and refused else None,
        "error": refused.error if mine and refused else None,
        "open": mine,
    }


def _email_form(studio: Studio) -> EmailForm:
    return EmailForm(
        studio.sending_address,
        str(studio.pickup_window_days),
        studio.pickup_hours_text,
        str(studio.received_emails_per_day),
    )


def change_line(change: SettingChange) -> dict[str, str]:
    return {"what": change.what, "by": change.by, "at": austin_time(change.at)}


def _settings_page(
    request: Request,
    staff: Staff,
    *,
    email: EmailForm | None = None,
    list_form: ListForm | None = None,
    program_form: ProgramForm | None = None,
    counts_form: CountsForm | None = None,
    notice: str | None = None,
    problem: str | None = None,
    status: int = 200,
) -> Response:
    view: StudioView = services(request).view_studio(None, RECENT_CHANGES)
    studio = view.studio
    lists = []
    for which in CatalogList:
        items = []
        for item in studio.items(which):
            used = view.used.get((which, item.id), False)
            row: dict[str, Any] = {
                "item": item,
                "used": used,
                "can_delete": can_delete_item(item, used=used),
                "program": None,
                "counts": None,
            }
            if which is CatalogList.FIRING_TYPES:
                row["program"] = _program_row(studio, item, program_form)
            elif which is CatalogList.KILNS:
                row["counts"] = _counts_row(item, counts_form)
            items.append(row)
        form = list_form if list_form is not None and list_form.which is which else ListForm(which)
        lists.append(
            {"which": which, "slug": SLUGS[which], "title": TITLES[which], "rows": items, "form": form}
        )
    context: dict[str, Any] = {
        "tab": "settings",
        "studio": studio,
        "email": email or _email_form(studio),
        "lists": lists,
        "history": [change_line(change) for change in view.history],
        "more_history": view.older is not None,
        "notice": notice,
        "problem": problem,
        "email_max": EMAIL_MAX,
        "hours_max": HOURS_TEXT_MAX,
        "name_max": ITEM_NAME_MAX,
        "window_min": PICKUP_WINDOW_MIN,
        "window_max": PICKUP_WINDOW_MAX,
        "cap_min": RECEIVED_EMAILS_PER_DAY_MIN,
        "cap_max": RECEIVED_EMAILS_PER_DAY_MAX,
        "cap_window_hours": RECEIVED_CAP_WINDOW // timedelta(hours=1),
        "labels": RECORD_LABELS,
        "whole": WHOLE_RANGES,
        "speeds": [(speed.value, speed.value.capitalize()) for speed in Speed],
        "count_max": FIRING_NUMBER_MAX,
    }
    return render(request, "console/settings.html", context, staff, status=status)


async def settings_page(request: Request) -> Response:
    staff = require_staff(request)
    notice = DONE.get(request.query_params.get("done", ""))
    return _settings_page(request, staff, notice=notice)


async def history_page(request: Request) -> Response:
    staff = require_staff(request)
    console = services(request)
    before = request.query_params.get("before")
    try:
        view = console.view_studio(before, HISTORY_PAGE, with_used=False)
    except BadCursor:  # an edited address: the first page
        before = None
        view = console.view_studio(None, HISTORY_PAGE, with_used=False)
    context = {
        "tab": "settings",
        "history": [change_line(change) for change in view.history],
        "older": view.older,
        "first_page": before is None,
    }
    return render(request, "console/history.html", context, staff)


# --- POST /console/settings/email and /test-email -------------------------------------------


def _typed(form: Mapping[str, str]) -> EmailForm:
    return EmailForm(
        form.get("sending_address", ""),
        form.get("pickup_window_days", ""),
        form.get("pickup_hours_text", ""),
        form.get("received_emails_per_day", ""),
    )


def _with_error(typed: EmailForm, error_field: str, error: str) -> EmailForm:
    return EmailForm(
        typed.sending_address,
        typed.pickup_window_days,
        typed.pickup_hours_text,
        typed.received_emails_per_day,
        error_field,
        error,
    )


async def save_email_settings(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    typed = _typed(form)
    version = form_version(form)
    try:
        services(request).change_email_settings(
            sending_address=typed.sending_address,
            pickup_window_days=typed.pickup_window_days,
            pickup_hours_text=typed.pickup_hours_text,
            received_emails_per_day=typed.received_emails_per_day,
            version=version,
            staff=staff.member,
        )
    except SendingAddressOutsideAsmbly as refused:
        email = _with_error(typed, "sending_address", refused.message)
        return _settings_page(request, staff, email=email, status=400)
    except InvalidSetting as refused:
        email = _with_error(typed, refused.field, refused.message)
        return _settings_page(request, staff, email=email, status=400)
    except Conflict:  # the stored values, so a second Save can't overwrite them unseen
        return _settings_page(request, staff, problem=CHANGED_ELSEWHERE, status=409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return RedirectResponse("/console/settings?done=email", status_code=303)


async def send_test_email(request: Request) -> Response:
    """Sends from the address in the field, saved or not, to the signed-in member; saves
    nothing, and shows the page again with what was typed, so it can be saved after."""
    staff, form = await require_staff_post(request)
    typed = _typed(form)
    try:
        services(request).send_test_email(sending_address=typed.sending_address, staff=staff.member)
    except SendingAddressOutsideAsmbly as refused:
        email = _with_error(typed, "sending_address", refused.message)
        return _settings_page(request, staff, email=email, status=400)
    except (NoStaffEmail, TestEmailFailed) as refused:
        return _settings_page(request, staff, email=typed, problem=refused.message, status=400)
    return _settings_page(request, staff, email=typed, notice=TEST_SENT)


# --- POST /console/settings/{list}/... -----------------------------------------------------


def _list(request: Request) -> CatalogList:
    which = LISTS.get(request.path_params["list"])
    if which is None:
        raise PageError(404)
    return which


def _item_id(form: Mapping[str, str]) -> ItemId:
    raw = form.get("item", "")
    if not is_item_id(raw):
        raise PageError(400)
    return ItemId(raw)


async def add_item(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    which = _list(request)
    name = form.get("name", "")
    try:
        services(request).add_item(
            which,
            name,
            needs_glaze_type=which is CatalogList.FIRING_TYPES and form.get("needs_glaze_type") == "1",
            needs_message=which is CatalogList.REASONS and form.get("needs_message") == "1",
            version=form_version(form),
            staff=staff.member,
        )
    except (InvalidSetting, DuplicateItem) as refused:
        list_form = ListForm(which, name, refused.message)
        return _settings_page(request, staff, list_form=list_form, status=400)
    except Conflict:
        return _settings_page(
            request, staff, list_form=ListForm(which, name), problem=CHANGED_ELSEWHERE, status=409
        )
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return RedirectResponse(f"/console/settings?done=added#{SLUGS[which]}", status_code=303)


async def _change_item(request: Request, action: str) -> Response:
    staff, form = await require_staff_post(request)
    which = _list(request)
    item = _item_id(form)
    version = form_version(form)
    console = services(request)
    changes: dict[str, Callable[[CatalogList, ItemId, int, StaffMember], Studio]] = {
        "retired": console.retire_item,
        "restored": console.restore_item,
        "deleted": console.delete_item,
    }
    change = changes[action]
    try:
        change(which, item, version, staff.member)
    except (InvalidSetting, ItemInUse, UnknownItem) as refused:
        return _settings_page(request, staff, list_form=ListForm(which, error=refused.message), status=400)
    except Conflict:
        return _settings_page(request, staff, problem=CHANGED_ELSEWHERE, status=409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return RedirectResponse(f"/console/settings?done={action}#{SLUGS[which]}", status_code=303)


async def retire_item(request: Request) -> Response:
    return await _change_item(request, "retired")


async def restore_item(request: Request) -> Response:
    return await _change_item(request, "restored")


async def delete_item(request: Request) -> Response:
    return await _change_item(request, "deleted")


# --- POST /console/settings/firing-types/{item}/program, /kilns/{item}/... ------------------


def _path_item(request: Request) -> ItemId:
    """The path's item ID, or a 404 page before any use case runs."""
    raw = request.path_params["item"]
    if not is_item_id(raw):
        raise PageError(404)
    return ItemId(raw)


async def set_default_program(request: Request) -> Response:
    """The firing type's default program; all four fields blank clears it."""
    staff, form = await require_staff_post(request)
    item = _path_item(request)
    version = form_version(form)
    values = {name: form.get(name, "") for name in PROGRAM_FIELDS}
    try:
        services(request).set_default_program(item, values, version, staff.member)
    except UnknownItem:
        raise PageError(404) from None
    except InvalidRecord as refused:
        program = ProgramForm(item, values, refused.errors)
        return _settings_page(request, staff, program_form=program, problem=CHECK_PROGRAM, status=400)
    except Conflict:  # the typed values, open, under the page's new version
        program = ProgramForm(item, values)
        return _settings_page(request, staff, program_form=program, problem=CHANGED_ELSEWHERE, status=409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return RedirectResponse("/console/settings?done=program#firing-types", status_code=303)


async def set_kiln_counts(request: Request) -> Response:
    """The kiln's firing counts as staff typed them, as of now."""
    staff, form = await require_staff_post(request)
    item = _path_item(request)
    version = form_version(form)
    values = {name: form.get(name, "") for name in COUNT_FIELDS}
    try:
        services(request).set_kiln_counts(
            item, values["since_elements"], values["all_time"], version, staff.member
        )
    except UnknownItem:
        raise PageError(404) from None
    except InvalidSetting as refused:
        counts = CountsForm(item, values, refused.field, refused.message)
        return _settings_page(request, staff, counts_form=counts, problem=CHECK_COUNTS, status=400)
    except Conflict:  # the typed values, open, under the page's new version
        counts = CountsForm(item, values)
        return _settings_page(request, staff, counts_form=counts, problem=CHANGED_ELSEWHERE, status=409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return RedirectResponse("/console/settings?done=counts#kilns", status_code=303)


async def record_new_elements(request: Request) -> Response:
    """New elements in the kiln: its next firing is number 1 since elements."""
    staff, form = await require_staff_post(request)
    item = _path_item(request)
    version = form_version(form)
    try:
        services(request).record_new_elements(item, version, staff.member)
    except UnknownItem:
        raise PageError(404) from None
    except Conflict:
        return _settings_page(request, staff, problem=CHANGED_ELSEWHERE, status=409)
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    return RedirectResponse("/console/settings?done=elements#kilns", status_code=303)
