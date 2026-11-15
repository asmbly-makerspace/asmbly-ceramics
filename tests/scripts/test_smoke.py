"""`scripts/smoke.py` against a local stub of the site and its bucket: each check passes
when the stub answers right, and fails with its own name when the stub answers wrong."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from scripts.smoke import SmokeError

from scripts import smoke

VERSION = "abc1234"
TOKEN = "t" * 32
FORM_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; img-src 'self'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


class Stub(ThreadingHTTPServer):
    wrong: str = ""


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
        if self.path == "/health":
            version = "old0000" if wrong == "health" else VERSION
            self.answer(200, json.dumps({"status": "ok", "version": version}).encode())
        elif self.path == "/":
            headers = dict(FORM_HEADERS)
            if wrong == "form":
                headers["Cache-Control"] = "max-age=60"
            headers["Set-Cookie"] = "__Host-device=d123; Path=/; Secure; HttpOnly"
            self.answer(200, f'<input name="submission" value="{TOKEN}">'.encode(), headers)
        elif self.path == "/console":
            self.answer(200 if wrong == "console" else 404)
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
        "console: ok",
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
        "console",
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
    assert report[6].startswith("oversized-upload: refused, ")


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
    assert error == "smoke test failed: console: expected 404, got 200\n"
    assert smoke.main([url]) == 2


def test_the_size_limit_is_the_domain_s() -> None:
    from asmbly_ceramics.domain.limits import PHOTO_MAX_BYTES

    assert smoke.PHOTO_MAX_BYTES == PHOTO_MAX_BYTES


def test_only_http_urls_are_requested() -> None:
    with pytest.raises(ValueError, match="http"):
        smoke.request("file:///etc/hostname")
