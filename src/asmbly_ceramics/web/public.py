"""The public drop-off form's endpoints (#2): the form, upload slots, submit, the ID page
and the health check.

Each turns a request into one use case call and its result into a response; every rule
is the domain's. Logs carry the outcome, the drop-off's ID and refused fields' names,
never a value the person typed, a cookie, a token or an address.
"""

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.templating import Jinja2Templates

from asmbly_ceramics.domain.errors import (
    FORM_EXPIRED_KEY,
    DropOffNotTaken,
    InvalidDetails,
    SubmissionNotFound,
    TooManySubmissions,
)
from asmbly_ceramics.domain.limits import PIECES_MIN
from asmbly_ceramics.domain.photos import PHOTO_COUNT_KEY, PhotoRefusal, distinct_slots, is_photo_count
from asmbly_ceramics.mail.compose import austin_time
from asmbly_ceramics.ports.errors import RecordsUnavailable, Unavailable, error_code
from asmbly_ceramics.ports.photos import PhotosAlreadyKept
from asmbly_ceramics.ports.records import Conflict
from asmbly_ceramics.use_cases.keys import is_form_token
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.use_cases.studio import StudioChoices
from asmbly_ceramics.use_cases.uploads import SlotRequest
from asmbly_ceramics.web.errors import TRY_AGAIN, PageError, error_response
from asmbly_ceramics.web.fields import (
    COOKIES_NEEDED,
    FORM_FIELDS,
    MESSAGES,
    PHOTO_MESSAGES,
    UPLOAD_FAILED,
    FieldMessages,
    MalformedForm,
    PostedForm,
    field_messages,
    read_form,
    submit_request,
)
from asmbly_ceramics.web.security import (
    DEVICE_COOKIE,
    DEVICE_COOKIE_MAX_AGE,
    RECEIVED_COOKIE,
    client_address,
    new_device,
    new_token,
    read_body,
    require_same_origin,
    sign,
    verify,
)

if TYPE_CHECKING:
    from asmbly_ceramics.web.app import WebServices, WebSettings

FORM_BODY_MAX = 16 * 1024
SLOTS_BODY_MAX = 1024
RECEIVED_LIFETIME = timedelta(minutes=30)
FORM_TYPE = "application/x-www-form-urlencoded"
_NO_ERRORS = FieldMessages(by_field={}, photos=())


def _services(request: Request) -> WebServices:
    services: WebServices = request.app.state.services
    return services


def _settings(request: Request) -> WebSettings:
    settings: WebSettings = request.app.state.settings
    return settings


def _now(request: Request) -> datetime:
    return _services(request).clock.now()


def _device(request: Request) -> str:
    return request.cookies.get(DEVICE_COOKIE, "")


def _page_log(outcome: str, *, drop_off_id: str | None = None, fields: str | None = None) -> None:
    if drop_off_id is not None:
        log_event("drop_off_page", outcome=outcome, drop_off_id=drop_off_id)
    elif fields is not None:
        log_event("drop_off_page", outcome=outcome, fields=fields)
    else:
        log_event("drop_off_page", outcome=outcome)


def _media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";")[0].strip().lower()


# --- GET / -------------------------------------------------------------------


async def form_page(request: Request) -> Response:
    response = _render_form(request, status=200, token=new_token())
    _page_log("shown")
    return response


