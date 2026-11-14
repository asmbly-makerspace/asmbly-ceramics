"""Headers on every response, the CSP, same-origin checks, no inline script or style,
signed cookies, the health check, and the 500 page."""

import logging
import re
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from starlette.testclient import TestClient

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.web.app import WebSettings, create_app
from asmbly_ceramics.web.errors import PageError
from asmbly_ceramics.web.security import csp, origin_of, sign, verify
from tests.use_cases.conftest import World
from tests.web.conftest import ADDRESS, BUCKET_ORIGIN, COOKIE_KEY, SAME_ORIGIN, SITE, VERSION, Site, services

EXPECTED_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
    f"font-src 'self'; connect-src 'self' {BUCKET_ORIGIN}; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)


def assert_secure(response: httpx2.Response, cache: str = "no-store") -> None:
    assert response.headers["content-security-policy"] == EXPECTED_CSP
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == cache
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["strict-transport-security"] == "max-age=31536000"


class BoomError(Exception):
    pass


def test_every_response_has_the_security_headers(site: Site) -> None:
    assert_secure(site.client.get("/"))
    assert_secure(site.client.get("/health"))
    missing = site.client.get("/no-such-page")
    assert missing.status_code == 404
    assert_secure(missing)
    refused = site.submit(site.details(name=""))
    assert refused.status_code == 400
    assert_secure(refused)
    site.submit(site.details())
    received = site.client.get("/drop-off/received")
    assert received.status_code == 200
    assert_secure(received)
    assert_secure(site.client.get("/drop-off/received", follow_redirects=False))
    assert_secure(site.client.get("/static/app.css"), cache="public, max-age=3600")
    assert_secure(site.client.get("/static/upload.js"), cache="public, max-age=3600")


def test_a_crash_is_a_plain_500_page_with_the_headers(site: Site, caplog: pytest.LogCaptureFixture) -> None:
    site.world.records.fail_reads_with = BoomError("a secret detail from inside")
    with caplog.at_level(logging.INFO):
        page = site.client.get("/")
    assert page.status_code == 500
    assert_secure(page)
    assert "Something went wrong on our side. Please try again." in page.text
    assert "secret detail" not in page.text
    [record] = [r for r in caplog.records if r.getMessage() == "page_crashed"]
    assert record.__dict__["error_code"] == "BoomError"
    assert all("secret detail" not in r.getMessage() for r in caplog.records)


def test_the_csp_allows_only_the_photo_bucket_to_be_contacted(site: Site) -> None:
    policy = site.client.get("/").headers["content-security-policy"]
    directives = dict(part.strip().split(" ", 1) for part in policy.split(";"))
    assert directives["connect-src"] == f"'self' {BUCKET_ORIGIN}"
    assert directives["script-src"] == "'self'"
    assert "unsafe" not in policy
    assert policy.startswith("default-src 'none'")
    assert policy.endswith("form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


@pytest.mark.parametrize("source", ["", "https://a.example.org; script-src *", "a b", "a,b", "a\nb", "a\rb"])
def test_a_csp_source_with_a_separator_is_refused(source: str) -> None:
    with pytest.raises(ValueError, match="separator"):
        csp(source)


def test_a_post_from_another_origin_is_refused(site: Site) -> None:
    fields = site.details()
    other = {"origin": "https://evil.example.org", "x-forwarded-for": ADDRESS}
    answer = site.submit(fields, headers=other)
    assert answer.status_code == 403
    assert "This form can only be sent from the drop-off page." in answer.text
    slots = site.client.post(
        "/drop-off/uploads", json={"count": 1, "submission": fields["submission"]}, headers=other
    )
    assert slots.status_code == 403
    assert site.world.records.drop_offs_in(set(DropOffState)) == []
    assert site.world.photos.slot_count() == 1  # only the one the test uploaded


def test_a_post_without_origin_needs_same_origin_fetch_metadata(site: Site) -> None:
    fields = site.details()
    bare = {"x-forwarded-for": ADDRESS}
    assert site.submit(fields, headers=bare).status_code == 403
    assert site.submit(fields, headers={**bare, "sec-fetch-site": "cross-site"}).status_code == 403
    null_origin = {**bare, "origin": "null"}
    assert site.submit(fields, headers=null_origin).status_code == 403
    assert site.submit(fields, headers={**null_origin, "sec-fetch-site": "same-origin"}).status_code == 303


def test_the_origin_must_match_exactly(site: Site) -> None:
    fields = site.details()
    for origin in ("http://testserver", "https://testserver:8443", "https://testserver.example.org"):
        assert site.submit(fields, headers={"origin": origin, "x-forwarded-for": ADDRESS}).status_code == 403
    assert (
        site.submit(fields, headers={"origin": "HTTPS://TESTSERVER", "x-forwarded-for": ADDRESS}).status_code
        == 303
    )


def test_a_submit_without_forwarded_for_is_refused(site: Site) -> None:
    answer = site.submit(site.details(), headers={"origin": SITE})
    assert answer.status_code == 400
    assert_secure(answer)


INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)


