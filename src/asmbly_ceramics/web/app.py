"""The web app: `create_app(services, settings)` builds the public form's routes, its
templates and static files, the headers every response carries, and the error pages.

Phase 8 adds the console's routes to this factory; nothing here assumes there are none.
`create_from_environment` is what a deployed function runs (`entry/run.sh`): it builds
`WebServices` on the AWS adapters (`composition.py`) and puts each request under its
deadline. The tests and `local.py` build them on the in-memory fakes.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from asmbly_ceramics import deadline
from asmbly_ceramics.domain import limits
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.errors import Unavailable
from asmbly_ceramics.use_cases.received import ReceivedSummary
from asmbly_ceramics.use_cases.studio import ViewStudioChoices
from asmbly_ceramics.use_cases.submit import SubmitDropOff
from asmbly_ceramics.use_cases.uploads import RequestUploadSlots
from asmbly_ceramics.web import errors, public
from asmbly_ceramics.web.security import CACHE_STATIC, csp, origin_of, security_headers

COOKIE_KEY_MIN_BYTES = 32
APP_ROLES = ("form",)  # phase 8 adds "console"
STATIC = Path(__file__).parent / "static"


@dataclass(frozen=True)
class WebSettings:
    site_url: str  # "https://ceramics.asmbly.org"; its scheme and host are the only allowed Origin
    photo_upload_origin: str  # "https://<bucket>.s3.us-east-2.amazonaws.com", for connect-src
    version: str  # shown by /health and on static URLs
    cookie_key: bytes = field(repr=False)  # signs __Host-received: SecretName.FORM_KEY (phase 7)

    def __post_init__(self) -> None:
        origin_of(self.site_url)  # ValueError when it has no scheme and host
        csp(self.photo_upload_origin)  # ValueError on a separator in the source
        if (
            origin_of(self.photo_upload_origin) != self.photo_upload_origin.lower()
            or "*" in self.photo_upload_origin
        ):
            raise ValueError("the photo upload origin is one scheme and host, no wildcard")
        if len(self.cookie_key) < COOKIE_KEY_MIN_BYTES:
            raise ValueError("the cookie key is too short")
        if not self.version or not self.version.isprintable() or len(self.version) > 64:
            raise ValueError("a version is a short printable string")


@dataclass(frozen=True)
class WebServices:
    view_studio_choices: ViewStudioChoices  # active firing types (with needs_glaze_type) and glaze types
    request_upload_slots: RequestUploadSlots
    submit_drop_off: SubmitDropOff
    received_summary: ReceivedSummary  # the ID page's summary, no contact details
    clock: Clock  # the __Host-received cookie's expiry


class SecurityHeaders:
    """Adds `security_headers` to every response, errors and 404s included, and turns
    any exception the routes and handlers didn't answer into the plain 500 page, inside
    this middleware so that page carries the headers too (Starlette's own `Exception`
    handler runs outside every middleware)."""

    def __init__(self, app: ASGIApp, *, policy: str) -> None:
        self.app = app
        self.headers = [
            (name.lower().encode(), value.encode()) for name, value in security_headers(policy).items()
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        static = scope["path"].startswith("/static/")
        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                cached = static and message["status"] in (200, 304)
                names = {name for name, _ in self.headers}
                kept = [(name, value) for name, value in message.get("headers", []) if name not in names]
                added = [
                    (name, CACHE_STATIC.encode() if cached and name == b"cache-control" else value)
                    for name, value in self.headers
                ]
                message = {**message, "headers": kept + added}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception as exc:
            if started:
                raise
            response = await errors.crashed(Request(scope, receive), exc)
            await response(scope, receive, send_with_headers)


class RequestDeadline:
    """Runs each HTTP request under `deadline.request_deadline`, so the AWS clients stop
    sending once it has passed and the page answers 503 before the function's timeout."""

    def __init__(self, app: ASGIApp, *, seconds: float = deadline.REQUEST_BUDGET_SECONDS) -> None:
        self.app = app
        self.seconds = seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with deadline.request_deadline(self.seconds):
            await self.app(scope, receive, send)


def templates_for(settings: WebSettings) -> Jinja2Templates:
    env = Environment(
        loader=PackageLoader("asmbly_ceramics.web"),
        autoescape=True,  # every template, whatever its name: `.svg` partials included
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals.update(version=settings.version, limits=limits)
    return Jinja2Templates(env=env)


def create_app(services: WebServices, settings: WebSettings) -> Starlette:
    routes = [
        Route("/", public.form_page, methods=["GET"]),
        Route("/drop-off/uploads", public.upload_slots, methods=["POST"]),
        Route("/drop-off", public.submit, methods=["POST"]),
        Route("/drop-off/received", public.received, methods=["GET"]),
        Route("/health", public.health, methods=["GET"]),
        Mount("/static", app=StaticFiles(directory=STATIC), name="static"),
    ]
    app = Starlette(
        routes=routes,
        middleware=[Middleware(SecurityHeaders, policy=csp(settings.photo_upload_origin))],
        exception_handlers={
            errors.PageError: errors.page_error,
            HTTPException: errors.http_error,
            Unavailable: errors.unavailable,
        },
    )
    app.state.services = services
    app.state.settings = settings
    app.state.site_origin = origin_of(settings.site_url)
    app.state.templates = templates_for(settings)
    return app


def create_from_environment() -> Starlette:
    """The deployed app, for uvicorn's `--factory` (`entry/run.sh`). `APP_ROLE` picks the
    function's routes: `form` today; any other value fails at start."""
    # Imported here: composition imports this module, and only a deployed function needs it.
    from asmbly_ceramics import composition
    from asmbly_ceramics.logs import configure_logging
    from asmbly_ceramics.settings import Settings, SettingsError

    role = os.environ.get("APP_ROLE", "")
    if role not in APP_ROLES:
        raise SettingsError("APP_ROLE is not a known role")
    settings = Settings.from_environment()
    configure_logging(settings.log_level, settings.version)
    app = create_app(*composition.build_form_services(settings))
    app.add_middleware(RequestDeadline)
    return app
