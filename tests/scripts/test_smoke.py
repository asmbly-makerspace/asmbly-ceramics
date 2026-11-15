"""`scripts/smoke.py` against a local stub of the site and its bucket: each check passes
when the stub answers right, and fails with its own name when the stub answers wrong."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode

import pytest
from scripts.smoke import SmokeError

from scripts import smoke
from tests.use_cases.conftest import World
from tests.use_cases.conftest import world as world  # the fakes, for the console check

VERSION = "abc1234"
TOKEN = "t" * 32
FORM_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; img-src 'self'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


class Stub(ThreadingHTTPServer):
    wrong: str = ""
    form_offline: bool = False  # as API Gateway answers when the form can't be invoked


class Handler(BaseHTTPRequestHandler):
    server: Stub

    def log_message(self, format: str, *args: object) -> None:
        pass

    def answer(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        wrong = self.server.wrong
        if self.server.form_offline and not self.path.startswith(("/console", "/bucket/")):
            self.answer(200 if wrong == "form-offline" else 503)
        elif self.path in ("/health", "/console/health"):
            check = "health" if self.path == "/health" else "console-health"
            version = "old0000" if wrong == check else VERSION
            self.answer(200, json.dumps({"status": "ok", "version": version}).encode())
        elif self.path == "/":
            headers = dict(FORM_HEADERS)
            if wrong == "form":
                headers["Cache-Control"] = "max-age=60"
            headers["Set-Cookie"] = "__Host-device=d123; Path=/; Secure; HttpOnly"
            self.answer(200, f'<input name="submission" value="{TOKEN}">'.encode(), headers)
        elif self.path == "/console":
            self.answer(302, headers={"Location": "/console/auth/sign-in?next=%2Fconsole"})
        elif self.path == "/console/auth/sign-in?next=%2Fconsole":
            site = f"http://127.0.0.1:{self.server.server_address[1]}"
            query = {
                "client_id": "made-up-client",
                "code_challenge_method": "S256",
                "redirect_uri": f"{site}/console/auth/callback",
                "state": "s",
            }
            if wrong == "console":
                query["redirect_uri"] = "https://evil.example/console/auth/callback"
            location = "https://sign-in.example.org/oauth2/authorize?" + urlencode(query)
            cookie = "__Host-signin=x.y; Path=/; Secure; HttpOnly; SameSite=Lax"
            self.answer(302, headers={"Location": location, "Set-Cookie": cookie})
        elif self.path in ("/console/loads", "/console/settings"):
            if wrong == "console-pages":
                self.answer(404)
            else:
                location = "/console/auth/sign-in?next=" + self.path.replace("/", "%2F")
                self.answer(302, headers={"Location": location})
        elif self.path == "/console/drop-offs/AC-1/photos/1":
            if wrong == "console-photo":
                self.answer(200, b"\xff\xd8", {"Content-Type": "image/jpeg"})
            else:
                self.answer(401, b"Sign in", {"Content-Type": "text/html"})
        elif self.path.startswith("/bucket/"):
            self.answer(200 if wrong == "private-photos" else 403)
        else:
            self.answer(404)

    def do_POST(self) -> None:
        wrong = self.server.wrong
        length = int(self.headers.get("Content-Length", "0"))
        if self.path == "/bucket/" and wrong == "close-early" and length > 1024:
            # As S3 may: answer before reading the body, then close.
            self.close_connection = True
            self.answer(400, b"<Error><Code>EntityTooLarge</Code></Error>")
            self.connection.shutdown(2)
            return
        body = self.rfile.read(length)
        if self.path == "/drop-off/uploads":
            site = f"http://127.0.0.1:{self.server.server_address[1]}"
            if self.headers.get("Origin") != site:
                self.answer(200 if wrong == "foreign-origin" else 403)
                return
            if wrong == "upload-slot" or "__Host-device=d123" not in self.headers.get("Cookie", ""):
                self.answer(429)
                return
            assert json.loads(body) == {"count": 2, "submission": TOKEN}
            slots = [
                {"id": name, "url": f"{site}/bucket/", "fields": {"key": f"uploads/{name}/0", "policy": "p"}}
                for name in ("a", "b")
            ]
            self.answer(200, json.dumps({"slots": slots}).encode())
        elif self.path == "/bucket/" and len(body) < 1024:
            self.answer(403 if wrong == "upload" else 204)
        elif self.path == "/bucket/":
            assert len(body) > smoke.PHOTO_MAX_BYTES
            if wrong == "oversized-upload":
                self.answer(204)
            else:
                self.answer(400, b"<Error><Code>EntityTooLarge</Code><Message>x</Message></Error>")
        else:
            self.answer(404)


@pytest.fixture
def site() -> Iterator[tuple[str, Stub]]:
    server = Stub(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server
    finally:
        server.shutdown()
        server.server_close()


def test_every_check_passes_against_a_right_site(site: tuple[str, Stub]) -> None:
    url, _ = site
    report = smoke.run(url + "/", VERSION, tries=1, wait=0)
    assert report == [
        "health: ok",
        "form: ok",
        "console-health: ok",
        "console: ok",
        "console-photo: ok",
        "console-pages: ok",
        "foreign-origin: ok",
        "upload-slot: ok",
        "upload: ok",
        "oversized-upload: refused, 400 EntityTooLarge",
        "private-photos: ok",
    ]


@pytest.mark.parametrize(
    "check",
    [
        "health",
        "form",
        "console-health",
        "console",
        "console-photo",
        "console-pages",
        "foreign-origin",
        "upload-slot",
        "upload",
        "oversized-upload",
        "private-photos",
    ],
)
def test_each_wrong_answer_fails_with_its_check_s_name(site: tuple[str, Stub], check: str) -> None:
    url, server = site
    server.wrong = check
    with pytest.raises(SmokeError) as failed:
        smoke.run(url, VERSION, tries=1, wait=0)
    assert failed.value.check == check


def test_an_upload_s3_cuts_off_while_it_is_sent_counts_as_refused(site: tuple[str, Stub]) -> None:
    url, server = site
    server.wrong = "close-early"
    report = smoke.run(url, VERSION, tries=1, wait=0)
    assert report[9].startswith("oversized-upload: refused, ")


def test_with_the_form_offline_only_the_console_is_checked_and_the_form_must_stay_off(
    site: tuple[str, Stub],
) -> None:
    url, server = site
    server.form_offline = True
    assert smoke.run(url, VERSION, tries=1, wait=0, form_offline=True) == [
        "console-health: ok",
        "console: ok",
        "console-photo: ok",
        "console-pages: ok",
        "form-offline: ok, status 503",
    ]
    with pytest.raises(SmokeError) as failed:
        smoke.run(url, VERSION, tries=1, wait=0)
    assert failed.value.check == "health"


@pytest.mark.parametrize("check", ["console-health", "console", "form-offline"])
def test_with_the_form_offline_a_wrong_answer_fails_with_its_check_s_name(
    site: tuple[str, Stub], check: str
) -> None:
    url, server = site
    server.form_offline = True
    server.wrong = check
    with pytest.raises(SmokeError) as failed:
        smoke.run(url, VERSION, tries=1, wait=0, form_offline=True)
    assert failed.value.check == check


def test_a_form_that_doesn_t_answer_at_all_counts_as_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url: str, **_: object) -> smoke.Answer:
        raise ConnectionRefusedError

    monkeypatch.setattr(smoke, "request", refuse)
    assert smoke.check_form_offline("https://ceramics.example.org") == "no answer (ConnectionRefusedError)"


def test_main_takes_the_form_offline_flag_and_nothing_else(
    site: tuple[str, Stub], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    url, server = site
    server.form_offline = True
    monkeypatch.setattr(smoke, "HEALTH_TRIES", 1)
    monkeypatch.setattr(smoke, "HEALTH_WAIT_SECONDS", 0.0)
    assert smoke.main([url, VERSION, "--form-offline"]) == 0
    assert "form-offline: ok, status 503" in capsys.readouterr().out
    assert smoke.main([url, VERSION, "--other"]) == 2
    assert smoke.main([url, VERSION, "--form-offline", "x"]) == 2


def test_health_is_retried_until_the_new_version_is_live(site: tuple[str, Stub]) -> None:
    url, server = site
    server.wrong = "health"
    timer = threading.Timer(0.05, lambda: setattr(server, "wrong", ""))
    timer.start()
    assert smoke.run(url, VERSION, tries=5, wait=0.1)[0] == "health: ok"


def test_a_site_that_doesn_t_answer_fails_health() -> None:
    with pytest.raises(SmokeError, match="health: URLError"):
        smoke.run("http://127.0.0.1:9", VERSION, tries=1, wait=0)


def test_main_prints_check_names_and_statuses_never_a_body(
    site: tuple[str, Stub], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    url, server = site
    monkeypatch.setattr(smoke, "HEALTH_TRIES", 1)
    monkeypatch.setattr(smoke, "HEALTH_WAIT_SECONDS", 0.0)
    assert smoke.main([url, VERSION]) == 0
    assert "smoke test passed" in capsys.readouterr().out
    server.wrong = "console"
    assert smoke.main([url, VERSION]) == 1
    error = capsys.readouterr().err
    assert error == "smoke test failed: console: the return address isn't this site's callback\n"
    assert smoke.main([url]) == 2


def test_the_size_limit_is_the_domain_s() -> None:
    from asmbly_ceramics.domain.limits import PHOTO_MAX_BYTES

    assert smoke.PHOTO_MAX_BYTES == PHOTO_MAX_BYTES


def test_only_http_urls_are_requested() -> None:
    with pytest.raises(ValueError, match="http"):
        smoke.request("file:///etc/hostname")


@pytest.mark.parametrize(
    ("location", "detail"),
    [
        ("http://sign-in.example.org/oauth2/authorize?client_id=c", "https address"),
        ("https://sign-in.example.org/login?client_id=c", "/oauth2/authorize"),
        ("https://sign-in.example.org/oauth2/authorize?code_challenge_method=S256", "client_id"),
        ("https://sign-in.example.org/oauth2/authorize?client_id=c&code_challenge_method=plain", "S256"),
    ],
)
def test_a_wrong_sign_in_address_fails_the_console_check(
    monkeypatch: pytest.MonkeyPatch, location: str, detail: str
) -> None:
    from email.message import Message

    headers = Message()
    headers["Location"] = location
    headers["Set-Cookie"] = "__Host-signin=x"
    first = Message()
    first["Location"] = "/console/auth/sign-in?next=%2Fconsole"

    def answer(url: str, **_: object) -> smoke.Answer:
        return smoke.Answer(302, first if url.endswith("/console") else headers, b"")

    monkeypatch.setattr(smoke, "request", answer)
    with pytest.raises(SmokeError, match=detail):
        smoke.check_console("https://ceramics-stage.example.org")


def test_the_console_checks_pass_against_the_real_console_app(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    """The console's checks against the console as built: the fakes, with the real
    sign-in address (`CognitoStaffTokens` builds it without the network)."""
    from dataclasses import replace
    from email.message import Message

    from starlette.testclient import TestClient

    from asmbly_ceramics.adapters.aws.staff_tokens import CognitoStaffTokens
    from asmbly_ceramics.web.app import create_app
    from tests.adapters.aws.test_staff_tokens import CLIENT_ID, ISSUER, ORIGIN
    from tests.web.conftest import SITE
    from tests.web.conftest import VERSION as WEB_VERSION
    from tests.web.console.conftest import console_services, console_settings

    tokens = CognitoStaffTokens(issuer=ISSUER, sign_in_origin=ORIGIN, client_id=CLIENT_ID)
    services = replace(console_services(world), staff_tokens=tokens)
    app = create_app(None, console_settings(world), services)
    with TestClient(app, base_url=SITE) as client:

        def through_client(url: str, **_: object) -> smoke.Answer:
            response = client.get(url.removeprefix(SITE), follow_redirects=False)
            headers = Message()
            for name, value in response.headers.multi_items():
                headers[name] = value
            return smoke.Answer(response.status_code, headers, response.content)

        monkeypatch.setattr(smoke, "request", through_client)
        smoke.check_health(SITE, WEB_VERSION, 1, 0, path="/console/health", check="console-health")
        smoke.check_console(SITE)
        smoke.check_console_photo(SITE)
        smoke.check_console_pages(SITE)
