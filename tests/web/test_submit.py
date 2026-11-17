"""Submit (#2): each field checked on the server, photos, repeats, the limits, the ID page."""

import html
import logging
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from asmbly_ceramics.adapters.memory.images import NOT_IMAGE, TOO_LARGE, TOO_MANY_PIXELS, UNSUPPORTED_TYPE
from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus
from asmbly_ceramics.domain.errors import DropOffNotTaken, TooManySubmissions
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import ADDRESS_LIMIT, DEVICE_LIMIT, PHOTO_MAX_BYTES, RateLimit
from asmbly_ceramics.domain.photos import PhotoRefusal
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.errors import IdsUnavailable, RecordsUnavailable
from asmbly_ceramics.ports.photos import PhotosAlreadyKept
from asmbly_ceramics.ports.records import Conflict, Submission
from asmbly_ceramics.use_cases.limits import RECEIVED_CAP_KEY
from asmbly_ceramics.web.fields import MESSAGES, PHOTO_MESSAGES, field_messages, message_for
from asmbly_ceramics.web.security import RECEIVED_COOKIE, sign
from tests.domain.builders import TEST_EMAIL, TEST_NAME, TEST_PHONE, TEST_PHONE_DIGITS
from tests.web.conftest import ADDRESS, COOKIE_KEY, PHOTO, SAME_ORIGIN, SITE, Site, set_cap

NAME = MESSAGES["name.required"]
EMAIL = MESSAGES["email.invalid"]
PHONE = MESSAGES["phone.invalid"]
PIECES = MESSAGES["pieces.invalid"]
FIRING = MESSAGES["firing_type.unknown"]
GLAZE = MESSAGES["glaze_type.required"]


def all_drop_offs(site: Site) -> list[DropOff]:
    return site.world.records.drop_offs_in(set(DropOffState))


def message_next_to(page: str, field: str) -> str:
    match = re.search(rf'id="{re.escape(field)}-error">([^<]*)<', page)
    assert match is not None, f"no message next to {field}"
    return html.unescape(match.group(1))


def received_page(site: Site) -> str:
    page = site.client.get("/drop-off/received", follow_redirects=False)
    assert page.status_code == 200
    return page.text


def test_a_valid_drop_off_is_stored_and_redirects_to_its_id(site: Site) -> None:
    answer = site.submit(site.details())
    assert answer.status_code == 303
    assert answer.headers["location"] == "/drop-off/received"
    [drop_off] = all_drop_offs(site)
    assert len(drop_off.photos) == 1
    assert site.world.photos.kept_count(drop_off.id) == 2  # full and thumbnail
    email = site.world.records.email(drop_off.id, EmailKind.RECEIVED)
    assert email is not None
    page = received_page(site)
    assert f'<p class="drop-off-id">{drop_off.id}</p>' in page
    assert "Write this ID and your name on a slip for each piece." in page
    assert "We'll email you a copy with your photos." in page
    assert "Bisque" in page
    assert "<dd>2</dd>" in page


def test_a_glaze_drop_off_names_its_glaze(site: Site) -> None:
    answer = site.submit(site.details(firing_type="glaze", glaze_type="house-dip-glaze"))
    assert answer.status_code == 303
    page = received_page(site)
    assert "House dip glaze" in page
    assert "Glaze" in page


