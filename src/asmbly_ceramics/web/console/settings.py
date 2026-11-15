"""The studio's settings (#6): the emails card (the sending address, the test email, the
pickup window and hours), the studio's lists, and the change history.

The domain decides every rule (an address only at asmbly.org, the window's range, unique
names, retire before delete, a used item kept) and the use cases log every change by
username and item ID. A page never logs the address or the hours text, and puts no typed
value in a URL.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from asmbly_ceramics.domain.errors import (
    DuplicateItem,
    InvalidSetting,
    ItemInUse,
    NoStaffEmail,
    SendingAddressOutsideAsmbly,
    TestEmailFailed,
    UnknownItem,
)
from asmbly_ceramics.domain.ids import ItemId, is_item_id
from asmbly_ceramics.domain.limits import (
    EMAIL_MAX,
    HOURS_TEXT_MAX,
    ITEM_NAME_MAX,
    PICKUP_WINDOW_MAX,
    PICKUP_WINDOW_MIN,
)
from asmbly_ceramics.domain.studio import CatalogList, SettingChange, Studio
from asmbly_ceramics.mail.compose import austin_time
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
}
SLUGS = {which: slug for slug, which in LISTS.items()}
TITLES = {
    CatalogList.KILNS: "Kilns",
    CatalogList.FIRING_TYPES: "Firing types",
    CatalogList.GLAZE_TYPES: "Glaze types",
    CatalogList.REASONS: "Rejection reasons",
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
}


@dataclass(frozen=True)
class EmailForm:
    """The emails card as typed; staff-typed text is never logged."""

    sending_address: str = field(default="", repr=False)
    pickup_window_days: str = ""
    pickup_hours_text: str = field(default="", repr=False)
    error_field: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ListForm:
    which: CatalogList
    name: str = ""
    error: str | None = None


def _email_form(studio: Studio) -> EmailForm:
    return EmailForm(studio.sending_address, str(studio.pickup_window_days), studio.pickup_hours_text)


def change_line(change: SettingChange) -> dict[str, str]:
    return {"what": change.what, "by": change.by, "at": austin_time(change.at)}


def _settings_page(
    request: Request,
    staff: Staff,
    *,
    email: EmailForm | None = None,
    list_form: ListForm | None = None,
    notice: str | None = None,
    problem: str | None = None,
    status: int = 200,
) -> Response:
    view: StudioView = services(request).view_studio(None, RECENT_CHANGES)
    studio = view.studio
    lists = []
    for which in CatalogList:
        items = [
            {"item": item, "used": view.used.get((which, item.id), False)} for item in studio.items(which)
        ]
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
        form.get("sending_address", ""), form.get("pickup_window_days", ""), form.get("pickup_hours_text", "")
    )


def _with_error(typed: EmailForm, error_field: str, error: str) -> EmailForm:
    return EmailForm(
        typed.sending_address, typed.pickup_window_days, typed.pickup_hours_text, error_field, error
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
