"""What every console page shares: stopping a request with a response, the per-request
staff check's result, reading a posted form, and rendering inside the console's layout.

Nothing here logs a value from a request.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl

from starlette.requests import Request
from starlette.responses import Response
from starlette.templating import Jinja2Templates

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.ports.secrets import SecretName
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.web.console.services import ConsoleServices
from asmbly_ceramics.web.errors import PageError
from asmbly_ceramics.web.security import read_body

FORM_BODY_MAX = 32 * 1024  # a 1,000-character message, percent-encoded, with room to spare
FORM_FIELDS_MAX = 16
FORM_TYPE = "application/x-www-form-urlencoded"


class Answer(Exception):  # noqa: N818  # not an error: a response, sent early
    """Stop here and send `response` (a redirect to the sign-in, the not-allowed page)."""

    def __init__(self, response: Response) -> None:
        super().__init__("answered")
        self.response = response


async def answer(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, Answer):  # registered for Answer only
        raise exc
    return exc.response


@dataclass(frozen=True)
class Staff:
    """A signed-in member of `ceramics`, for this request."""

    member: StaffMember
    token: str = field(repr=False)  # the session's ID token
    csrf: str = field(repr=False)  # this session's CSRF token, for every form on the page


def services(request: Request) -> ConsoleServices:
    console: ConsoleServices = request.app.state.console
    return console


def session_key(request: Request) -> bytes:
    return services(request).secrets.get(SecretName.SESSION_KEY)


def templates(request: Request) -> Jinja2Templates:
    found: Jinja2Templates = request.app.state.templates
    return found


async def read_form(request: Request) -> Mapping[str, str]:
    """A posted form's fields, the first value of each, strictly UTF-8 and bounded.
    Anything else is a 400 page; no value is ever logged."""
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != FORM_TYPE:
        raise PageError(400)
    body = await read_body(request, FORM_BODY_MAX)
    try:
        pairs = parse_qsl(
            body.decode("utf-8", errors="strict"),
            keep_blank_values=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=FORM_FIELDS_MAX,
        )
    except UnicodeDecodeError, ValueError:
        raise PageError(400) from None
    fields: dict[str, str] = {}
    for name, value in pairs:
        fields.setdefault(name, value)
    return fields


def drop_off_id(request: Request) -> DropOffId:
    """The path's `AC-n`, or a 404 page before any use case runs."""
    try:
        return DropOffId.parse(request.path_params["id"])
    except ValueError:
        raise PageError(404) from None


def not_found(id: DropOffId) -> PageError:
    return PageError(404, f"There's no drop-off {id}.")


def render(
    request: Request,
    template: str,
    context: Mapping[str, Any],
    staff: Staff,
    *,
    status: int = 200,
    attention: int | None = None,
) -> Response:
    """A console page: the band shows who is signed in, Sign out (with this session's
    CSRF token), and "Emails need attention (n)" whenever n > 0."""
    if attention is None:
        attention = len(services(request).emails_needing_attention())
    full = {"tab": "", **context, "staff": staff, "csrf": staff.csrf, "attention": attention}
    return templates(request).TemplateResponse(request, template, full, status_code=status)


def phone_text(digits: str) -> str:
    """Ten digits as `(area) exchange-line`, the way a US number is written; anything
    else as stored."""
    if len(digits) == 10 and digits.isdigit():
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return digits