LONG_EMAIL = "a" * 243 + "@" + "example.org"  # 255 characters


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"name": ""}, "name", NAME),
        ({"name": "x" * 101}, "name", MESSAGES["name.too_long"]),
        ({"name": "\x00\x07"}, "name", NAME),  # control characters only
        ({"email": "tester.example.org"}, "email", EMAIL),
        ({"email": LONG_EMAIL}, "email", EMAIL),
        ({"email": "test er" + "@" + "example.org"}, "email", EMAIL),
        ({"phone": "512555"}, "phone", PHONE),
        ({"phone": "1" * 16}, "phone", PHONE),
        ({"phone": "call me"}, "phone", PHONE),
        ({"pieces": "0"}, "pieces", PIECES),
        ({"pieces": "51"}, "pieces", PIECES),
        ({"pieces": "two"}, "pieces", PIECES),
        ({"firing_type": ""}, "firing_type", FIRING),
        ({"firing_type": "raku"}, "firing_type", FIRING),
        ({"firing_type": "glaze"}, "glaze_type", GLAZE),
        ({"glaze_type": "house-dip-glaze"}, "glaze_type", MESSAGES["glaze_type.not_allowed"]),
        ({"firing_type": "glaze", "glaze_type": "porcelain"}, "glaze_type", MESSAGES["glaze_type.unknown"]),
    ],
)
def test_each_missing_or_bad_field_shows_its_message_and_saves_nothing(
    site: Site, overrides: dict[str, str], field: str, message: str
) -> None:
    answer = site.submit(site.details(**overrides))
    assert answer.status_code == 400
    assert message_next_to(answer.text, field) == message
    assert "There is 1 problem with your drop-off." in answer.text
    assert f'href="#{field}"' in answer.text
    assert all_drop_offs(site) == []
    assert site.world.records.emails_in(set(EmailStatus)) == []
    assert site.world.photos.kept_count(DropOffId(1)) == 0


def test_a_retired_firing_or_glaze_type_is_refused(site: Site) -> None:
    site.retire(CatalogList.FIRING_TYPES, "bisque")
    answer = site.submit(site.details())
    assert answer.status_code == 400
    assert message_next_to(answer.text, "firing_type") == FIRING
    site.retire(CatalogList.GLAZE_TYPES, "commercial-glaze")
    answer = site.submit(site.details(firing_type="glaze", glaze_type="commercial-glaze"))
    assert message_next_to(answer.text, "glaze_type") == MESSAGES["glaze_type.unknown"]
    assert all_drop_offs(site) == []


def test_several_problems_are_counted_and_each_shown(site: Site) -> None:
    answer = site.submit(site.details(name="", phone="12"))
    assert "There are 2 problems with your drop-off." in answer.text
    assert message_next_to(answer.text, "name") == NAME
    assert message_next_to(answer.text, "phone") == PHONE


def test_no_photos_and_seven_photos_are_refused(site: Site) -> None:
    none = site.submit(site.details(slot=[]))
    assert none.status_code == 400
    assert "Add 1 to 6 photos." in none.text
    seven = site.submit(
        site.details(slot=list(site.world.uploaded(*[PHOTO] * 6)) + list(site.world.uploaded(PHOTO)))
    )
    assert seven.status_code == 400
    assert "Add 1 to 6 photos." in seven.text
    assert all_drop_offs(site) == []


@pytest.mark.parametrize(
    ("data", "kind"),
    [(NOT_IMAGE, PhotoRefusal.NOT_IMAGE), (UNSUPPORTED_TYPE, PhotoRefusal.UNSUPPORTED_TYPE)],
)
def test_a_file_that_isnt_an_image_is_refused_next_to_the_photo_field(
    site: Site, data: bytes, kind: PhotoRefusal
) -> None:
    slots = site.world.uploaded(PHOTO, data + b"made-up")
    answer = site.submit(site.details(slot=list(slots)))
    assert answer.status_code == 400
    photo_errors = answer.text[answer.text.index('id="photos-error"') :]
    assert html.escape(PHOTO_MESSAGES[kind].format(n=2), quote=False) in photo_errors.replace("&#39;", "'")
    assert all_drop_offs(site) == []


