"""What keeps the public form safe at the edge: the headers on every response, the
client's address for the rate limit, the same-origin check, signed cookies, and reading
a bounded body. The console (phase 8) reuses these.

Nothing here logs, and nothing here puts a cookie's, a token's or an address's value in
an exception's text.
"""

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from urllib.parse import urlsplit

from starlette.requests import Request

from asmbly_ceramics.web.errors import PageError

DEVICE_COOKIE = "__Host-device"
RECEIVED_COOKIE = "__Host-received"
DEVICE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # a year, in seconds
CACHE_NO_STORE = "no-store"
CACHE_STATIC = "public, max-age=3600"
_BAD_SOURCE_CHARACTERS = frozenset(";, \r\n\t")


def csp(photo_upload_origin: str) -> str:
    """The Content-Security-Policy, from a fixed frame: `default-src 'none'` first and
    `base-uri`, `form-action`, `frame-ancestors` last. The one variable source is the
    photo bucket's upload origin, which may hold no `;`, `,`, space, tab, CR or LF, so
    it can't add a directive or a second source."""
    if not photo_upload_origin or any(c in _BAD_SOURCE_CHARACTERS for c in photo_upload_origin):
        raise ValueError("a CSP source holds no separator or whitespace")
    directives = (
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' blob: data:",
        "font-src 'self'",
        f"connect-src 'self' {photo_upload_origin}",
        "form-action 'self'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    )
    return "; ".join(directives)


def security_headers(policy: str) -> Mapping[str, str]:
    """The headers every response carries; `Cache-Control` is `no-store` except on
    static files, which the app sets to `CACHE_STATIC` itself."""
    return MappingProxyType(
        {
            "Content-Security-Policy": policy,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": CACHE_NO_STORE,
            "Referrer-Policy": "same-origin",  # under no-referrer, browsers send `Origin: null` on POSTs
            "Strict-Transport-Security": "max-age=31536000",
        }
    )


def origin_of(url: str) -> str:
    """`scheme://host[:port]` of a URL, lowercased, as a browser's `Origin` header has it."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError("an origin needs a scheme and a host")
    return f"{parts.scheme}://{parts.netloc}".lower()


def client_address(request: Request) -> str:
    """The **last** comma-separated value of `X-Forwarded-For`, trimmed: API Gateway's
    HTTP API appends the address it saw, so only the last value can be trusted; anything
    earlier is the caller's own text. `request.client` is the Web Adapter's loopback and
    is never used. No header, or an empty last value: a 400 page."""
    values = request.headers.getlist("x-forwarded-for")
    if not values:
        raise PageError(400)
    last = values[-1].split(",")[-1].strip()
    if not last:
        raise PageError(400)
    return last


def require_same_origin(request: Request, site_origin: str) -> None:
    """`Origin` must be this site's exactly; without `Origin`, or with `null` (sent when a
    referrer policy hides the origin), `Sec-Fetch-Site` must be `same-origin`. Anything
    else: a 403 page."""
    origin = request.headers.get("origin")
    if origin is not None and origin != "null":
        if origin.lower() == site_origin:
            return
        raise PageError(403)
    if request.headers.get("sec-fetch-site") == "same-origin":
        return
    raise PageError(403)


def new_token() -> str:
    """A submission token: 24 random bytes, 32 URL-safe characters (`is_form_token`)."""
    return secrets.token_urlsafe(24)


def new_device() -> str:
    """A device cookie's value: 32 random bytes, 43 URL-safe characters."""
    return secrets.token_urlsafe(32)


def sign(value: str, expires_at: datetime, key: bytes) -> str:
    """`<value>.<expiry, Unix seconds>.<HMAC-SHA256 hex>`. `value` holds no `.`."""
    if "." in value:
        raise ValueError("a signed value holds no '.'")
    payload = f"{value}.{int(expires_at.timestamp())}"
    return f"{payload}.{_mac(payload, key)}"


def verify(signed: str | None, now: datetime, key: bytes) -> str | None:
    """The value `sign` signed, or `None` when it is missing, malformed, tampered with or
    expired (at its expiry or after)."""
    if not signed:
        return None
    parts = signed.split(".")
    if len(parts) != 3:
        return None
    value, expiry, mac = parts
    if not expiry.isascii() or not expiry.isdigit() or len(expiry) > 12 or not mac.isascii():
        return None
    if not hmac.compare_digest(mac, _mac(f"{value}.{expiry}", key)):
        return None
    if now.timestamp() >= int(expiry):
        return None
    return value


def _mac(payload: str, key: bytes) -> str:
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


async def read_body(request: Request, limit: int) -> bytes:
    """The body, at most `limit` bytes; more, or a `Content-Length` saying more, is a 413
    page. Counted as it streams, so a lying or missing `Content-Length` doesn't help."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise PageError(413)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise PageError(413)
        chunks.append(chunk)
    return b"".join(chunks)
