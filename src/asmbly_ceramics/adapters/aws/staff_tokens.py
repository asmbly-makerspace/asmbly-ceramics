"""`StaffTokens` on asmbly-staff-login's Cognito pool, through its public endpoints.

- `verify` checks an ID token's RS256 signature against the pool's key set, its issuer,
  its audience (this app's client), its expiry and `token_use == "id"`
  (amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html), then the username's
  shape and the `ceramics` group in `cognito:groups`. The email is taken only from a
  verified claim (`email_verified` is the boolean true), since the test email is sent to
  it as given.
- `sign_in_url`, `sign_out_url` and `exchange` are the managed login's
  `/oauth2/authorize`, `/logout` and `/oauth2/token` endpoints, with PKCE (S256) and no
  client secret (a public client).

Nothing logged holds a token, a code, a verifier, the state or the email claim: a
failure logs a fixed reason, or the OAuth error code.
"""

import contextlib
import hmac
import http.client
import json
import logging
import urllib.error
import urllib.request
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
LEEWAY_SECONDS = 30
_REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "token_use", "cognito:username"]


class SigningKeys(Protocol):
    """What `verify` needs of `jwt.PyJWKClient`, so tests pass a key set of their own."""

    def get_signing_key_from_jwt(self, token: str) -> PyJWK: ...


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
        self._keys: SigningKeys = keys or PyJWKClient(
            f"{self._issuer}/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=KEYS_LIFESPAN_SECONDS,
            timeout=TIMEOUT_SECONDS,
        )
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
                "scope": "openid email",
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
