"""The form page (#2): what it offers, the device cookie, a token per load."""

import re

from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.web.security import DEVICE_COOKIE, DEVICE_COOKIE_MAX_AGE
from tests.domain.builders import STAFF
from tests.web.conftest import Site


def test_the_form_lists_the_active_firing_and_glaze_types(site: Site) -> None:
    site.retire(CatalogList.GLAZE_TYPES, "commercial-glaze")
    page = site.client.get("/").text
    assert 'value="bisque"' in page
    assert ">Bisque<" in page
    assert 'value="glaze"' in page
    assert 'data-needs-glaze="true"' in page
    assert ">House dip glaze<" in page
    assert "Commercial glaze" not in page
    assert STAFF not in page


def test_the_form_s_body_has_no_console_class(site: Site) -> None:
    """The console's styles hang on <body class="console">; the public form never gets it."""
    page = site.client.get("/").text
    assert "<body>" in page
    assert 'class="console"' not in page


def test_the_form_sets_a_device_cookie_once(site: Site) -> None:
    first = site.client.get("/")
    [cookie] = first.headers.get_list("set-cookie")
    assert cookie.startswith(DEVICE_COOKIE + "=")
    parts = {part.strip().lower() for part in cookie.split(";")}
    assert {"secure", "httponly", "samesite=lax", "path=/", f"max-age={DEVICE_COOKIE_MAX_AGE}"} <= parts
    value = cookie.split(";")[0].split("=", 1)[1]
    assert len(value) == 43  # 32 random bytes
    second = site.client.get("/")
    assert second.headers.get_list("set-cookie") == []


def test_a_malformed_device_cookie_is_replaced(site: Site) -> None:
    site.client.cookies.set(DEVICE_COOKIE, "short")
    page = site.client.get("/")
    assert any(cookie.startswith(DEVICE_COOKIE + "=") for cookie in page.headers.get_list("set-cookie"))


def test_each_page_load_has_a_new_submission_token(site: Site) -> None:
    tokens = {site.form() for _ in range(3)}
    assert len(tokens) == 3
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{32}", token) for token in tokens)


def test_the_photo_field_accepts_only_jpeg_png_and_webp_and_doesnt_force_the_camera(site: Site) -> None:
    page = site.client.get("/").text
    [photo_input] = re.findall(r'<input id="photos"[^>]*>', page)
    assert 'accept="image/jpeg,image/png,image/webp"' in photo_input
    assert "multiple" in photo_input
    assert "capture" not in page
    assert "name=" not in photo_input  # only the slots post, never a file or its name


def test_the_form_says_it_needs_javascript_for_photos(site: Site) -> None:
    page = site.client.get("/").text
    noscript = page[page.index("<noscript>") : page.index("</noscript>")]
    assert "This form needs JavaScript to upload photos." in noscript


def test_the_fields_have_labels_and_phone_keyboards(site: Site) -> None:
    page = site.client.get("/").text
    for name in ("name", "email", "phone", "pieces"):
        assert f'<label for="{name}">' in page
    assert 'type="email"' in page
    assert 'autocomplete="email"' in page
    assert 'inputmode="email"' in page
    assert 'type="tel"' in page
    assert 'autocomplete="tel"' in page
    assert 'inputmode="numeric" min="1" max="50"' in page
    assert 'autocomplete="name" maxlength="100"' in page
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in page


def test_the_page_shows_the_logo_and_the_ceramics_band(site: Site) -> None:
    page = site.client.get("/").text
    assert 'aria-label="Asmbly Makerspace"' in page
    assert 'class="ceramics-band"' in page
    assert "<h1>Drop off for firing</h1>" in page
    assert page.count("<h1>") == 1


def test_the_form_answers_503_when_the_studio_cant_be_read(site: Site, caplog: object) -> None:
    from asmbly_ceramics.ports.errors import RecordsUnavailable

    site.world.records.fail_reads_with = RecordsUnavailable("ThrottlingException")
    page = site.client.get("/")
    assert page.status_code == 503
    assert "Something went wrong on our side. Please try again." in page.text
    assert "ThrottlingException" not in page.text


def test_no_form_control_shadows_the_forms_submit_method(site: Site) -> None:
    """A control named or with the id `submit` replaces `form.submit` in the browser."""
    page = site.client.get("/").text
    assert not re.search(r'\b(id|name)="submit"', page)


def test_the_script_reads_its_limits_and_messages_from_the_page(site: Site) -> None:
    from pathlib import Path

    import asmbly_ceramics.web
    from asmbly_ceramics.domain.limits import PHOTO_MAX_BYTES, PHOTOS_MAX

    page = site.client.get("/").text
    assert f'data-photos-max="{PHOTOS_MAX}"' in page
    assert 'data-photos-min="1"' in page
    assert f'data-photo-max-bytes="{PHOTO_MAX_BYTES}"' in page
    assert 'data-message-count="Add 1 to 6 photos."' in page
    script = (Path(asmbly_ceramics.web.__file__).parent / "static" / "upload.js").read_text()
    numbers = re.findall(r"(?<![\w.])\d+(?![\w.])", script)
    # indexes, AT_ONCE, parseInt's radix, HTTP statuses and the decision's number only
    assert set(numbers) <= {"0", "1", "2", "10", "200", "429", "0002"}, numbers
    assert "total < 1" not in script
    assert "MB" not in script


def test_the_script_locks_the_photo_list_while_it_uploads() -> None:
    """A photo removed or added mid-upload would leave the slots out of step with the
    list: the picker and every Remove are disabled while uploading, and the uploads and
    the submit use the list as it was when Send was pressed."""
    from pathlib import Path

    import asmbly_ceramics.web

    script = (Path(asmbly_ceramics.web.__file__).parent / "static" / "upload.js").read_text()
    assert "picker.disabled = value;" in script
    assert (
        'list.querySelectorAll(".remove").forEach(function (button) { button.disabled = value; });' in script
    )
    assert "var sending = chosen.slice();" in script
    assert "chosen[i]" not in script
    assert "setBusy(true);" in script
    assert script.count("if (busy) {") >= 4  # submit, picker, a chosen photo's and a kept photo's Remove
