"""Staff sign-in (#3): every console route checks the session and the `ceramics` group,
sign-in and its callback, the fixed return addresses, sign-out and the signed-out page."""

import html
import logging
import re
from urllib.parse import quote

import httpx2
import pytest

from asmbly_ceramics.adapters.memory.staff_tokens import SIGN_IN_ORIGIN, s256
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.ports.errors import SignInUnavailable
from asmbly_ceramics.ports.secrets import SecretName
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.web.console.session import SESSION_COOKIE, SIGNIN_COOKIE, decode_sign_in
from tests.domain.builders import STAFF, TEST_NAME
from tests.use_cases.conftest import World
from tests.use_cases.flows import STAFF_MEMBER
from tests.web.conftest import SITE, Site
from tests.web.console.conftest import OUTSIDER, Console, events, page_csrf, query_of

CALLBACK = f"{SITE}/console/auth/callback"
SIGNED_OUT = f"{SITE}/console/signed-out"
# Every console route but sign-in, its callback and the signed-out page.
GETS = [
    "/console",
    "/console/emails",
    "/console/drop-offs/AC-1",
    "/console/drop-offs/AC-1/photos/1",
    "/console/drop-offs/AC-1/photos/1/thumb",
    "/console/loads",
    "/console/loads/L-1",
    "/console/settings",
    "/console/settings/history",
    "/console/counts",
]
POSTS = [
    "/console/search",
    "/console/drop-offs/AC-1/reject/preview",
    "/console/drop-offs/AC-1/reject",
    "/console/drop-offs/AC-1/undo-reject",
    "/console/drop-offs/AC-1/delete",
    "/console/drop-offs/AC-1/emails/received/retry",
    "/console/loads",
    "/console/loads/L-1/add",
    "/console/loads/L-1/remove",
    "/console/loads/L-1/edit",
    "/console/loads/L-1/start-firing",
    "/console/loads/L-1/fire",
    "/console/loads/L-1/delete",
    "/console/loads/L-1/emails/AC-1/retry",
    "/console/settings/email",
    "/console/settings/test-email",
    "/console/settings/kilns/add",
    "/console/settings/kilns/retire",
    "/console/settings/kilns/restore",
    "/console/settings/kilns/delete",
    "/console/sign-out",
]
PHOTOS = {path for path in GETS if "/photos/" in path}
NOT_ALLOWED = (
    "You don&#39;t have access to the ceramics console. "
    "Ask the Facilities Manager to add you to the ceramics group."
)


def sign_in_cookie(console: Console) -> str:
    value = console.client.cookies.get(SIGNIN_COOKIE)
    assert value is not None
    return value


def start(console: Console, next: str = "/console") -> dict[str, list[str]]:
    """Starts a sign-in; returns the authorize address's query."""
    answer = console.get(f"/console/auth/sign-in?next={quote(next, safe='')}")
    assert answer.status_code == 302
    location = answer.headers["location"]
    assert location.startswith(f"{SIGN_IN_ORIGIN}/oauth2/authorize?")
    return query_of(location)


def finish(
    console: Console, token: str, *, code: str = "made-up-code", state: str | None = None
) -> httpx2.Response:
    console.tokens.approve(code, token)
    query = {"code": code, "state": state if state is not None else started_state(console)}
    return console.client.get("/console/auth/callback", params=query, follow_redirects=False)


def started_state(console: Console) -> str:
    sign_in = decode_sign_in(
        sign_in_cookie(console), console.world.secrets.get(SecretName.SESSION_KEY), console.world.clock.now()
    )
    assert sign_in is not None
    return sign_in.state


# --- the per-request check ----------------------------------------------------------------


def test_a_console_page_without_a_session_redirects_to_sign_in_with_next(console: Console) -> None:
    answer = console.get("/console/drop-offs/AC-1?reject=1")
    assert answer.status_code == 302
    assert answer.headers["location"] == "/console/auth/sign-in?next=" + quote(
        "/console/drop-offs/AC-1?reject=1", safe=""
    )


@pytest.mark.parametrize("path", sorted(set(GETS) - PHOTOS))
def test_every_console_page_without_a_session_redirects_to_sign_in(console: Console, path: str) -> None:
    answer = console.get(path)
    assert answer.status_code == 302
    assert query_of(answer.headers["location"])["next"] == [path]


@pytest.mark.parametrize("path", sorted(PHOTOS))
def test_a_photo_without_a_session_is_401_and_starts_no_sign_in(console: Console, path: str) -> None:
    console.drop_off(1)
    answer = console.get(path)
    assert answer.status_code == 401
    assert "Sign in to the console to see this photo." in answer.text
    assert answer.headers["content-type"].startswith("text/html")
    assert SIGNIN_COOKIE not in answer.headers.get("set-cookie", "")