def _render_form(
    request: Request,
    *,
    status: int,
    token: str,
    values: Mapping[str, str] | None = None,
    messages: FieldMessages = _NO_ERRORS,
    kept_slots: tuple[str, ...] = (),
    notice: str | None = None,
    choices: StudioChoices | None = None,
) -> Response:
    if choices is None:
        choices = _services(request).view_studio_choices()
    context: dict[str, Any] = {
        "choices": choices,
        "token": token,
        "values": values or dict.fromkeys(FORM_FIELDS, ""),
        "messages": messages,
        "kept_slots": kept_slots,
        "notice": notice,
        "photo_messages": {
            "count": MESSAGES[PHOTO_COUNT_KEY],
            "too_large": PHOTO_MESSAGES[PhotoRefusal.TOO_LARGE],
            "failed": UPLOAD_FAILED,
            "try_again": TRY_AGAIN,
            "expired": COOKIES_NEEDED,
        },
    }
    if not context["values"].get("pieces"):
        context["values"] = {**context["values"], "pieces": str(PIECES_MIN)}
    templates: Jinja2Templates = request.app.state.templates
    response: Response = templates.TemplateResponse(request, "form.html", context, status_code=status)
    if not is_form_token(_device(request)):
        # Only ever used hashed, as the rate limit's key (phase 2a).
        response.set_cookie(
            DEVICE_COOKIE,
            new_device(),
            max_age=DEVICE_COOKIE_MAX_AGE,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
    return response


# --- POST /drop-off/uploads ------------------------------------------------------


def _bad_request() -> JSONResponse:
    _page_log("bad_request")
    return JSONResponse({"error": "bad_request"}, status_code=400)


async def upload_slots(request: Request) -> Response:
    require_same_origin(request, request.app.state.site_origin)
    source_address = client_address(request)
    if _media_type(request) != "application/json":
        return _bad_request()
    body = await read_body(request, SLOTS_BODY_MAX)
    try:
        payload = json.loads(body)
    except ValueError, RecursionError:  # bad JSON, bad UTF-8, or nested past the parser's depth
        return _bad_request()
    if not isinstance(payload, dict):
        return _bad_request()
    count, token = payload.get("count"), payload.get("submission")
    if type(count) is not int or not is_photo_count(count):  # JSON true is a bool, not a count
        return _bad_request()
    if not isinstance(token, str) or not is_form_token(token):
        return _bad_request()
    request_slots = _services(request).request_upload_slots
    try:
        slots = request_slots(
            SlotRequest(count=count, device=_device(request), source_address=source_address)
        )
    except InvalidDetails as refused:
        if "form" in refused.errors:
            _page_log("expired")
            return JSONResponse({"error": "expired"}, status_code=400)
        return _bad_request()
    except TooManySubmissions as refused:
        _page_log("rate_limited")
        return JSONResponse({"error": "rate_limited", "message": refused.message}, status_code=429)
    except Unavailable as error:
        if not isinstance(error, RecordsUnavailable):  # the limiter's failure is the use case's to log
            log_event("upload_slots_unavailable", level=logging.WARNING, error_code=error.code)
        return JSONResponse({"error": "unavailable"}, status_code=503)
    issued = [{"id": slot.slot_id, "url": slot.post.url, "fields": dict(slot.post.fields)} for slot in slots]
    return JSONResponse({"slots": issued})


# --- POST /drop-off --------------------------------------------------------------


async def submit(request: Request) -> Response:
    require_same_origin(request, request.app.state.site_origin)
    source_address = client_address(request)
    if _media_type(request) != FORM_TYPE:
        raise PageError(400)
    body = await read_body(request, FORM_BODY_MAX)
    try:
        form = read_form(body)
    except MalformedForm:
        raise PageError(400) from None
    request_ = submit_request(form, device=_device(request), source_address=source_address)
    # Read first, so a 503 can still show the form with its token when the store fails.
    choices = _services(request).view_studio_choices()
    try:
        submitted = _services(request).submit_drop_off(request_)
    except InvalidDetails as refused:
        return _refused(request, form, refused.errors, choices)
    except TooManySubmissions as refused:
        _page_log("rate_limited")
        return error_response(request, 429, refused.message)
    except DropOffNotTaken as refused:
        _page_log("not_taken")
        return error_response(request, 429, refused.message)
    except (Unavailable, Conflict, PhotosAlreadyKept) as error:
        code = error.code if isinstance(error, Unavailable) else type(error).__name__
        log_event("drop_off_unavailable", level=logging.WARNING, error_code=error_code(code))
        # The same token: sending again answers with the drop-off if it was stored.
        return _render_form(
            request,
            status=503,
            token=form.submission if is_form_token(form.submission) else new_token(),
            values=form.values,
            kept_slots=_kept_slots(form.slots, {}),
            notice=TRY_AGAIN,
            choices=choices,
        )
    _page_log("repeated" if submitted.repeated else "submitted", drop_off_id=str(submitted.view.id))
    url = "/drop-off/received?again=1" if submitted.repeated else "/drop-off/received"
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        RECEIVED_COOKIE,
        sign(submitted.token_hash, _now(request) + RECEIVED_LIFETIME, _settings(request).cookie_key),
        max_age=int(RECEIVED_LIFETIME.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


def _refused(
    request: Request, form: PostedForm, errors: Mapping[str, str], choices: StudioChoices
) -> Response:
    expired = errors.get("form") == FORM_EXPIRED_KEY
    field_errors = {name: key for name, key in errors.items() if name != "form"}
    _page_log("expired" if expired else "refused", fields=",".join(sorted(errors)))
    return _render_form(
        request,
        status=400,
        token=new_token() if expired or not is_form_token(form.submission) else form.submission,
        values=form.values,
        messages=field_messages(field_errors),
        kept_slots=_kept_slots(form.slots, field_errors),
        notice=MESSAGES[FORM_EXPIRED_KEY] if expired else None,
        choices=choices,
    )


def _kept_slots(slots: tuple[str, ...], errors: Mapping[str, str]) -> tuple[str, ...]:
    """The uploads worth keeping for the next try: the use case's distinct slots
    (`distinct_slots`, the numbering its `photo.<n>` keys use) minus the refused ones.
    None when the slots themselves were refused."""
    distinct = distinct_slots(slots)
    if "photos" in errors or distinct is None:
        return ()
    return tuple(slot for n, slot in enumerate(distinct, start=1) if f"photo.{n}" not in errors)


# --- GET /drop-off/received ------------------------------------------------------


async def received(request: Request) -> Response:
    token_hash = verify(request.cookies.get(RECEIVED_COOKIE), _now(request), _settings(request).cookie_key)
    if token_hash is None:
        return RedirectResponse("/", status_code=303)
    try:
        view = _services(request).received_summary(token_hash)
    except SubmissionNotFound:
        return RedirectResponse("/", status_code=303)
    context = {
        "view": view,
        "when": austin_time(view.created_at),
        "again": request.query_params.get("again") == "1",
    }
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "received.html", context)


# --- GET /health -------------------------------------------------------------------


async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok", "version": _settings(request).version})