def test_a_photo_over_10_mb_is_refused(site: Site) -> None:
    # S3 refuses the post, so nothing is stored for the slot.
    slots = site.world.uploaded(b"x" * (PHOTO_MAX_BYTES + 1))
    answer = site.submit(site.details(slot=list(slots)))
    assert answer.status_code == 400
    page = html.unescape(answer.text)
    assert PHOTO_MESSAGES[PhotoRefusal.MISSING].format(n=1) in page
    # The inspector's own size check.
    too_large = site.submit(site.details(slot=list(site.world.uploaded(TOO_LARGE + b"made-up"))))
    assert "Photo 1 is over 10 MB." in html.unescape(too_large.text)
    pixels = site.submit(site.details(slot=list(site.world.uploaded(TOO_MANY_PIXELS))))
    assert PHOTO_MESSAGES[PhotoRefusal.TOO_MANY_PIXELS].format(n=1) in html.unescape(pixels.text)
    assert all_drop_offs(site) == []


def test_a_malformed_or_seventh_slot_is_refused_before_any_read(site: Site) -> None:
    bad = site.submit(site.details(slot=["not-a-slot"]))
    assert bad.status_code == 400
    assert "Add 1 to 6 photos." in bad.text
    seven = [f"made-up-slot-id-{n:06d}" for n in range(7)]
    answer = site.submit(site.details(slot=seven))
    assert answer.status_code == 400
    assert site.world.photos.read_uploads == []


def test_refused_photos_are_dropped_and_good_uploads_are_kept_for_the_next_try(site: Site) -> None:
    good, bad = site.world.uploaded(PHOTO, NOT_IMAGE)
    answer = site.submit(site.details(slot=[good, bad, good], name=""))
    assert answer.status_code == 400
    assert f'name="slot" value="{good}"' in answer.text
    assert bad not in answer.text
    assert answer.text.count("A photo you already added") == 1


def test_the_eleventh_drop_off_from_one_device_in_ten_minutes_is_refused(site: Site) -> None:
    for _ in range(DEVICE_LIMIT.limit):
        assert site.submit(site.details()).status_code == 303
    answer = site.submit(site.details())
    assert answer.status_code == 429
    assert TooManySubmissions().message in answer.text
    assert len(all_drop_offs(site)) == DEVICE_LIMIT.limit


def test_the_device_can_drop_off_again_after_ten_minutes(site: Site) -> None:
    for _ in range(DEVICE_LIMIT.limit):
        site.submit(site.details())
    site.world.clock.advance(DEVICE_LIMIT.window + timedelta(seconds=1))
    assert site.submit(site.details()).status_code == 303


def test_the_thirty_first_from_one_address_is_refused_even_with_new_cookies(site: Site) -> None:
    for _ in range(ADDRESS_LIMIT.limit):
        site.client.cookies.clear()
        assert site.submit(site.details()).status_code == 303
    site.client.cookies.clear()
    answer = site.submit(site.details())
    assert answer.status_code == 429
    assert len(all_drop_offs(site)) == ADDRESS_LIMIT.limit