@pytest.mark.parametrize("path", [p for p in POSTS if p != "/console/sign-out"])
def test_every_console_post_without_a_session_says_to_sign_in_without_a_redirect(
    console: Console, path: str
) -> None:
    # A form's redirect on to the staff sign-in would be blocked by `form-action 'self'`.
    answer = console.post(path, {"q": "x"}, csrf=False)
    assert answer.status_code == 401
    assert "location" not in answer.headers
    assert "Your sign-in has ended, so that wasn&#39;t saved. Sign in and try again." in answer.text
    assert 'href="/console/auth/sign-in"' in answer.text


@pytest.mark.parametrize(
    ("method", "path"), [("GET", p) for p in GETS] + [("POST", p) for p in POSTS if p != "/console/sign-out"]
)
def test_every_console_route_is_not_allowed_outside_the_group(
    console: Console, method: str, path: str
) -> None:
    console.drop_off(1)
    console.sign_in(groups=("front-desk",), username=OUTSIDER)
    answer = console.get(path) if method == "GET" else console.post(path, {"q": "x"})
    assert answer.status_code == 403
    assert NOT_ALLOWED in answer.text
    assert TEST_NAME not in answer.text  # no drop-off shown


def test_an_unknown_token_clears_the_cookie_and_redirects(
    console: Console, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    console.client.cookies.set(SESSION_COOKIE, "made-up-expired-token")
    answer = console.get("/console")
    assert answer.status_code == 302
    assert (
        f'{SESSION_COOKIE}=""' in answer.headers["set-cookie"] or "Max-Age=0" in answer.headers["set-cookie"]
    )
    assert events(caplog) == [("auth_rejected", None)]
    assert "made-up-expired-token" not in caplog.text


def test_a_token_far_too_long_is_no_session(console: Console) -> None:
    console.client.cookies.set(SESSION_COOKIE, "x" * 5000)
    assert console.get("/console").status_code == 302


def test_a_token_without_groups_is_not_allowed(console: Console, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    console.sign_in(groups=(), username=OUTSIDER)
    answer = console.get("/console")
    assert answer.status_code == 403
    assert events(caplog) == [("not_allowed", OUTSIDER)]


def test_not_allowed_names_the_facilities_manager_and_links_to_the_form(console: Console) -> None:
    token = console.sign_in(groups=("front-desk",), username=OUTSIDER)
    answer = console.get("/console")
    assert NOT_ALLOWED in answer.text
    assert 'href="/"' in answer.text
    assert 'action="/console/sign-out"' in answer.text
    assert page_csrf(answer.text) == console.csrf()
    assert token not in answer.text


def test_unavailable_signing_keys_answer_503(console: Console, caplog: pytest.LogCaptureFixture) -> None:
    console.sign_in()
    console.tokens.fail_with = SignInUnavailable("jwks_unreachable")
    answer = console.get("/console")
    assert answer.status_code == 503
    assert "The staff sign-in can&#39;t be checked right now. Try again in a minute." in answer.text
    [record] = [r for r in caplog.records if r.message == "jwks_unavailable"]
    assert record.levelno == logging.ERROR


def test_every_console_response_carries_the_security_headers(console: Console) -> None:
    for answer in (
        console.get("/console"),
        console.get("/console/signed-out"),
        console.get("/console/drop-offs/AC-1/photos/1"),
    ):
        assert answer.headers["content-security-policy"].startswith("default-src 'none'")
        assert "form-action 'self'" in answer.headers["content-security-policy"]
        assert answer.headers["x-content-type-options"] == "nosniff"
        assert answer.headers["cache-control"] == "no-store"
        assert answer.headers["referrer-policy"] == "same-origin"


# --- sign-in and its callback -----------------------------------------------------------------


def test_sign_in_sets_a_signed_state_cookie_and_redirects_to_the_authorize_endpoint(console: Console) -> None:
    query = start(console, "/console/emails")
    answer_cookie = sign_in_cookie(console)
    sign_in = decode_sign_in(
        answer_cookie, console.world.secrets.get(SecretName.SESSION_KEY), console.world.clock.now()
    )
    assert sign_in is not None
    assert sign_in.next == "/console/emails"
    assert query["redirect_uri"] == [CALLBACK]
    assert query["state"] == [sign_in.state]
    assert query["code_challenge"] == [s256(sign_in.verifier)]


def test_the_sign_in_cookie_is_host_only_secure_http_only_and_lax(console: Console) -> None:
    answer = console.get("/console/auth/sign-in")
    cookie = answer.headers["set-cookie"]
    assert cookie.startswith(f"{SIGNIN_COOKIE}=")
    for part in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=600"):
        assert part.lower() in cookie.lower(), part
    assert "domain=" not in cookie.lower()


def test_the_return_addresses_are_fixed_whatever_the_request_says(console: Console) -> None:
    answer = console.client.get(
        "/console/auth/sign-in?next=%2Fconsole",
        headers={"host": "evil.example", "x-forwarded-host": "evil.example"},
        follow_redirects=False,
    )
    assert query_of(answer.headers["location"])["redirect_uri"] == [CALLBACK]
    console.sign_in()
    signed_out = console.post(
        "/console/sign-out", headers={"origin": SITE, "x-forwarded-host": "evil.example"}
    )
    assert query_of(logout_url(signed_out.text))["redirect_uri"] == [SIGNED_OUT]


def logout_url(page: str) -> str:
    """The staff sign-out address the signing-out page goes on to."""
    match = re.search(r'<a class="button" href="([^"]+)">Continue</a>', page)
    assert match is not None
    return html.unescape(match.group(1))


def test_callback_for_a_group_member_sets_the_session_and_returns_to_next(
    console: Console, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    console.tokens.members["made-up-new-token"] = StaffMember(STAFF, None)
    start(console, "/console/emails")
    answer = finish(console, "made-up-new-token")
    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/emails"
    cookies = answer.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    assert session.startswith(f"{SESSION_COOKIE}=made-up-new-token")
    for part in ("httponly", "secure", "samesite=lax", "path=/", "max-age=3600"):
        assert part in session.lower(), part
    assert any(c.startswith(f"{SIGNIN_COOKIE}=") and "max-age=0" in c.lower() for c in cookies)
    assert ("signed_in", STAFF) in events(caplog)
    assert "made-up-new-token" not in caplog.text
    assert console.get("/console").status_code == 200


def test_callback_with_a_wrong_state_is_refused_and_sets_no_session(console: Console) -> None:
    console.tokens.outsiders.clear()
    start(console)
    answer = finish(console, "made-up-any", state="made-up-wrong-state")
    assert answer.status_code == 400
    assert "Sign-in didn&#39;t finish. Try again." in answer.text
    assert f"{SESSION_COOKIE}=" not in answer.headers.get("set-cookie", "")


@pytest.mark.parametrize("damage", ["missing", "tampered", "old"])
def test_callback_with_an_old_or_tampered_signin_cookie_is_refused(console: Console, damage: str) -> None:
    from datetime import timedelta

    start(console)
    state = started_state(console)
    if damage == "missing":
        console.client.cookies.delete(SIGNIN_COOKIE)
    elif damage == "tampered":
        value = sign_in_cookie(console)
        console.client.cookies.set(SIGNIN_COOKIE, value[:-1] + ("0" if value[-1] != "0" else "1"))
    else:
        console.world.clock.advance(timedelta(minutes=10))
    answer = finish(console, "made-up-any", state=state)
    assert answer.status_code == 400
    assert f"{SESSION_COOKIE}=" not in answer.headers.get("set-cookie", "")


def test_an_error_from_the_sign_in_is_refused(console: Console) -> None:
    start(console)
    answer = console.client.get(
        "/console/auth/callback",
        params={"error": "access_denied", "state": started_state(console)},
        follow_redirects=False,
    )
    assert answer.status_code == 400


def test_a_code_the_sign_in_refuses_is_refused(console: Console) -> None:
    start(console)
    answer = console.client.get(
        "/console/auth/callback",
        params={"code": "made-up-unknown", "state": started_state(console)},
        follow_redirects=False,
    )
    assert answer.status_code == 400


def test_callback_for_someone_outside_the_group_shows_not_allowed_and_sets_no_session(
    console: Console,
) -> None:
    console.tokens.outsiders["made-up-outsider-token"] = OUTSIDER
    start(console)
    answer = finish(console, "made-up-outsider-token")
    assert answer.status_code == 403
    assert NOT_ALLOWED in answer.text
    assert f"{SESSION_COOKIE}=" not in answer.headers.get("set-cookie", "")
    assert f'href="{SIGN_IN_ORIGIN}/logout?' in answer.text  # no session: a plain link to the staff sign-out


def test_a_sign_in_that_can_t_reach_the_pool_is_503(console: Console) -> None:
    start(console)
    state = started_state(console)
    console.tokens.approve("made-up-code", "made-up-token")
    console.tokens.fail_with = SignInUnavailable("timeout")
    answer = console.client.get(
        "/console/auth/callback", params={"code": "made-up-code", "state": state}, follow_redirects=False
    )
    assert answer.status_code == 503
    assert f"{SESSION_COOKIE}=" not in answer.headers.get("set-cookie", "")


@pytest.mark.parametrize(
    "next",
    [
        "//evil.example",
        "https://evil.example",
        "/\\evil",
        "javascript:x",
        "/form",
        "/consolex",
        "/console//evil",
    ],
)
def test_next_pointing_off_site_is_replaced_by_the_console(console: Console, next: str) -> None:
    start(console, next)
    sign_in = decode_sign_in(
        sign_in_cookie(console), console.world.secrets.get(SecretName.SESSION_KEY), console.world.clock.now()
    )
    assert sign_in is not None
    assert sign_in.next == "/console"


# --- sign-out --------------------------------------------------------------------------------


def test_sign_out_clears_the_session_and_goes_to_the_staff_logout(
    console: Console, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    console.sign_in()
    answer = console.post("/console/sign-out")
    assert answer.status_code == 200
    assert "location" not in answer.headers  # no form redirect off-site (`form-action 'self'`)
    location = logout_url(answer.text)
    assert location.startswith(f"{SIGN_IN_ORIGIN}/logout?")
    assert query_of(location)["redirect_uri"] == [SIGNED_OUT]
    assert f'<meta http-equiv="refresh" content="0; url={html.escape(location)}">' in answer.text
    assert "max-age=0" in answer.headers["set-cookie"].lower()
    assert ("signed_out", STAFF) in events(caplog)


@pytest.mark.parametrize("groups", [("ceramics",), ("front-desk",)])
def test_sign_out_without_the_csrf_token_is_refused(console: Console, groups: tuple[str, ...]) -> None:
    console.sign_in(groups=groups, username=STAFF if groups == ("ceramics",) else OUTSIDER)
    assert console.post("/console/sign-out", {"other": "1"}, csrf=False).status_code == 403
    assert console.post("/console/sign-out", {"csrf": "made-up-wrong"}).status_code == 403
    assert console.post("/console/sign-out", headers={"origin": "https://evil.example"}).status_code == 403
    assert console.post("/console/sign-out").status_code == 200  # with it, it works, from not-allowed too


def test_sign_out_with_a_stale_session_only_clears_it(console: Console) -> None:
    console.client.cookies.set(SESSION_COOKIE, "made-up-stale-token")
    answer = console.post("/console/sign-out", csrf=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/signed-out"


def test_sign_out_with_no_session_cookie_goes_to_signed_out(console: Console) -> None:
    # The normal state once the session cookie's hour has lapsed: already signed out.
    answer = console.post("/console/sign-out", csrf=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/console/signed-out"
    assert "wasn&#39;t saved" not in answer.text


def test_the_signed_out_page_is_public_and_shows_nothing_personal(console: Console) -> None:
    console.drop_off(1)
    answer = console.get("/console/signed-out")
    assert answer.status_code == 200
    assert "You're signed out of the ceramics console." in answer.text
    assert 'href="/console/auth/sign-in"' in answer.text
    assert 'href="/"' in answer.text
    assert TEST_NAME not in answer.text


def test_the_form_s_app_serves_no_console(site: Site) -> None:
    assert site.client.get("/console", follow_redirects=False).status_code == 404
    assert site.client.get("/console/auth/sign-in", follow_redirects=False).status_code == 404


PUBLIC = {"/console/auth/sign-in", "/console/auth/callback", "/console/signed-out"}


def test_every_console_route_is_in_the_checked_lists() -> None:
    """A route added later (phase 9) without its own row here fails, so the session and
    group tests above always cover every console path."""
    from starlette.routing import Route

    from asmbly_ceramics.web.console import console_routes

    checked = {p.replace("AC-1", "{id}").replace("/photos/1", "/photos/{k}") for p in GETS + POSTS}
    checked = {p.replace("/emails/received/", "/emails/{kind}/") for p in checked}
    checked = {
        p.replace("L-1/emails/{id}/", "L-1/emails/{drop_off}/").replace("L-1", "{load}") for p in checked
    }
    checked = {p.replace("/settings/kilns/", "/settings/{list}/") for p in checked}
    for route in console_routes():
        assert isinstance(route, Route)
        assert route.path in checked | PUBLIC, route.path


@pytest.mark.parametrize("path", POSTS)
def test_no_console_post_redirects_to_another_site(console: Console, path: str) -> None:
    """Browsers check `form-action 'self'` on a form's redirects too."""
    console.drop_off(1)
    for signed in (False, True):
        if signed:
            console.sign_in()
        answer = console.post(
            path, {"q": "x", "occasion": "", "version": "1", "reason": "other"}, csrf=signed
        )
        location = answer.headers.get("location", "")
        assert not location or location.startswith("/"), (path, location)


def test_changing_the_session_key_signs_everyone_out(console: Console) -> None:
    from asmbly_ceramics.ports.secrets import SecretName

    console.sign_in()
    assert console.get("/console").status_code == 200
    console.world.secrets.set(SecretName.SESSION_KEY, b"a-new-made-up-session-key-0123456789")
    answer = console.get("/console")
    assert answer.status_code == 302
    assert "max-age=0" in answer.headers["set-cookie"].lower()


def test_a_tampered_session_seal_is_no_session(console: Console) -> None:
    token = console.sign_in()
    console.client.cookies.set(SESSION_COOKIE, token + ".0000")
    assert console.get("/console").status_code == 302


def test_a_failed_callback_while_signed_in_goes_to_the_console(console: Console) -> None:
    console.sign_in()
    answer = console.client.get(
        "/console/auth/callback", params={"code": "x", "state": "y"}, follow_redirects=False
    )
    assert answer.status_code == 303
    assert answer.headers["location"] == "/console"


def test_sign_out_clears_the_session_even_when_the_keys_can_t_be_fetched(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    console.sign_in()
    csrf = console.csrf()

    def keys_down(token: str) -> StaffMember:
        raise SignInUnavailable("jwks_unreachable")

    monkeypatch.setattr(console.tokens, "verify", keys_down)  # building the address needs no keys
    answer = console.post("/console/sign-out", {"csrf": csrf})
    assert answer.status_code == 200
    assert "max-age=0" in answer.headers["set-cookie"].lower()
    assert console.post("/console/sign-out", {"csrf": "made-up-wrong"}).status_code in (303, 403)


def test_a_token_too_long_for_a_cookie_doesn_t_loop(console: Console) -> None:
    long_token = "made-up-" + "x" * 4200
    console.tokens.members[long_token] = StaffMember(STAFF, None)
    start(console)
    answer = finish(console, long_token)
    assert answer.status_code == 400
    assert f"{SESSION_COOKIE}=" not in answer.headers.get("set-cookie", "")


def test_the_sign_out_page_goes_to_the_real_staff_logout(world: World) -> None:
    """Through the real adapter: `client_id` and `logout_uri`, not the fake's names."""
    from dataclasses import replace

    from starlette.testclient import TestClient

    from asmbly_ceramics.adapters.aws.staff_tokens import CognitoStaffTokens
    from asmbly_ceramics.web.app import create_app
    from tests.adapters.aws.test_staff_tokens import CLIENT_ID, ISSUER, ORIGIN
    from tests.web.console.conftest import console_services, console_settings

    tokens = CognitoStaffTokens(issuer=ISSUER, sign_in_origin=ORIGIN, client_id=CLIENT_ID)
    services = replace(console_services(world), staff_tokens=tokens)
    with TestClient(create_app(None, console_settings(world), services), base_url=SITE) as client:
        console = Console(client, world)
        token = console.sign_in()
        member = world.staff_tokens.members[token]
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(tokens, "verify", lambda t: member)  # the fake's made-up token
            answer = console.post("/console/sign-out")
    location = logout_url(answer.text)
    assert location.startswith(f"{ORIGIN}/logout?")
    assert query_of(location) == {"client_id": [CLIENT_ID], "logout_uri": [SIGNED_OUT]}


@pytest.mark.parametrize("path", [p for p in POSTS if p != "/console/sign-out"])
def test_every_console_post_needs_this_session_s_csrf_token_and_this_origin(
    console: Console, path: str
) -> None:
    console.drop_off(1)
    console.sign_in()
    console.world.start_load(ItemId("athena"), ItemId("bisque"), None, STAFF_MEMBER)  # L-1
    fields = {"q": "x", "version": "1", "drop_off": "AC-1", "item": "helios", "name": "Hestia"}
    commits = len(console.world.records.commits)

    without = console.post(path, fields, csrf=False)
    other_site = console.post(path, fields, headers={"origin": "https://evil.example"})

    assert without.status_code == 403
    assert other_site.status_code == 403
    assert len(console.world.records.commits) == commits
    assert console.world.mailer.sent == []
