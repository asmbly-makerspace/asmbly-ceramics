"""`StaffTokens` on asmbly-staff-login's Cognito pool, through its public endpoints.

- `verify` checks an ID token's RS256 signature against the pool's key set, its issuer,
  its audience (this app's client), its expiry and `token_use == "id"`
  (amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html), then the username's
  shape and the `ceramics` group in `cognito:groups`. The email is taken only from a
  verified claim (`email_verified` is the boolean true), since the test email is sent to
  it as given. `sign_in_url` asks for the scope `openid` alone: Cognito then puts every
  attribute the client may read in the ID token, `email` and `email_verified` among them
  (cognito-user-pools-define-resource-servers.html, "OpenID Connect (OIDC) scopes"), and
  asmbly-staff-login's web clients allow only `openid`.
- `sign_in_url`, `sign_out_url` and `exchange` are the managed login's
  `/oauth2/authorize`, `/logout` and `/oauth2/token` endpoints, with PKCE (S256) and no
  client secret (a public client).

The pool's key set is fetched by `ThrottledSigningKeys`: once an hour, and again for a
`kid` it doesn't hold at most once a minute, so a stream of forged tokens with made-up
`kid`s can't make every request fetch the key set (phase 8).

Nothing logged holds a token, a code, a verifier, the state or the email claim: a
failure logs a fixed reason, or the OAuth error code.
"""

import contextlib
import hmac
import http.client
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any, NoReturn, Protocol
from urllib.parse import urlencode, urlsplit

import jwt
from jwt import PyJWK, PyJWKClient, PyJWKClientConnectionError, PyJWKClientError, PyJWTError

from asmbly_ceramics.ports.errors import SignInUnavailable, error_code
from asmbly_ceramics.ports.staff import (
    STAFF_GROUP,
    NotAllowed,
    NotSignedIn,
    StaffMember,
    is_staff_username,
)
from asmbly_ceramics.use_cases.log import log_event

TIMEOUT_SECONDS = 5
KEYS_LIFESPAN_SECONDS = 3600
KEYS_REFETCH_SECONDS = 60  # the soonest an unknown `kid` (or a failed fetch) fetches again
KEYS_FIRST_RETRY_SECONDS = 5  # while no key set is held: a cold container retries sooner
LEEWAY_SECONDS = 30
_REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "token_use", "cognito:username"]


class SigningKeys(Protocol):
    """What `verify` needs of `jwt.PyJWKClient`, so tests pass a key set of their own."""

    def get_signing_key_from_jwt(self, token: str) -> PyJWK: ...


class ThrottledSigningKeys:
    """`SigningKeys` from a key set fetched by `fetch`: again after `lifespan` seconds,
    and for a `kid` it doesn't hold (a key rotated in, or a forged token) at most once
    every `refetch` seconds, counting failed fetches; otherwise an unknown `kid` is
    refused without a fetch (`PyJWKClientError`, which `verify` treats as not signed in).
    A failed first fetch raises `PyJWKClientConnectionError` (sign-in unavailable) and is
    tried again after `first_retry` seconds; a failed refresh (unreachable, or an empty or
    malformed key set) keeps the set it holds."""

    def __init__(
        self,
        fetch: Callable[[], Sequence[PyJWK]],
        *,
        clock: Callable[[], float] = time.monotonic,
        lifespan: float = KEYS_LIFESPAN_SECONDS,
        refetch: float = KEYS_REFETCH_SECONDS,
        first_retry: float = KEYS_FIRST_RETRY_SECONDS,
    ) -> None:
        self._fetch = fetch
        self._clock = clock
        self._lifespan = lifespan
        self._refetch = refetch
        self._first_retry = first_retry
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None  # the last fetch that worked
        self._tried_at: float | None = None  # the last fetch, worked or not

    @classmethod
    def for_issuer(cls, issuer: str) -> ThrottledSigningKeys:
        client = PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_jwk_set=False, timeout=TIMEOUT_SECONDS)
        return cls(client.get_signing_keys)

    def get_signing_key_from_jwt(self, token: str) -> PyJWK:
        kid = jwt.get_unverified_header(token).get("kid")  # DecodeError for a malformed token
        if not isinstance(kid, str) or not kid:
            raise PyJWKClientError("no kid")
        now = self._clock()
        stale = self._fetched_at is None or now - self._fetched_at >= self._lifespan
        if (stale or kid not in self._keys) and self._may_fetch(now):
            self._tried_at = now
            try:
                # PyJWKClientConnectionError when it can't be reached; another PyJWTError
                # for an empty or malformed key set; ValueError or OSError reading it.
                fetched = {key.key_id: key for key in self._fetch() if key.key_id}
                if not fetched:
                    raise PyJWKClientError("no signing keys")
            except (PyJWTError, ValueError, OSError) as failed:
                if self._fetched_at is None:
                    raise
                # A refresh failed: keep the set held, and log a code, never the body.
                unreachable = isinstance(failed, PyJWKClientConnectionError)
                log_event(
                    "jwks_refresh_failed",
                    level=logging.WARNING,
                    error_code="jwks_unreachable" if unreachable else "jwks_unreadable",
                )
            else:
                self._fetched_at = now
                self._keys = fetched
        elif self._fetched_at is None:
            raise PyJWKClientConnectionError("the key set was fetched without success just now")
        key = self._keys.get(kid)
        if key is None:
            raise PyJWKClientError("no key with that kid")
        return key

    def _may_fetch(self, now: float) -> bool:
        wait = self._first_retry if self._fetched_at is None else self._refetch
        return self._tried_at is None or now - self._tried_at >= wait


