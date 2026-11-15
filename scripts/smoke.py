"""The smoke test the deploy runs against an environment, with no AWS credentials.

    python3 scripts/smoke.py https://ceramics-stage.asmbly.org abc1234

It stops at the first failed check, printing the check's name and the status it got,
never a body. It never submits a drop-off and never sends an email; its upload slots
count once against the rate limit; the one-byte upload expires with `uploads/`. Standard library only.

1. health: `GET /health` is 200 with `status: ok` and the expected version (retried,
   for the new version to be live).
2. form: `GET /` is 200 with the form's security headers; its device cookie and
   submission token are kept for check 5.
3. console: `GET /console` is 404 (phase 8 makes it a redirect to the staff sign-in).
4. foreign-origin: `POST /drop-off/uploads` from another origin is 403.
5. upload-slot, upload, oversized-upload: two slots are issued; S3 takes a one-byte
   upload to the first (so a refusal below isn't a broken upload) and refuses a photo
   one byte over 10 MB to the second (a 4xx; its S3 error code is printed, or that S3
   closed the connection).
6. private-photos: a kept photo's and an upload's storage addresses, without
   credentials, are 403.
"""

import http.client
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import Message
from urllib.parse import urlsplit

PHOTO_MAX_BYTES = 10 * 1024 * 1024  # domain.limits.PHOTO_MAX_BYTES; the script imports nothing
FOREIGN_ORIGIN = "https://example.org"
TIMEOUT_SECONDS = 30
HEALTH_TRIES = 10  # 6 s apart: a minute for the new version to go live
HEALTH_WAIT_SECONDS = 6.0
_TOKEN = re.compile(r'name="submission" value="([A-Za-z0-9_-]+)"')
_S3_CODE = re.compile(r"<Code>([A-Za-z]{1,64})</Code>")


class SmokeError(Exception):
    def __init__(self, check: str, detail: str) -> None:
        super().__init__(f"{check}: {detail}")
        self.check = check


@dataclass
class Answer:
    status: int
    headers: Message
    body: bytes = field(repr=False)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def request(
    url: str, *, method: str = "GET", headers: Mapping[str, str] | None = None, body: bytes | None = None
) -> Answer:
    if urlsplit(url).scheme not in ("https", "http"):
        raise ValueError("an http(s) URL")
    prepared = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))  # noqa: S310
    try:
        with _OPENER.open(prepared, timeout=TIMEOUT_SECONDS) as response:
            return Answer(response.status, response.headers, response.read())
    except urllib.error.HTTPError as error:
        return Answer(error.code, error.headers, error.read())


def expect(check: str, answer: Answer, status: int) -> None:
    if answer.status != status:
        raise SmokeError(check, f"expected {status}, got {answer.status}")


def check_health(site: str, version: str, tries: int, wait: float) -> None:
    last = "no answer"
    for attempt in range(tries):
        try:
            answer = request(f"{site}/health")
        except OSError as error:
            last = type(error).__name__
        else:
            last = f"status {answer.status}"
            if answer.status == 200:
                try:
                    health = json.loads(answer.body)
                except ValueError:
                    health = {}
                if (
                    isinstance(health, dict)
                    and health.get("status") == "ok"
                    and health.get("version") == version
                ):
                    return
                last = "not the expected version yet"
        if attempt + 1 < tries:
            time.sleep(wait)
    raise SmokeError("health", last)


def check_form(site: str) -> tuple[str, str]:
    """The form's headers; returns its `Cookie` header and its submission token."""
    answer = request(f"{site}/")
    expect("form", answer, 200)
    if not answer.headers.get("Content-Security-Policy", "").startswith("default-src 'none'"):
        raise SmokeError("form", "no Content-Security-Policy starting default-src 'none'")
    if answer.headers.get("X-Content-Type-Options") != "nosniff":
        raise SmokeError("form", "no X-Content-Type-Options: nosniff")
    if answer.headers.get("Cache-Control") != "no-store":
        raise SmokeError("form", "no Cache-Control: no-store")
    cookies = [value.split(";", 1)[0] for value in answer.headers.get_all("Set-Cookie") or []]
    token = _TOKEN.search(answer.body.decode("utf-8", "replace"))
    if not cookies or token is None:
        raise SmokeError("form", "no device cookie or submission token")
    return "; ".join(cookies), token.group(1)


