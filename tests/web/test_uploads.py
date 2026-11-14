"""Upload slots (#2): counts, the device cookie, the origin, the rate limit, failing closed."""

import logging

import httpx2
import pytest

from asmbly_ceramics.domain.errors import TooManySubmissions
from asmbly_ceramics.domain.limits import SLOT_ADDRESS_LIMIT, SLOT_DEVICE_LIMIT
from asmbly_ceramics.domain.photos import is_slot_id
from asmbly_ceramics.ports.errors import PhotosUnavailable, RecordsUnavailable
from tests.web.conftest import ADDRESS, BUCKET_ORIGIN, SAME_ORIGIN, SITE, Site


def ask(site: Site, body: object, headers: dict[str, str] | None = None) -> httpx2.Response:
    return site.client.post("/drop-off/uploads", json=body, headers=headers or SAME_ORIGIN)


def test_upload_slots_are_issued_for_one_to_six_photos(site: Site) -> None:
    token = site.form()
    for count in (1, 6):
        answer = ask(site, {"count": count, "submission": token})
        assert answer.status_code == 200
        slots = answer.json()["slots"]
        assert len(slots) == count
        assert all(is_slot_id(slot["id"]) for slot in slots)
        assert len({slot["id"] for slot in slots}) == count  # distinct
        assert all(set(slot) == {"id", "url", "fields"} for slot in slots)


@pytest.mark.parametrize(
    "body",
    [
        {"count": 0},
        {"count": 7},
        {"count": "3"},
        {"count": True},
        {"count": False},
        {"count": [2]},
        {"count": None},
        {"count": 2.0},
        {"count": 3, "submission": ""},
        {"count": 3, "submission": "short"},
        [3],
        "3",
    ],
)
def test_bad_requests_get_400(site: Site, body: object) -> None:
    token = site.form()
    if isinstance(body, dict) and "submission" not in body:
        body = {**body, "submission": token}
    answer = ask(site, body)
    assert answer.status_code == 400
    assert answer.json() == {"error": "bad_request"}
    assert site.world.photos.slot_count() == 0


def test_a_missing_token_and_a_body_that_isnt_json_get_400(site: Site) -> None:
    site.form()
    assert ask(site, {"count": 2}).status_code == 400
    not_json = site.client.post(
        "/drop-off/uploads", content=b"{count", headers={**SAME_ORIGIN, "content-type": "application/json"}
    )
    assert not_json.json() == {"error": "bad_request"}
    nested = site.client.post(
        "/drop-off/uploads", content=b"[" * 1000, headers={**SAME_ORIGIN, "content-type": "application/json"}
    )
    assert nested.status_code == 400
    form_body = site.client.post("/drop-off/uploads", data={"count": "2"}, headers=SAME_ORIGIN)
    assert form_body.status_code == 400
    big = site.client.post(
        "/drop-off/uploads",
        content=b'{"count": 1, "pad": "' + b"x" * 2000 + b'"}',
        headers={**SAME_ORIGIN, "content-type": "application/json"},
    )
    assert big.status_code == 413
    assert big.json() == {"error": "bad_request"}
    assert site.world.photos.slot_count() == 0


def test_upload_slots_need_the_device_cookie(site: Site) -> None:
    token = site.form()
    site.client.cookies.clear()
    answer = ask(site, {"count": 2, "submission": token})
    assert answer.status_code == 400
    assert answer.json() == {"error": "expired"}
    assert site.world.photos.slot_count() == 0
    assert site.world.limiter.keys_hit == []


def test_upload_slots_are_rate_limited(site: Site) -> None:
    token = site.form()
    for _ in range(SLOT_DEVICE_LIMIT.limit):
        assert ask(site, {"count": 1, "submission": token}).status_code == 200
    answer = ask(site, {"count": 1, "submission": token})
    assert answer.status_code == 429
    assert answer.json() == {"error": "rate_limited", "message": TooManySubmissions().message}
    assert site.world.photos.slot_count() == SLOT_DEVICE_LIMIT.limit


def test_spoofed_forwarded_for_does_not_change_the_rate_key(site: Site) -> None:
    token = site.form()
    for n in range(SLOT_ADDRESS_LIMIT.limit):
        site.client.cookies.clear()
        site.form()
        spoofed = {"origin": SITE, "x-forwarded-for": f"198.51.100.{n % 250}, {ADDRESS}"}
        assert ask(site, {"count": 1, "submission": token}, spoofed).status_code == 200
    site.client.cookies.clear()
    site.form()
    assert ask(site, {"count": 1, "submission": token}).status_code == 429


def test_a_request_without_forwarded_for_is_refused(site: Site) -> None:
    token = site.form()
    answer = ask(site, {"count": 1, "submission": token}, {"origin": SITE})
    assert answer.status_code == 400
    empty_last = ask(
        site, {"count": 1, "submission": token}, {"origin": SITE, "x-forwarded-for": "198.51.100.1, "}
    )
    assert empty_last.status_code == 400
    assert site.world.photos.slot_count() == 0


def test_upload_slots_fail_closed_when_the_limiter_is_unavailable(site: Site) -> None:
    token = site.form()
    site.world.limiter.fail_with = RecordsUnavailable("ThrottlingException")
    answer = ask(site, {"count": 2, "submission": token})
    assert answer.status_code == 503
    assert answer.json() == {"error": "unavailable"}
    assert site.world.photos.slot_count() == 0


def test_an_unavailable_photo_store_is_a_503_logged_by_its_code(
    site: Site, caplog: pytest.LogCaptureFixture
) -> None:
    token = site.form()
    site.world.photos.fail_with = PhotosUnavailable("SlowDown")
    with caplog.at_level(logging.INFO):
        answer = ask(site, {"count": 2, "submission": token})
    assert answer.status_code == 503
    [record] = [r for r in caplog.records if r.getMessage() == "upload_slots_unavailable"]
    assert record.__dict__["error_code"] == "SlowDown"


def test_a_slot_request_from_another_origin_is_refused(site: Site) -> None:
    token = site.form()
    answer = ask(
        site, {"count": 1, "submission": token}, {"origin": BUCKET_ORIGIN, "x-forwarded-for": ADDRESS}
    )
    assert answer.status_code == 403
    assert answer.json() == {"error": "forbidden"}
    assert site.world.photos.slot_count() == 0


def test_other_methods_get_405(site: Site) -> None:
    wrong = site.client.get("/drop-off/uploads")
    assert wrong.status_code == 405
    assert wrong.json() == {"error": "method_not_allowed"}  # the script reads JSON here
    assert "POST" in wrong.headers["allow"]
    assert site.client.put("/drop-off", headers=SAME_ORIGIN).status_code == 405


def test_the_page_refuses_a_json_true_count_by_itself(site: Site, monkeypatch: pytest.MonkeyPatch) -> None:
    """`true` is a bool in Python, and a bool is an int: the page's own strict check
    refuses it even if the domain's range check were looser."""
    import asmbly_ceramics.web.public

    monkeypatch.setattr(asmbly_ceramics.web.public, "is_photo_count", lambda count: True)
    answer = ask(site, {"count": True, "submission": site.form()})
    assert answer.status_code == 400
    assert answer.json() == {"error": "bad_request"}
    assert site.world.photos.slot_count() == 0