class TokenTransport(Protocol):
    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        """The answer's status and body; `OSError` when the endpoint can't be reached."""
        ...


class UrllibTransport:
    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        if urlsplit(url).scheme != "https":
            raise ValueError("the token endpoint is https")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310  # https only, checked above
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310  # https only, checked above
                return int(response.status), bytes(response.read())
        except urllib.error.HTTPError as error:
            return int(error.code), bytes(error.read())


def _https_origin(url: str, what: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.path not in ("", "/") or parts.query:
        raise ValueError(f"the {what} is an https origin with no path")
    return f"https://{parts.netloc}"


class CognitoStaffTokens:
    def __init__(
        self,
        *,
        issuer: str,
        sign_in_origin: str,
        client_id: str,
        keys: SigningKeys | None = None,
        transport: TokenTransport | None = None,
    ) -> None:
        if urlsplit(issuer).scheme != "https":
            raise ValueError("the issuer is an https address")
        if not client_id:
            raise ValueError("a client ID is needed")
        self._issuer = issuer.rstrip("/")
        self._origin = _https_origin(sign_in_origin, "sign-in address")
        self._client_id = client_id
        self._keys: SigningKeys = keys or ThrottledSigningKeys.for_issuer(self._issuer)
        self._transport = transport or UrllibTransport()

    def verify(self, id_token: str) -> StaffMember:
        claims = self._claims(id_token)
        username = claims["cognito:username"]
        if not is_staff_username(username):
            _refused("username")
        groups = claims.get("cognito:groups")
        if not isinstance(groups, list) or STAFF_GROUP not in groups:
            log_event("sign_in_refused", reason="not_in_group", user=username)
            raise NotAllowed(username)
        email = claims.get("email")
        verified = claims.get("email_verified") is True and isinstance(email, str)
        return StaffMember(username=username, email=email if verified else None)

    def sign_in_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": "openid",  # alone, the ID token holds every claim the client may read: email too
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self._origin}/oauth2/authorize?{query}"

    def sign_out_url(self, *, redirect_uri: str) -> str:
        query = urlencode({"client_id": self._client_id, "logout_uri": redirect_uri})
        return f"{self._origin}/logout?{query}"

    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        ).encode()
        try:
            status, answer = self._transport.post(
                f"{self._origin}/oauth2/token", body, {"Content-Type": "application/x-www-form-urlencoded"}
            )
        except (OSError, http.client.HTTPException) as error:  # unreachable, timed out, cut short
            code_name = error_code(type(error).__name__)
            log_event("sign_in_unavailable", level=logging.WARNING, error_code=code_name)
            raise SignInUnavailable(code_name) from None
        if status >= 500:
            log_event("sign_in_unavailable", level=logging.WARNING, error_code=str(status))
            raise SignInUnavailable(str(status))
        payload = _json(answer)
        if status != 200:
            oauth_error = payload.get("error") if isinstance(payload.get("error"), str) else ""
            log_event("sign_in_refused", reason="exchange", error_code=error_code(str(oauth_error)))
            raise NotSignedIn()
        id_token = payload.get("id_token")
        if not isinstance(id_token, str):
            _refused("no_id_token")
        with contextlib.suppress(NotAllowed):  # signed in; the console's `verify` says "not allowed"
            self.verify(id_token)
        return id_token

    def _claims(self, id_token: str) -> dict[str, Any]:
        if not isinstance(id_token, str) or not id_token:
            _refused("missing")
        try:
            key = self._keys.get_signing_key_from_jwt(id_token)
        except PyJWKClientConnectionError:  # a PyJWTError too: caught first
            log_event("sign_in_unavailable", level=logging.WARNING, error_code="jwks_unreachable")
            raise SignInUnavailable("jwks_unreachable") from None
        except PyJWKClientError, PyJWTError:
            _refused("invalid")
        except ValueError, OSError:  # not JSON, or the connection broke reading it
            log_event("sign_in_unavailable", level=logging.WARNING, error_code="jwks_unreadable")
            raise SignInUnavailable("jwks_unreadable") from None
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._client_id,
                options={"require": _REQUIRED_CLAIMS},
                leeway=LEEWAY_SECONDS,
            )
        except jwt.ExpiredSignatureError:
            _refused("expired")
        except PyJWTError:
            _refused("invalid")
        audience = claims.get("aud")
        # PyJWT checks `aud` already; the comparison is the security boundary, so it is
        # made again in constant time on the exact string.
        if not isinstance(audience, str) or not hmac.compare_digest(audience, self._client_id):
            _refused("audience")
        if claims.get("token_use") != "id":
            _refused("token_use")
        return claims


def _json(answer: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(answer)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _refused(reason: str) -> NoReturn:
    """Logs the fixed `reason` and raises `NotSignedIn`."""
    log_event("sign_in_refused", reason=reason)
    # `from None`: called inside `except` blocks, where PyJWT's error (whose text can
    # quote the token's header, the caller's text) would otherwise be chained.
    raise NotSignedIn() from None
