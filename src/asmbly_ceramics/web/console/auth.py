"""Staff sign-in (#3): the per-request check, sign-in, its callback, sign-out and the
signed-out page.

Every console page goes through `require_staff` (a GET) or `require_staff_post` (a POST)
before anything else. Someone not signed in goes to the staff sign-in and back; someone
signed in but outside `ceramics` sees "not allowed"; a key-fetch outage is a 503. The
staff sign-in returns only to the two fixed addresses built from `site_url`, never from
the request. Logs carry the staff username and fixed words, never a token, a code, the
state or a cookie.
"""

import hmac
import logging
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from asmbly_ceramics.ports.errors import SignInUnavailable
from asmbly_ceramics.ports.staff import NotAllowed, NotSignedIn, StaffMember
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.web.console.common import (
    FORM_FIELDS_MAX,
    Answer,
    PostedForm,
    Staff,
    read_form,
    services,
    session_key,
    templates,
)
from asmbly_ceramics.web.console.csrf import CSRF_FIELD, check_csrf, check_origin, csrf_token
from asmbly_ceramics.web.console.session import (
    CONSOLE_HOME,
    SIGNIN_COOKIE,
    TOKEN_MAX_LENGTH,
    clear_session,
    clear_sign_in,
    code_challenge,
    decode_sign_in,
    encode_sign_in,
    has_session_cookie,
    new_sign_in,
    safe_next,
    seal_session,
    session_token,
    set_session,
    set_sign_in,
)

SIGN_IN = "/console/auth/sign-in"
NOT_ALLOWED = (
    "You don't have access to the ceramics console. "
    "Ask the Facilities Manager to add you to the ceramics group."
)
SIGN_IN_UNAVAILABLE = "The staff sign-in can't be checked right now. Try again in a minute."
SIGN_IN_FAILED = "Sign-in didn't finish. Try again."
PHOTO_NEEDS_SIGN_IN = "Sign in to the console to see this photo."
SESSION_ENDED = "Your sign-in has ended, so that wasn't saved. Sign in and try again."
CODE_MAX_LENGTH = 2048


def _sign_in_redirect(request: Request) -> Response:
    """A GET is sent to the sign-in and returns here after it. A POST answers the 401
    "Sign in" page instead of a redirect: the console's `form-action 'self'` is checked
    by browsers on every redirect of a form submission, so a POST redirected on to the
    staff sign-in would be blocked. Its data isn't kept."""
    if request.method in ("GET", "HEAD"):
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"{SIGN_IN}?next={quote(safe_next(target), safe='')}", status_code=302)
    return _message(request, 401, SESSION_ENDED, sign_in_link=True)


def _message(request: Request, status: int, message: str, *, sign_in_link: bool = False) -> Response:
    return templates(request).TemplateResponse(
        request,
        "console/message.html",
        {"message": message, "sign_in_link": sign_in_link},
        status_code=status,
    )


def _not_allowed(request: Request, *, csrf: str | None, logout_url: str | None) -> Response:
    """The 403 page: "Sign in as someone else" posts to sign-out with this session's CSRF
    token, or, reached from the callback with no session, links to the staff sign-out."""
    return templates(request).TemplateResponse(
        request,
        "console/not_allowed.html",
        {"message": NOT_ALLOWED, "csrf": csrf, "logout_url": logout_url},
        status_code=403,
    )


def _unavailable(request: Request, event: str = "jwks_unavailable") -> Response:
    """`jwks_unavailable` when a token can't be checked (the pool's keys), or
    `sign_in_unavailable` when the callback can't reach the token endpoint; at ERROR, for
    the logged-errors alarm."""
    log_event(event, level=logging.ERROR)
    return _message(request, 503, SIGN_IN_UNAVAILABLE)


def _signed_out_again(request: Request) -> Response:
    log_event("auth_rejected")
    response = _sign_in_redirect(request)
    clear_session(response)
    return response


def require_staff(request: Request) -> Staff:
    """The signed-in member of `ceramics`, or an `Answer`: the sign-in redirect (no
    session, or a token that doesn't verify: the cookie is cleared), the not-allowed page,
    or a 503 when the pool's keys can't be fetched."""
    if not has_session_cookie(request):
        raise Answer(_sign_in_redirect(request))
    console = services(request)
    token = session_token(request, session_key(request))
    if token is None:  # not sealed with this environment's key
        raise Answer(_signed_out_again(request))
    try:
        member = console.staff_tokens.verify(token)
    except NotSignedIn:
        raise Answer(_signed_out_again(request)) from None
    except NotAllowed as refused:
        log_event("not_allowed", user=refused.username)
        raise Answer(
            _not_allowed(request, csrf=csrf_token(token, session_key(request)), logout_url=None)
        ) from None
    except SignInUnavailable:
        raise Answer(_unavailable(request)) from None
    return Staff(member=member, token=token, csrf=csrf_token(token, session_key(request)))


async def require_staff_post(
    request: Request, *, max_fields: int = FORM_FIELDS_MAX
) -> tuple[Staff, PostedForm]:
    """`require_staff`, then this site's origin, then this session's CSRF token: the
    posted form (at most `max_fields` fields), or a 403 page and nothing changed."""
    staff = require_staff(request)
    check_origin(request, services(request).site_url)
    form = await read_form(request, max_fields)
    check_csrf(form.get(CSRF_FIELD, ""), staff.token, session_key(request))
    return staff, form