def test_a_drop_off_past_the_daily_cap_shows_the_friendly_refusal(
    site: Site, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    set_cap(site, 1)
    assert site.submit(site.details()).status_code == 303
    site.client.cookies.clear()

    fields = site.details()
    answer = site.submit(fields)

    assert answer.status_code == 429
    shown = html.unescape(re.sub(r"<[^>]+>", " ", answer.text))
    assert DropOffNotTaken().message in shown
    for word in ("cap", "limit", "hash", "too many"):
        assert word not in shown.lower()
    for typed in (TEST_NAME, TEST_EMAIL, TEST_PHONE, html.escape(TEST_EMAIL)):
        assert typed not in answer.text
    assert len(all_drop_offs(site)) == 1
    logged = repr([vars(r) for r in caplog.records])
    secrets = (TEST_NAME, TEST_EMAIL, TEST_PHONE, TEST_PHONE_DIGITS, site.device(), str(fields["submission"]))
    for secret in secrets:
        assert secret not in logged


def test_the_form_says_try_again_when_the_cap_can_t_be_counted(site: Site) -> None:
    counted = site.world.limiter.hit

    def hit(key: str, limit: RateLimit, now: datetime) -> bool:
        if key == RECEIVED_CAP_KEY:
            raise RecordsUnavailable("ThrottlingException")
        return counted(key, limit, now)

    site.world.limiter.hit = hit  # type: ignore[method-assign]
    fields = site.details()

    answer = site.submit(fields)

    assert answer.status_code == 503
    assert "Something went wrong on our side. Please try again." in answer.text
    assert f'name="submission" value="{fields["submission"]}"' in answer.text
    assert all_drop_offs(site) == []


def test_submitting_the_same_page_twice_gives_the_same_id(site: Site) -> None:
    fields = site.details()
    first = site.submit(fields)
    first_page = received_page(site)
    again = site.submit(fields)
    assert first.status_code == again.status_code == 303
    assert again.headers["location"] == "/drop-off/received?again=1"
    [drop_off] = all_drop_offs(site)
    again_page = site.client.get("/drop-off/received?again=1").text
    assert f"already received as {drop_off.id}" in again_page
    assert str(drop_off.id) in first_page


def test_two_page_loads_get_two_ids(site: Site) -> None:
    site.submit(site.details())
    site.submit(site.details())
    ids = {str(drop_off.id) for drop_off in all_drop_offs(site)}
    assert len(ids) == 2


def test_the_received_page_shows_the_id_and_no_contact_details(site: Site) -> None:
    site.submit(site.details())
    page = received_page(site)
    for detail in (TEST_NAME, TEST_EMAIL, TEST_PHONE, "512"):
        assert detail not in page
    assert "<img" not in page


def test_the_received_page_without_its_cookie_goes_back_to_the_form(site: Site) -> None:
    answer = site.client.get("/drop-off/received", follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/"


@pytest.mark.parametrize("cookie", ["tampered", "expired", "garbage", "other-key"])
def test_a_tampered_or_expired_received_cookie_goes_back_to_the_form(site: Site, cookie: str) -> None:
    site.submit(site.details())
    real = site.client.cookies.get(RECEIVED_COOKIE)
    assert real is not None
    token_hash = real.split(".")[0]
    values = {
        "tampered": real[:-1] + ("0" if real[-1] != "0" else "1"),
        "expired": sign(token_hash, site.world.clock.now() - timedelta(days=3650), COOKIE_KEY),
        "garbage": "a.b.c.d",
        "other-key": real.replace(token_hash, "submission#" + "0" * 64),
    }
    site.client.cookies.clear()
    site.client.cookies.set(RECEIVED_COOKIE, values[cookie])
    answer = site.client.get("/drop-off/received", follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/"


def test_the_received_cookie_holds_only_the_submission_hash(site: Site) -> None:
    answer = site.submit(site.details())
    [cookie] = [c for c in answer.headers.get_list("set-cookie") if c.startswith(RECEIVED_COOKIE)]
    parts = {part.strip().lower() for part in cookie.split(";")}
    assert {"secure", "httponly", "samesite=lax", "path=/"} <= parts
    value = site.client.cookies.get(RECEIVED_COOKIE)
    assert value is not None
    assert re.fullmatch(r"submission#[0-9a-f]{64}\.[0-9]+\.[0-9a-f]{64}", value.strip('"'))
    [drop_off] = all_drop_offs(site)
    assert str(drop_off.id) not in value


def test_values_are_kept_and_escaped_when_the_form_is_shown_again(site: Site) -> None:
    script = "<script>alert(1)</script>"
    answer = site.submit(site.details(name=script, email="no-at-sign", pieces="3"))
    assert answer.status_code == 400
    assert script not in answer.text
    assert 'value="&lt;script&gt;alert(1)&lt;/script&gt;"' in answer.text
    assert 'value="no-at-sign"' in answer.text
    assert 'value="3"' in answer.text


def test_an_attribute_breaking_value_is_escaped(site: Site) -> None:
    answer = site.submit(site.details(name='" autofocus onfocus="alert(1)', phone="1"))
    assert 'onfocus="alert(1)"' not in answer.text
    assert "&#34; autofocus onfocus=&#34;alert(1)" in answer.text


def test_an_oversized_body_is_refused(site: Site) -> None:
    fields = site.details(name="x" * (16 * 1024 + 1))
    answer = site.submit(fields)
    assert answer.status_code == 413
    assert all_drop_offs(site) == []


def test_a_body_that_isnt_a_form_is_refused(site: Site) -> None:
    site.form()
    json_body = site.client.post("/drop-off", json={"name": "x"}, headers=SAME_ORIGIN, follow_redirects=False)
    assert json_body.status_code == 400
    bad_utf8 = site.client.post(
        "/drop-off",
        content=b"name=%ff%fe",
        headers={**SAME_ORIGIN, "content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert bad_utf8.status_code == 400
    assert all_drop_offs(site) == []


def test_a_form_without_a_token_or_cookie_is_shown_again_with_a_fresh_token(site: Site) -> None:
    fields = site.details(submission="short")
    answer = site.submit(fields)
    assert answer.status_code == 400
    assert "allow cookies for this site" in answer.text
    assert 'name="submission" value="short"' not in answer.text
    fresh = site.details()
    site.client.cookies.clear()
    no_cookie = site.submit(fresh)
    assert no_cookie.status_code == 400
    assert "allow cookies for this site" in no_cookie.text
    assert all_drop_offs(site) == []


def test_a_failed_commit_shows_the_form_again_with_the_same_token(site: Site) -> None:
    fields = site.details()
    site.world.records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
    answer = site.submit(fields)
    assert answer.status_code == 503
    assert "Something went wrong on our side. Please try again." in answer.text
    assert f'name="submission" value="{fields["submission"]}"' in answer.text
    assert "ThrottlingException" not in answer.text
    # Sending again with the same token stores it once.
    assert site.submit(fields).status_code == 303
    assert len(all_drop_offs(site)) == 1


def test_a_store_that_fails_for_reads_too_still_shows_the_form_with_its_token(site: Site) -> None:
    fields = site.details()
    site.world.studio()  # the form's choices are read before the failure starts
    real_choices = site.world.choices()
    site.world.records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
    original = site.world.records.submission

    def failing_after_first(token_hash: str) -> Submission | None:
        site.world.records.fail_reads_with = RecordsUnavailable("ThrottlingException")
        return original(token_hash)

    site.world.records.submission = failing_after_first  # type: ignore[method-assign]  # a store failing mid-request
    answer = site.submit(fields)
    assert real_choices.firing_types
    assert answer.status_code == 503
    assert f'name="submission" value="{fields["submission"]}"' in answer.text


def test_the_received_cookie_lasts_thirty_minutes(site: Site) -> None:
    site.submit(site.details())
    site.world.clock.advance(timedelta(minutes=29))
    assert site.client.get("/drop-off/received", follow_redirects=False).status_code == 200
    site.world.clock.advance(timedelta(minutes=1))
    assert site.client.get("/drop-off/received", follow_redirects=False).status_code == 303


def test_an_unavailable_id_counter_is_a_503(site: Site) -> None:
    fields = site.details()
    site.world.ids.fail_with = IdsUnavailable("ProvisionedThroughputExceededException")
    answer = site.submit(fields)
    assert answer.status_code == 503
    assert all_drop_offs(site) == []


def test_every_message_key_has_a_message() -> None:
    keys = {
        *[f"{field}.required" for field in ("name", "email", "phone", "firing_type", "glaze_type")],
        "name.too_long",
        "email.invalid",
        "phone.invalid",
        "pieces.invalid",
        "firing_type.unknown",
        "glaze_type.unknown",
        "glaze_type.not_allowed",
        "photos.count",
        "form.expired",
    }
    assert keys == set(MESSAGES)
    assert set(PHOTO_MESSAGES) == set(PhotoRefusal)
    for kind in PhotoRefusal:
        assert message_for(f"photo.{kind}") == PHOTO_MESSAGES[kind]
    assert message_for("nonsense.key") == "Check this and try again."
    shown = field_messages({"photo.2": "photo.not_image", "photo.1": "photo.weird", "name": "name.required"})
    assert shown.photos == (
        "Photo 1: Check this and try again.",
        PHOTO_MESSAGES[PhotoRefusal.NOT_IMAGE].format(n=2),
    )
    assert shown.count == 3


def test_the_domain_raises_only_keys_the_page_knows() -> None:
    """Every message key in the domain's source has a message here."""
    import pathlib

    import asmbly_ceramics.domain.dropoff as dropoff

    source = pathlib.Path(dropoff.__file__).read_text()
    for key in re.findall(r'"([a-z_]+\.[a-z_]+)"', source):
        assert key in MESSAGES, key


def test_another_address_from_the_same_network_header_is_counted_by_its_last_value(site: Site) -> None:
    for _ in range(ADDRESS_LIMIT.limit):
        site.client.cookies.clear()
        spoofed = {"origin": SITE, "x-forwarded-for": f"198.51.100.{_ % 250}, {ADDRESS}"}
        assert site.submit(site.details(), headers=spoofed).status_code == 303
    site.client.cookies.clear()
    assert site.submit(site.details()).status_code == 429


def test_a_received_cookie_with_a_non_ascii_signature_goes_back_to_the_form(site: Site) -> None:
    site.submit(site.details())
    real = site.client.cookies.get(RECEIVED_COOKIE)
    assert real is not None
    forged = (RECEIVED_COOKIE + "=" + real.rsplit(".", 1)[0] + "." + "\u00e9" * 64).encode("latin-1")
    site.client.cookies.clear()
    answer = site.client.get("/drop-off/received", headers={b"cookie": forged}, follow_redirects=False)
    assert answer.status_code == 303


def test_a_streamed_body_over_the_limit_is_refused(site: Site) -> None:
    site.form()

    def chunks() -> Iterator[bytes]:
        yield b"name="
        for _ in range(20):
            yield b"x" * 1024

    answer = site.client.post(
        "/drop-off",
        content=chunks(),
        headers={**SAME_ORIGIN, "content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert answer.status_code == 413
    assert "content-length" not in answer.request.headers
    slots = site.client.post(
        "/drop-off/uploads",
        content=(b"x" * 600 for _ in range(3)),
        headers={**SAME_ORIGIN, "content-type": "application/json"},
    )
    assert slots.status_code == 413
    assert all_drop_offs(site) == []
    assert site.world.photos.slot_count() == 0


def test_a_body_with_too_many_fields_is_refused(site: Site) -> None:
    fields = site.details()
    fields["slot"] = [f"made-up-slot-id-{n:06d}" for n in range(70)]
    answer = site.submit(fields)
    assert answer.status_code == 400
    assert site.world.photos.read_uploads == []
    assert all_drop_offs(site) == []


@pytest.mark.parametrize("error", [Conflict(["AC-9"]), PhotosAlreadyKept(DropOffId(9))])
def test_a_drop_off_that_cant_get_a_number_is_a_503_logged_by_its_class(
    site: Site, error: Exception, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fields = site.details()

    def always(_request: object) -> None:
        raise error

    state = site.client.app.state  # type: ignore[attr-defined]  # the test client's app is Starlette's
    monkeypatch.setattr(state, "services", replace(state.services, submit_drop_off=always))
    with caplog.at_level(logging.INFO):
        answer = site.submit(fields)
    assert answer.status_code == 503
    assert f'name="submission" value="{fields["submission"]}"' in answer.text
    [record] = [r for r in caplog.records if r.getMessage() == "drop_off_unavailable"]
    assert record.__dict__["error_code"] == type(error).__name__


def test_a_signed_cookie_whose_submission_is_gone_goes_back_to_the_form(site: Site) -> None:
    site.client.cookies.set(
        RECEIVED_COOKIE,
        sign("submission#" + "0" * 64, site.world.clock.now() + timedelta(minutes=5), COOKIE_KEY),
    )
    answer = site.client.get("/drop-off/received", follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/"
