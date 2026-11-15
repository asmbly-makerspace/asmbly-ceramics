"""The console's two cookies, and the signed sign-in state.

- `__Host-signin` holds, for ten minutes, what the callback must check: the PKCE
  verifier, the `state` sent to the staff sign-in, where to go next, and when it was made,
  signed with HMAC-SHA256 under the session key.
- `__Host-session` holds the staff member's ID token, sealed with HMAC-SHA256 under the
  session key (`<token>.<mac>`), checked on every request (`auth.require_staff`). The
  seal ties a session to this environment's key: changing `session-key` signs everyone
  out, and a token signed in on stage (the same client) is no session on prod. It lives
  an hour, as the token does; it is never refreshed.

Both are `__Host-`, HttpOnly, Secure, SameSite=Lax and Path=/. Nothing here logs, and no
error holds a cookie's value.
"""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime

from starlette.requests import Request
from starlette.responses import Response

SESSION_COOKIE = "__Host-session"
SIGNIN_COOKIE = "__Host-signin"
SIGNIN_LIFETIME_SECONDS = 600
SESSION_MAX_AGE_SECONDS = 3600  # asmbly-staff-login's web clients get 60-minute ID tokens
CLOCK_SKEW_SECONDS = 60
TOKEN_MAX_LENGTH = 4096  # a browser keeps a cookie of about 4 KB at most; an ID token is 1 to 2 KB
SIGNIN_MAX_LENGTH = 2048
NEXT_MAX_LENGTH = 512
CONSOLE_HOME = "/console"
_SIGNIN_PURPOSE = b"signin:"
_SESSION_PURPOSE = b"session:"


@dataclass(frozen=True, slots=True)
class SignIn:
    verifier: str = field(repr=False)  # the PKCE code verifier: 32 random bytes, base64url
    state: str = field(repr=False)  # 32 random bytes, base64url
    next: str  # `safe_next`'s console path
    issued_at: int  # Unix seconds


def new_sign_in(next: str, now: datetime) -> SignIn:
    return SignIn(
        verifier=secrets.token_urlsafe(32),
        state=secrets.token_urlsafe(32),
        next=safe_next(next),
        issued_at=int(now.timestamp()),
    )


def code_challenge(verifier: str) -> str:
    """PKCE's S256: unpadded base64url of the verifier's SHA-256."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def safe_next(raw: object) -> str:
    """`raw` when it is a path of this console (`/console`, `/console/...` or
    `/console?...`), with no scheme, host, `//`, backslash, control character or space;
    otherwise `/console`. So the return after signing in never leaves the console."""
    if not isinstance(raw, str) or not raw or len(raw) > NEXT_MAX_LENGTH:
        return CONSOLE_HOME
    if not raw.isascii() or any(c <= " " or c in "\\\x7f" for c in raw) or "//" in raw:
        return CONSOLE_HOME
    if raw != CONSOLE_HOME and not raw.startswith((CONSOLE_HOME + "/", CONSOLE_HOME + "?")):
        return CONSOLE_HOME
    return raw


def _mac(payload: str, key: bytes) -> str:
    return hmac.new(key, _SIGNIN_PURPOSE + payload.encode("ascii"), hashlib.sha256).hexdigest()


def encode_sign_in(sign_in: SignIn, key: bytes) -> str:
    data = json.dumps(
        {"v": sign_in.verifier, "s": sign_in.state, "n": sign_in.next, "t": sign_in.issued_at},
        separators=(",", ":"),
    )
    payload = base64.urlsafe_b64encode(data.encode("ascii")).rstrip(b"=").decode("ascii")
    return f"{payload}.{_mac(payload, key)}"


def decode_sign_in(value: str | None, key: bytes, now: datetime) -> SignIn | None:
    """The sign-in state, or `None` when it is missing, malformed, tampered with, older
    than ten minutes, or from the future."""
    if not value or len(value) > SIGNIN_MAX_LENGTH or not value.isascii():
        return None
    payload, _, mac = value.partition(".")
    if not payload or not hmac.compare_digest(mac, _mac(payload, key)):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    verifier, state, next_, issued_at = data.get("v"), data.get("s"), data.get("n"), data.get("t")
    if not (isinstance(verifier, str) and isinstance(state, str) and isinstance(next_, str)):
        return None
    if type(issued_at) is not int:
        return None
    age = now.timestamp() - issued_at
    if not -CLOCK_SKEW_SECONDS <= age < SIGNIN_LIFETIME_SECONDS:
        return None
    return SignIn(verifier=verifier, state=state, next=safe_next(next_), issued_at=issued_at)


def _session_mac(token: str, key: bytes) -> str:
    return hmac.new(key, _SESSION_PURPOSE + token.encode(), hashlib.sha256).hexdigest()


def seal_session(token: str, key: bytes) -> str:
    return f"{token}.{_session_mac(token, key)}"


def has_session_cookie(request: Request) -> bool:
    return bool(request.cookies.get(SESSION_COOKIE))


def session_token(request: Request, key: bytes) -> str | None:
    """The session cookie's ID token when its seal is this key's, or `None` when there is
    no cookie, it is far too long, or its seal doesn't match (another key, another
    environment, tampered with)."""
    sealed = request.cookies.get(SESSION_COOKIE)
    if not sealed or len(sealed) > TOKEN_MAX_LENGTH or not sealed.isascii():
        return None
    token, _, mac = sealed.rpartition(".")
    if not token or not hmac.compare_digest(mac, _session_mac(token, key)):
        return None
    return token


def _set(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(name, value, max_age=max_age, path="/", secure=True, httponly=True, samesite="lax")


def _clear(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")


def set_session(response: Response, token: str, key: bytes) -> None:
    _set(response, SESSION_COOKIE, seal_session(token, key), SESSION_MAX_AGE_SECONDS)


def clear_session(response: Response) -> None:
    _clear(response, SESSION_COOKIE)


def set_sign_in(response: Response, value: str) -> None:
    _set(response, SIGNIN_COOKIE, value, SIGNIN_LIFETIME_SECONDS)


def clear_sign_in(response: Response) -> None:
    _clear(response, SIGNIN_COOKIE)
