"""Forged requests: every console POST carries a CSRF token bound to its session, and
comes from this site.

The token is HMAC-SHA256, under the session key, of the session's ID token, so it changes
with each sign-in and another session's token never fits. SameSite=Lax on the session
cookie already keeps a cross-site POST from carrying it; these checks hold even if it
didn't. Nothing here logs a token or a header's value.
"""

import base64
import hashlib
import hmac
from urllib.parse import urlsplit

from starlette.requests import Request

from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.web.errors import PageError
from asmbly_ceramics.web.security import origin_of

CSRF_FIELD = "csrf"
FORM_EXPIRED = "This form has expired. Go back, reload the page and try again."
_PURPOSE = b"csrf:"


def csrf_token(session_token: str, key: bytes) -> str:
    digest = hmac.new(key, _PURPOSE + session_token.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def check_csrf(sent: str, session_token: str, key: bytes) -> None:
    """A 403 page unless `sent` is this session's token."""
    if not sent or not hmac.compare_digest(sent.encode(), csrf_token(session_token, key).encode()):
        log_event("csrf_refused", outcome="missing" if not sent else "wrong_token")
        raise PageError(403, FORM_EXPIRED, logged=True)


def check_origin(request: Request, site_url: str) -> None:
    """`Origin` must be this site; when the browser sends none (or `null`),
    `Sec-Fetch-Site` must be `same-origin` or `Referer` a console page of this site.
    Otherwise a 403 page."""
    site = origin_of(site_url)
    origin = request.headers.get("origin")
    if origin is not None and origin != "null":
        if origin.lower() == site:
            return
        log_event("csrf_refused", outcome="other_origin")
        raise PageError(403, FORM_EXPIRED, logged=True)
    if request.headers.get("sec-fetch-site") == "same-origin":
        return
    referer = request.headers.get("referer", "")
    try:
        same_site = origin_of(referer) == site
        path = urlsplit(referer).path
    except ValueError:  # a malformed Referer (an unclosed `[`) is no console page
        same_site, path = False, ""
    if same_site and (path == "/console" or path.startswith("/console/")):
        return
    log_event("csrf_refused", outcome="other_origin")
    raise PageError(403, FORM_EXPIRED, logged=True)