def slots_request(site: str, origin: str, cookie: str, token: str) -> Answer:
    return request(
        f"{site}/drop-off/uploads",
        method="POST",
        headers={"Origin": origin, "Cookie": cookie, "Content-Type": "application/json"},
        body=json.dumps({"count": 2, "submission": token}).encode(),
    )


def multipart(fields: Mapping[str, str], content: bytes) -> tuple[bytes, str]:
    boundary = "smoke" + secrets.token_hex(12)
    parts = []
    for name, value in {**fields, "Content-Type": "image/jpeg"}.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="smoke.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n".encode()
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def check_upload(url: str, fields: Mapping[str, str]) -> None:
    body, content_type = multipart(fields, b"\xff")
    answer = request(url, method="POST", headers={"Content-Type": content_type}, body=body)
    if not 200 <= answer.status < 300:
        code = _S3_CODE.search(answer.body.decode("utf-8", "replace"))
        raise SmokeError(
            "upload", f"expected 2xx, got {answer.status} {code.group(1) if code else ''}".strip()
        )


def check_oversized_upload(url: str, fields: Mapping[str, str]) -> str:
    body, content_type = multipart(fields, b"\0" * (PHOTO_MAX_BYTES + 1))
    try:
        answer = request(url, method="POST", headers={"Content-Type": content_type}, body=body)
    except (ConnectionError, http.client.HTTPException, TimeoutError) as error:
        return f"S3 closed the connection ({type(error).__name__})"
    except urllib.error.URLError as error:  # a reset or timeout while the body was sent
        if isinstance(error.reason, (ConnectionError, TimeoutError)):
            return f"S3 closed the connection ({type(error.reason).__name__})"
        raise SmokeError("oversized-upload", type(error.reason).__name__) from None
    if not 400 <= answer.status < 500:
        raise SmokeError("oversized-upload", f"expected a 4xx, got {answer.status}")
    code = _S3_CODE.search(answer.body.decode("utf-8", "replace"))
    return f"{answer.status} {code.group(1) if code else 'without an S3 code'}"


def run(site: str, version: str, *, tries: int = 10, wait: float = 6.0) -> list[str]:
    site = site.rstrip("/")
    report: list[str] = []
    check_health(site, version, tries, wait)
    report.append("health: ok")
    cookie, token = check_form(site)
    report.append("form: ok")
    expect("console", request(f"{site}/console"), 404)
    report.append("console: ok")
    expect("foreign-origin", slots_request(site, FOREIGN_ORIGIN, cookie, token), 403)
    report.append("foreign-origin: ok")
    answer = slots_request(site, site, cookie, token)
    expect("upload-slot", answer, 200)
    try:
        first, second = json.loads(answer.body)["slots"]
        url, fields = first["url"], dict(first["fields"])
        key = fields["key"]
        oversized_url, oversized_fields = second["url"], dict(second["fields"])
    except ValueError, KeyError, IndexError, TypeError:
        raise SmokeError("upload-slot", "the answer holds no two slots") from None
    report.append("upload-slot: ok")
    check_upload(url, fields)
    report.append("upload: ok")
    report.append(f"oversized-upload: refused, {check_oversized_upload(oversized_url, oversized_fields)}")
    bucket = url.rstrip("/")
    for path in ("dropoffs/AC-1/1.jpg", key):
        expect("private-photos", request(f"{bucket}/{path}"), 403)
    report.append("private-photos: ok")
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: smoke.py <site URL> <version>", file=sys.stderr)
        return 2
    try:
        for line in run(argv[0], argv[1], tries=HEALTH_TRIES, wait=HEALTH_WAIT_SECONDS):
            print(line)
    except SmokeError as failed:
        print(f"smoke test failed: {failed}", file=sys.stderr)
        return 1
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