def require_staff_for_photo(request: Request) -> Staff:
    """`require_staff` for a photo: without a valid session a 401 page, never the photo and
    never a redirect (a thumbnail loading after the session ended mustn't start a sign-in
    and overwrite the sign-in state)."""
    try:
        return require_staff(request)
    except Answer as answered:
        if answered.response.status_code in (302, 303, 401):
            response = _message(request, 401, PHOTO_NEEDS_SIGN_IN, sign_in_link=True)
            if has_session_cookie(request):
                clear_session(response)
            raise Answer(response) from None
        raise


# --- GET /console/auth/sign-in -------------------------------------------------------


async def sign_in(request: Request) -> Response:
    console = services(request)
    started = new_sign_in(request.query_params.get("next", CONSOLE_HOME), console.clock.now())
    url = console.staff_tokens.sign_in_url(
        state=started.state,
        code_challenge=code_challenge(started.verifier),
        redirect_uri=console.callback_url,
    )
    response = RedirectResponse(url, status_code=302)
    set_sign_in(response, encode_sign_in(started, session_key(request)))
    return response


# --- GET /console/auth/callback --------------------------------------------------------


def _failed(request: Request) -> Response:
    """The sign-in cookie stays: another tab's sign-in may still finish with it, and it
    expires by itself in ten minutes. Someone already signed in (Back to the callback, or
    a second tab) goes to the console instead; the console checks the session itself."""
    log_event("sign_in_failed")
    if session_token(request, session_key(request)) is not None:
        return RedirectResponse(CONSOLE_HOME, status_code=303)
    return _message(request, 400, SIGN_IN_FAILED, sign_in_link=True)


def _is_param(value: str | None) -> bool:
    return value is not None and 0 < len(value) <= CODE_MAX_LENGTH and value.isascii() and value.isprintable()


async def callback(request: Request) -> Response:
    console = services(request)
    key = session_key(request)
    started = decode_sign_in(request.cookies.get(SIGNIN_COOKIE), key, console.clock.now())
    code, state = request.query_params.get("code"), request.query_params.get("state")
    if (
        started is None
        or "error" in request.query_params
        or not _is_param(code)
        or not _is_param(state)
        or not hmac.compare_digest(str(state).encode(), started.state.encode())
    ):
        return _failed(request)
    try:
        token = console.staff_tokens.exchange(
            code=str(code), code_verifier=started.verifier, redirect_uri=console.callback_url
        )
        member: StaffMember = console.staff_tokens.verify(token)
    except NotSignedIn:
        return _failed(request)
    except NotAllowed as refused:
        log_event("not_allowed", user=refused.username)
        response = _not_allowed(
            request,
            csrf=None,
            logout_url=console.staff_tokens.sign_out_url(redirect_uri=console.signed_out_url),
        )
        clear_sign_in(response)
        return response
    except SignInUnavailable:
        response = _unavailable(request, "sign_in_unavailable")
        clear_sign_in(response)
        return response
    if len(seal_session(token, key)) > TOKEN_MAX_LENGTH:
        # A browser drops a cookie this long: signing in would loop. Say it didn't finish.
        log_event("sign_in_failed", reason="token_too_long")
        return _message(request, 400, SIGN_IN_FAILED, sign_in_link=True)
    log_event("signed_in", user=member.username)
    response = RedirectResponse(started.next, status_code=303)
    set_session(response, token, key)
    clear_sign_in(response)
    return response


# --- POST /console/sign-out --------------------------------------------------------------


async def sign_out(request: Request) -> Response:
    """Clears the session and ends the managed-login session. Allowed to anyone whose
    session token verifies, in `ceramics` or not ("Sign in as someone else" on the
    not-allowed page), with this site's origin and the session's CSRF token."""
    console = services(request)
    # No cookie (its hour lapsed) or a stale one: nothing is signed in, so there is no
    # session to protect and the person is already signed out here.
    token = session_token(request, session_key(request))
    try:
        if token is None:  # no cookie, or not sealed with this environment's key
            raise NotSignedIn()
        username = console.staff_tokens.verify(token).username
    except NotAllowed as refused:
        username = refused.username
    except NotSignedIn:
        token = None
    except SignInUnavailable:
        # The token can't be checked, but its seal and the CSRF token are this key's own:
        # signing out still clears the session (a shared tablet mustn't stay signed in).
        username = None
    if token is None:
        response = RedirectResponse("/console/signed-out", status_code=303)
        clear_session(response)  # nothing signed in to end: only a stale cookie goes
        return response
    check_origin(request, console.site_url)
    form = await read_form(request)
    check_csrf(form.get(CSRF_FIELD, ""), token, session_key(request))
    if username is None:
        log_event("signed_out")
    else:
        log_event("signed_out", user=username)
    # A page that goes on to the staff sign-out by itself (a meta refresh, and a link),
    # not a redirect: `form-action 'self'` would block a form's redirect to another site.
    logout_url = console.staff_tokens.sign_out_url(redirect_uri=console.signed_out_url)
    page: Response = templates(request).TemplateResponse(
        request, "console/signing_out.html", {"logout_url": logout_url}
    )
    clear_session(page)
    return page


# --- GET /console/signed-out ---------------------------------------------------------------


async def signed_out(request: Request) -> Response:
    return templates(request).TemplateResponse(request, "console/signed_out.html", {})
