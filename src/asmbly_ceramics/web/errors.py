"""Refusals as pages that say what to do and nothing more.

A page never shows an exception's text, a traceback or AWS's message: each status has a
fixed sentence, and the one log line for a crash holds the exception's class name only.
"""

import logging

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.templating import Jinja2Templates

from asmbly_ceramics.domain.errors import TooManySubmissions
from asmbly_ceramics.ports.errors import Unavailable
from asmbly_ceramics.ports.errors import error_code as safe_error_code
from asmbly_ceramics.use_cases.log import log_event

TRY_AGAIN = "Something went wrong on our side. Please try again."
MESSAGES = {
    400: "Something was wrong with that request. Go back to the drop-off form and try again.",
    403: "This form can only be sent from the drop-off page.",
    404: "There's no page here.",
    405: "There's no page here.",
    413: "That was too much to send at once. Go back to the drop-off form and try again.",
    429: TooManySubmissions().message,
    500: TRY_AGAIN,
    503: TRY_AGAIN,
}


class PageError(Exception):
    """Stop and answer with the error page for `status`; `message` replaces the
    status's fixed sentence only with another fixed sentence (a domain error's)."""

    def __init__(self, status: int, message: str | None = None) -> None:
        if status not in MESSAGES:
            raise ValueError("a page error's status has a message")
        super().__init__(status)
        self.status = status
        self.message = message or MESSAGES[status]


def error_response(request: Request, status: int, message: str | None = None) -> Response:
    """The error page, or JSON for the upload slots' endpoint, which a script reads."""
    if request.url.path == "/drop-off/uploads":
        return JSONResponse({"error": _JSON_ERRORS.get(status, "unavailable")}, status_code=status)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request, "error.html", {"message": message or MESSAGES[status]}, status_code=status
    )


_REFUSALS = {400: "bad_request", 403: "other_origin", 413: "too_large"}
_JSON_ERRORS = {
    400: "bad_request",
    403: "forbidden",
    405: "method_not_allowed",
    413: "bad_request",
    429: "rate_limited",
}


async def page_error(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, PageError):  # registered for PageError only
        raise exc
    if exc.status in _REFUSALS:  # counted by phase 7; no value from the request
        log_event("page_refused", outcome=_REFUSALS[exc.status])
    return error_response(request, exc.status, exc.message)


async def http_error(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, HTTPException):  # registered for HTTPException only
        raise exc
    status = exc.status_code if exc.status_code in MESSAGES else 400
    response = error_response(request, status)
    if exc.headers:
        response.headers.update(exc.headers)  # 405's Allow
    return response


async def unavailable(request: Request, exc: Exception) -> Response:
    """A port that can't reach AWS: "try again". Logged by its code, never its text."""
    if not isinstance(exc, Unavailable):  # registered for Unavailable only
        raise exc
    log_event("page_unavailable", level=logging.WARNING, error_code=safe_error_code(exc.code))
    return error_response(request, 503)


async def crashed(request: Request, exc: Exception) -> Response:
    """Anything else: a plain 500 page and one line with the exception's class name."""
    log_event("page_crashed", level=logging.ERROR, error_code=safe_error_code(type(exc).__name__))
    return error_response(request, 500)
