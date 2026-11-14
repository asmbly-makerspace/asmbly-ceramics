"""The web app on the in-memory fakes: the `site` fixture and helpers for the form.

Made-up details are built in code (`tests/domain/builders.py`), never written whole in a
file. The client talks `https`, so `Secure` and `__Host-` cookies come back.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

import httpx2
import pytest
from starlette.testclient import TestClient

from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.web.app import WebServices, WebSettings, create_app
from asmbly_ceramics.web.security import DEVICE_COOKIE
from tests.domain.builders import TEST_EMAIL, TEST_NAME, TEST_PHONE
from tests.use_cases.conftest import World
from tests.use_cases.conftest import world as world  # the fakes and use cases
from tests.use_cases.flows import STAFF_MEMBER

SITE = "https://testserver"
BUCKET_ORIGIN = "https://made-up-bucket.s3.us-east-2.amazonaws.com"
VERSION = "test-1"
COOKIE_KEY = b"k" * 32
ADDRESS = "203.0.113.9"  # TEST-NET-3, a documentation address
SAME_ORIGIN = {"origin": SITE, "x-forwarded-for": ADDRESS}
_TOKEN = re.compile(r'name="submission" value="([A-Za-z0-9_-]+)"')
PHOTO = b"\xff\xd8made-up-photo-bytes"


def settings() -> WebSettings:
    return WebSettings(
        site_url=SITE, photo_upload_origin=BUCKET_ORIGIN, version=VERSION, cookie_key=COOKIE_KEY
    )


def services(world: World) -> WebServices:
    return WebServices(
        view_studio_choices=world.choices,
        request_upload_slots=world.upload_slots,
        submit_drop_off=world.submit,
        received_summary=world.received,
        clock=world.clock,
    )


@dataclass
class Site:
    client: TestClient
    world: World

    def form(self) -> str:
        """Loads the form (setting the device cookie) and returns its submission token."""
        page = self.client.get("/")
        assert page.status_code == 200
        match = _TOKEN.search(page.text)
        assert match is not None
        return match.group(1)

    def device(self) -> str:
        value = self.client.cookies.get(DEVICE_COOKIE)
        assert value is not None
        return value

    def details(self, **overrides: str | list[str]) -> dict[str, str | list[str]]:
        """A valid drop-off's fields, with a fresh token and one uploaded photo."""
        fields: dict[str, str | list[str]] = {
            "submission": self.form(),
            "name": TEST_NAME,
            "email": TEST_EMAIL,
            "phone": TEST_PHONE,
            "pieces": "2",
            "firing_type": "bisque",
            "slot": list(self.world.uploaded(PHOTO)),
        }
        fields.update(overrides)
        return fields

    def retire(self, which: CatalogList, id: str) -> None:
        """Staff retire a firing or glaze type in the console (#6)."""
        studio = self.world.studio()
        self.world.retire_item(which, ItemId(id), studio.version, STAFF_MEMBER)

    def submit(
        self, fields: dict[str, str | list[str]], headers: dict[str, str] | None = None
    ) -> httpx2.Response:
        return self.client.post(
            "/drop-off", data=fields, headers=headers or SAME_ORIGIN, follow_redirects=False
        )


@pytest.fixture
def site(world: World) -> Iterator[Site]:
    with TestClient(create_app(services(world), settings()), base_url=SITE) as client:
        yield Site(client, world)
