"""The console on the in-memory fakes: the `console` fixture and its helpers.

`MemoryStaffTokens` accepts made-up tokens: a member of `ceramics` is a key of
`members`, someone signed in outside the group a key of `outsiders`. Made-up details are
built in code (`tests/domain/builders.py`). The client talks `https`, so the `__Host-`
cookies come back.
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from starlette.testclient import TestClient

from asmbly_ceramics.adapters.memory.staff_tokens import MemoryStaffTokens
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.ports.secrets import SecretName
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.web.app import WebSettings, create_app
from asmbly_ceramics.web.console import ConsoleServices
from asmbly_ceramics.web.console.csrf import csrf_token
from asmbly_ceramics.web.console.session import SESSION_COOKIE, seal_session
from tests.domain.builders import STAFF, TEST_NAME
from tests.use_cases.conftest import World
from tests.use_cases.conftest import world as world  # the fakes and use cases
from tests.use_cases.flows import STAFF_EMAIL
from tests.use_cases.test_submit import a_device, a_request, a_token
from tests.web.conftest import BUCKET_ORIGIN, SITE, VERSION

ORIGIN = {"origin": SITE}
OUTSIDER = "front.desk"
_CSRF = re.compile(r'name="csrf" value="([A-Za-z0-9_-]+)"')


def console_services(world: World) -> ConsoleServices:
    return ConsoleServices(
        staff_tokens=world.staff_tokens,
        secrets=world.secrets,
        clock=world.clock,
        studio=world.studio,
        site_url=SITE,
        waiting_list=world.waiting,
        find_drop_offs=world.find,
        view_drop_off=world.view,
        view_photo=world.view_photo,
        preview_rejection=world.preview,
        reject_drop_off=world.reject,
        undo_rejection=world.undo,
        retry_email=world.retry_email,
        emails_needing_attention=world.emails_needing_attention,
    )


def console_settings(world: World) -> WebSettings:
    return WebSettings(
        site_url=SITE,
        photo_upload_origin=BUCKET_ORIGIN,
        version=VERSION,
        cookie_key=world.secrets.get(SecretName.SESSION_KEY),
    )


@dataclass
class Console:
    client: TestClient
    world: World

    @property
    def tokens(self) -> MemoryStaffTokens:
        return self.world.staff_tokens

    def sign_in(self, *, groups: tuple[str, ...] = ("ceramics",), username: str = STAFF) -> str:
        """A made-up ID token for `username`, in the session cookie, as the callback leaves it."""
        token = f"made-up-token-{username}-{len(self.tokens.members) + len(self.tokens.outsiders)}"
        if "ceramics" in groups:
            self.tokens.members[token] = StaffMember(username, STAFF_EMAIL)
        else:
            self.tokens.outsiders[token] = username
        self.client.cookies.set(SESSION_COOKIE, self.seal(token))
        return token

    def seal(self, token: str) -> str:
        """The session cookie's value for `token`, as the callback sets it."""
        return seal_session(token, self.world.secrets.get(SecretName.SESSION_KEY))

    def csrf(self) -> str:
        sealed = self.client.cookies.get(SESSION_COOKIE)
        assert sealed is not None
        return csrf_token(sealed.rpartition(".")[0], self.world.secrets.get(SecretName.SESSION_KEY))

    def get(self, path: str) -> httpx2.Response:
        return self.client.get(path, follow_redirects=False)

    def post(
        self,
        path: str,
        data: Mapping[str, str] | None = None,
        *,
        csrf: bool = True,
        headers: Mapping[str, str] | None = None,
    ) -> httpx2.Response:
        fields = dict(data or {})
        if csrf:
            fields.setdefault("csrf", self.csrf())
        return self.client.post(
            path, data=fields, headers=dict(ORIGIN if headers is None else headers), follow_redirects=False
        )

    def drop_off(
        self,
        number: int,
        *,
        name: str = TEST_NAME,
        firing_type: str = "bisque",
        glaze_type: str | None = None,
    ) -> DropOffId:
        """A drop-off made through the form, from its own made-up device."""
        request = a_request(
            self.world,
            token=a_token(number),
            device=a_device(number),
            name=name,
            firing_type=firing_type,
            glaze_type=glaze_type,
        )
        return self.world.submit(request).view.id

    def version(self, id: DropOffId) -> str:
        drop_off = self.world.records.drop_off(id)
        assert drop_off is not None
        return str(drop_off.version)


def events(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str | None]]:
    """The app's log lines as (event, user)."""
    return [(r.message, getattr(r, "user", None)) for r in caplog.records if r.name == "asmbly_ceramics"]


def page_csrf(html: str) -> str:
    match = _CSRF.search(html)
    assert match is not None
    return match.group(1)


def query_of(location: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(location).query)


@pytest.fixture
def console(world: World) -> Iterator[Console]:
    app = create_app(None, console_settings(world), console_services(world))
    with TestClient(app, base_url=SITE) as client:
        yield Console(client, world)


__all__ = ["OUTSIDER", "Console", "console", "events", "page_csrf", "query_of", "world"]