def test_no_page_has_inline_script_or_style(site: Site) -> None:
    pages = [site.client.get("/").text, site.submit(site.details(name="")).text]
    site.submit(site.details())
    pages.append(site.client.get("/drop-off/received").text)
    pages.append(site.client.get("/no-such-page").text)
    for page in pages:
        assert not INLINE_SCRIPT.search(page)
        assert "<style" not in page.lower()
        assert "style=" not in page.lower()
        assert " on" + "click" not in page.lower()


def test_the_health_check_names_the_version(site: Site) -> None:
    answer = site.client.get("/health")
    assert answer.json() == {"status": "ok", "version": VERSION}


def test_signed_values_round_trip_and_expire() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    signed = sign("value", now + timedelta(minutes=30), COOKIE_KEY)
    assert verify(signed, now, COOKIE_KEY) == "value"
    assert verify(signed, now + timedelta(minutes=30), COOKIE_KEY) is None
    assert verify(signed, now, b"other" * 8) is None
    assert verify(None, now, COOKIE_KEY) is None
    assert verify("value.notanumber.mac", now, COOKIE_KEY) is None
    assert verify("value." + "9" * 20 + ".mac", now, COOKIE_KEY) is None
    with pytest.raises(ValueError, match=r"no '\.'"):
        sign("has.dot", now, COOKIE_KEY)


def test_settings_are_checked(world: World) -> None:
    good = {
        "site_url": SITE,
        "photo_upload_origin": BUCKET_ORIGIN,
        "version": VERSION,
        "cookie_key": COOKIE_KEY,
    }
    WebSettings(**good)  # type: ignore[arg-type]  # a dict of mixed values, checked at run time
    for bad in (
        {"site_url": "testserver"},
        {"photo_upload_origin": "a b"},
        {"photo_upload_origin": "*"},
        {"photo_upload_origin": "https:"},
        {"photo_upload_origin": "https://*.s3.us-east-2.amazonaws.com"},
        {"photo_upload_origin": BUCKET_ORIGIN + "/path"},
        {"cookie_key": b"short"},
        {"version": ""},
        {"version": "x\n"},
    ):
        with pytest.raises(ValueError, match=r"origin|CSP|key|version"):
            WebSettings(**{**good, **bad})  # type: ignore[arg-type]  # a dict of mixed values, checked at run time
    assert origin_of("HTTPS://Ceramics.Example.org/path") == "https://ceramics.example.org"
    with pytest.raises(ValueError, match="status"):
        PageError(418)
    assert "cookie_key" not in repr(WebSettings(**good))  # type: ignore[arg-type]  # a dict of mixed values, checked at run time


def test_the_app_builds_more_than_once(world: World) -> None:
    settings = WebSettings(
        site_url=SITE, photo_upload_origin=BUCKET_ORIGIN, version=VERSION, cookie_key=COOKIE_KEY
    )
    for _ in range(2):
        with TestClient(create_app(services(world), settings), base_url=SITE) as client:
            assert client.get("/health").status_code == 200


def test_post_routes_answer_with_same_origin_headers(site: Site) -> None:
    assert site.submit(site.details(), headers=SAME_ORIGIN).status_code == 303


def test_a_static_file_that_isnt_there_isnt_cached(site: Site) -> None:
    missing = site.client.get("/static/nothing.css")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"


def test_refusals_at_the_edge_are_logged_by_kind_only(site: Site, caplog: pytest.LogCaptureFixture) -> None:
    fields = site.details()
    with caplog.at_level(logging.INFO):
        site.submit(fields, headers={"origin": "https://evil.example.org", "x-forwarded-for": ADDRESS})
        site.submit(fields, headers={"origin": SITE})
    outcomes = [r.__dict__["outcome"] for r in caplog.records if r.getMessage() == "page_refused"]
    assert outcomes == ["other_origin", "bad_request"]


def test_a_revalidated_static_file_keeps_its_cache_header(site: Site) -> None:
    first = site.client.get("/static/app.css")
    again = site.client.get("/static/app.css", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "public, max-age=3600"


def test_the_csp_allows_the_host_the_photo_store_presigns_for() -> None:
    """The browser posts each photo to the URL `S3PhotoStore` presigns with the
    composition root's `CLIENT_CONFIG`; `connect-src` must name that URL's origin, in the
    form `WebSettings.photo_upload_origin` documents (the regional virtual-hosted host)."""
    from asmbly_ceramics.adapters.aws.clients import CLIENT_CONFIG
    from asmbly_ceramics.adapters.aws.photos import S3PhotoStore
    from tests.adapters.conftest import a_client

    bucket = origin_of(BUCKET_ORIGIN).removeprefix("https://").split(".s3.")[0]
    [slot] = S3PhotoStore(a_client("s3", CLIENT_CONFIG), bucket).upload_slots(1, datetime.now(UTC))
    presigned_origin = origin_of(slot.post.url)
    assert presigned_origin == BUCKET_ORIGIN
    settings = WebSettings(
        site_url=SITE, photo_upload_origin=presigned_origin, version=VERSION, cookie_key=COOKIE_KEY
    )
    assert f"connect-src 'self' {presigned_origin};" in csp(settings.photo_upload_origin)
