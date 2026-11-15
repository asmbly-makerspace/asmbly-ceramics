"""One drop-off's page, its photos, the rejection preview, reject, undo, and retrying an
email (#3, #4, #5).

The use cases decide every rule (who can be rejected, the message, the same-day undo,
which email can be retried) and log what they did; a page turns their result or refusal
into a response. The rejection message is a person's words: it travels only in a POST
body and a hidden field, is shown escaped, and is never logged or put in a URL.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus, is_email_occasion
from asmbly_ceramics.domain.errors import (
    DomainError,
    EmailNotRetryable,
    ItemRetired,
    MessageRequired,
    MessageTooLong,
    NotFound,
    NotRejected,
    NotWaiting,
    UndoTooLate,
    UnknownItem,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId, is_item_id
from asmbly_ceramics.domain.limits import MESSAGE_MAX, PHOTOS_MAX, PHOTOS_MIN, STUDIO_TZ
from asmbly_ceramics.domain.photos import PhotoRef, PhotoSize
from asmbly_ceramics.domain.waiting import days_waiting
from asmbly_ceramics.mail.compose import austin_day, austin_time
from asmbly_ceramics.ports.composer import FROM_NAME
from asmbly_ceramics.ports.records import CommitOutcomeUnknown, Conflict
from asmbly_ceramics.use_cases.reject import RejectRequest, UndoRequest
from asmbly_ceramics.use_cases.view_drop_off import DropOffView
from asmbly_ceramics.web.console.auth import require_staff, require_staff_for_photo, require_staff_post
from asmbly_ceramics.web.console.common import (
    Staff,
    drop_off_id,
    form_version,
    not_found,
    phone_text,
    render,
    services,
)
from asmbly_ceramics.web.errors import PageError
from asmbly_ceramics.web.security import csp

KIND_LABELS = {
    EmailKind.RECEIVED: "Received",
    EmailKind.READY: "Ready for pickup",
    EmailKind.REJECTED: "Rejected",
}
MAYBE_SAVED = "That may or may not have been saved. Reload the drop-off to check before trying again."
# After a change, the page says what happened from a fixed word in its address: never the
# message or anything the person typed.
DONE = {
    "rejected": "{id} was rejected. The email is on its way.",
    "undone": "{id} is waiting again. No email was sent.",
    "undone-contact": (
        "{id} is waiting again. The rejection email went, or may have: contact the person directly."
    ),
    "retried": "The email to {id} will be sent again.",
}
_FIELD_OF = {
    UnknownItem: "reason",
    ItemRetired: "reason",
    MessageRequired: "message",
    MessageTooLong: "message",
}


def photo_src(ref: PhotoRef, size: PhotoSize = PhotoSize.FULL) -> str:
    path = f"/console/drop-offs/{ref.drop_off_id}/photos/{ref.index}"
    return path + "/thumb" if size is PhotoSize.THUMB else path


def _thumb_src(ref: PhotoRef) -> str:
    return photo_src(ref, PhotoSize.THUMB)


def state_text(view: DropOffView, now: datetime) -> str:
    drop_off = view.drop_off
    match drop_off.state:
        case DropOffState.WAITING:
            days = days_waiting(drop_off, now)
            return "Waiting since today" if days == 0 else f"Waiting {days} day{'' if days == 1 else 's'}"
        case DropOffState.IN_LOAD:
            return f"In load {drop_off.load_id}"
        case DropOffState.FIRED:
            return (
                "Fired"
                if drop_off.fired_at is None
                else f"Fired {austin_day(drop_off.fired_at.astimezone(STUDIO_TZ).date())}"
            )
        case DropOffState.REJECTED:
            at = drop_off.rejection.at if drop_off.rejection else None
            # "today" is the domain's same-Austin-day answer (the undo's rule), not the page's.
            when = "today" if view.can_undo_rejection else ("" if at is None else _day(at))
            return (
                f"Rejected {when}: {view.rejection_reason}" if when else f"Rejected: {view.rejection_reason}"
            )
        case _:
            return "Closed"


def _day(at: datetime) -> str:
    return austin_day(at.astimezone(STUDIO_TZ).date())


def email_status(email: Email) -> str:
    match email.status:
        case EmailStatus.SENT:
            return "Sent"
        case EmailStatus.PENDING:
            return "Waiting to send"
        case EmailStatus.SENDING:
            return "Sending"
        case EmailStatus.FAILED:
            return f"Sending failed ({email.error_code or 'unknown'})"
        case _:
            return "Cancelled"


@dataclass(frozen=True)
class Panel:
    """The reject panel as the page shows it: open or not, the typed values, and the
    refusal next to its field."""

    open: bool = False
    reason: str = ""
    message: str = field(default="", repr=False)  # staff-typed text: never in a log or traceback
    error_field: str | None = None
    error: str | None = None


def _drop_off_page(
    request: Request,
    staff: Staff,
    view: DropOffView,
    *,
    panel: Panel | None = None,
    notice: str | None = None,
    problem: str | None = None,
    status: int = 200,
) -> Response:
    now = services(request).clock.now()
    contact = view.drop_off.contact
    context: dict[str, Any] = {
        "view": view,
        "drop_off": view.drop_off,
        "state": state_text(view, now),
        "phone": phone_text(contact.phone) if contact else "",
        # URL-escaped as well as HTML-escaped: a valid address may hold `?`, `&` or `=`,
        # which in a raw mailto: would add a cc, a subject or a body.
        "mailto": "mailto:" + quote(contact.email, safe="@") if contact else "",
        "dropped_off": austin_time(view.drop_off.created_at),
        "closed_on": austin_day(view.drop_off.closed_at.astimezone(STUDIO_TZ).date())
        if view.drop_off.closed_at
        else "",
        "photo_src": photo_src,
        "emails": [(email, KIND_LABELS[email.kind], email_status(email)) for email in view.emails],
        "retryable": {(email.kind, email.occasion) for email in view.emails_needing_attention},
        "panel": panel or Panel(),
        "notice": notice,
        "problem": problem,
        "message_max": MESSAGE_MAX,
        "can_reject": view.can_reject,
    }
    return render(request, "console/drop_off.html", context, staff, status=status)


def _view(request: Request, id: DropOffId) -> DropOffView:
    try:
        return services(request).view_drop_off(id)
    except NotFound:
        raise not_found(id) from None


# --- GET /console/drop-offs/{id} ----------------------------------------------------------


async def drop_off_page(request: Request) -> Response:
    staff = require_staff(request)
    id = drop_off_id(request)
    view = _view(request, id)
    done = request.query_params.get("done", "")
    # A notice shows only when the drop-off's state agrees with it, so an old or edited
    # address can't say a waiting drop-off was rejected (or the reverse). It can't tell an
    # undo whose email went from one whose email didn't; the undo's own redirect does.
    agrees = {
        "rejected": view.drop_off.state is DropOffState.REJECTED,
        "undone": view.drop_off.state is DropOffState.WAITING,
        "undone-contact": view.drop_off.state is DropOffState.WAITING,
        "retried": True,
    }
    notice = DONE[done].format(id=id) if agrees.get(done) else None
    panel = Panel(open=request.query_params.get("reject") == "1" and view.can_reject)
    return _drop_off_page(request, staff, view, panel=panel, notice=notice)


# --- GET /console/drop-offs/{id}/photos/{k}[/thumb] ------------------------------------------


async def _photo(request: Request, size: PhotoSize) -> Response:
    require_staff_for_photo(request)
    id = drop_off_id(request)
    raw = request.path_params["k"]
    if (
        len(raw) != 1
        or not raw.isascii()
        or not raw.isdigit()
        or not PHOTOS_MIN <= int(raw) <= PHOTOS_MAX
        or raw != str(int(raw))
    ):
        raise PageError(404)
    index = int(raw)
    try:
        data = services(request).view_photo(id, index, size)
    except NotFound:
        raise PageError(404) from None
    suffix = "-thumb" if size is PhotoSize.THUMB else ""
    return Response(
        data,
        media_type="image/jpeg",
        headers={"Content-Disposition": f'inline; filename="{id}-{index}{suffix}.jpg"'},
    )


async def photo(request: Request) -> Response:
    return await _photo(request, PhotoSize.FULL)


async def thumbnail(request: Request) -> Response:
    return await _photo(request, PhotoSize.THUMB)


# --- POST .../reject/preview and .../reject ----------------------------------------------------


def _reject_request(id: DropOffId, form: Mapping[str, str], staff: Staff) -> RejectRequest:
    """`UnknownItem` for a reason without an item's shape: it can't name one."""
    reason = form.get("reason", "")
    if not is_item_id(reason):
        raise UnknownItem("reason")
    return RejectRequest(
        drop_off_id=id,
        reason=ItemId(reason),
        message=form.get("message", ""),
        version=form_version(form),
        staff=staff.member,
    )


def _refused(
    request: Request, staff: Staff, id: DropOffId, form: Mapping[str, str], error: DomainError | Conflict
) -> Response:
    """The drop-off page again, as it is now, with the panel open, the typed reason and
    message kept, and the refusal next to its field (or above, for a state or a
    conflict). Nothing was stored."""
    view = _view(request, id)
    reason, message = form.get("reason", ""), form.get("message", "")
    if isinstance(error, Conflict):
        problem = f"{id} changed while you were looking. Check it and try again."
        return _drop_off_page(
            request,
            staff,
            view,
            panel=Panel(open=view.can_reject, reason=reason, message=message),
            problem=problem,
            status=409,
        )
    if isinstance(error, NotWaiting):
        problem = error.message
        if view.drop_off.load_id is not None:
            problem += f" It is in load {view.drop_off.load_id}."
        return _drop_off_page(request, staff, view, problem=problem, status=400)
    text = error.message
    panel = Panel(
        open=True, reason=reason, message=message, error_field=_FIELD_OF.get(type(error)), error=text
    )
    return _drop_off_page(request, staff, view, panel=panel, status=400)


_REFUSALS = (UnknownItem, ItemRetired, MessageRequired, MessageTooLong, NotWaiting, Conflict)


async def preview(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    id = drop_off_id(request)
    console = services(request)
    try:
        composed = console.preview_rejection(_reject_request(id, form, staff), _thumb_src)
    except NotFound:
        raise not_found(id) from None
    except _REFUSALS as error:
        return _refused(request, staff, id, form, error)
    view = _view(request, id)
    context = {
        "drop_off": view.drop_off,
        "composed": composed,
        "to": view.drop_off.contact.email if view.drop_off.contact else "",
        "from_name": FROM_NAME,
        "from_address": console.studio().sending_address,
        "reason": form.get("reason", ""),
        "message": form.get("message", ""),
        "version": form_version(form),  # the version the staff member saw, for Send
    }
    response = render(request, "console/reject_preview.html", context, staff)
    response.headers["Content-Security-Policy"] = csp(
        request.app.state.settings.photo_upload_origin, email_preview=True
    )
    return response


async def reject(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    id = drop_off_id(request)
    try:
        services(request).reject_drop_off(_reject_request(id, form, staff))
    except NotFound:
        raise not_found(id) from None
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    except _REFUSALS as error:
        return _refused(request, staff, id, form, error)
    return RedirectResponse(f"/console/drop-offs/{id}?done=rejected", status_code=303)


# --- POST .../undo-reject --------------------------------------------------------------------


async def undo(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    id = drop_off_id(request)
    try:
        undone = services(request).undo_rejection(UndoRequest(id, form_version(form), staff.member))
    except NotFound:
        raise not_found(id) from None
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    except (NotRejected, UndoTooLate) as refused:
        return _drop_off_page(request, staff, _view(request, id), problem=refused.message, status=400)
    except Conflict:
        problem = f"{id} changed while you were looking. Check it and try again."
        return _drop_off_page(request, staff, _view(request, id), problem=problem, status=409)
    done = "undone-contact" if undone.contact_the_person else "undone"
    return RedirectResponse(f"/console/drop-offs/{id}?done={done}", status_code=303)


# --- POST .../emails/{kind}/retry ------------------------------------------------------------


async def retry(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    id = drop_off_id(request)
    try:
        kind = EmailKind(request.path_params["kind"])
    except ValueError:
        raise PageError(404) from None
    occasion = form.get("occasion", "")
    if not is_email_occasion(kind, occasion):
        raise PageError(400)
    back_to_list = form.get("back") == "emails"
    try:
        services(request).retry_email(id, kind, occasion, staff.member)
    except NotFound:
        raise not_found(id) from None
    except CommitOutcomeUnknown:
        raise PageError(503, MAYBE_SAVED) from None
    except EmailNotRetryable as refused:
        return _drop_off_page(request, staff, _view(request, id), problem=refused.message, status=400)
    except Conflict:
        problem = f"{id} changed while you were looking. Check it and try again."
        return _drop_off_page(request, staff, _view(request, id), problem=problem, status=409)
    if back_to_list:
        return RedirectResponse(f"/console/emails?done=retried&id={id}", status_code=303)
    return RedirectResponse(f"/console/drop-offs/{id}?done=retried", status_code=303)
