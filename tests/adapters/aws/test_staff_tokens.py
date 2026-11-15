"""`CognitoStaffTokens`: an RSA key made in the test, a stub key set and a stub token
endpoint; no network."""

import base64
import hashlib
import hmac
import http.client
import io
import json
import logging
import time
import urllib.error
import urllib.request
from email.message import Message
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK, PyJWKClientConnectionError, PyJWKClientError, PyJWKSetError

from asmbly_ceramics.adapters.aws.staff_tokens import (
    KEYS_FIRST_RETRY_SECONDS,
    KEYS_LIFESPAN_SECONDS,
    KEYS_REFETCH_SECONDS,
    CognitoStaffTokens,
    SigningKeys,
    ThrottledSigningKeys,
    UrllibTransport,
)
from asmbly_ceramics.adapters.memory.staff_tokens import s256
from asmbly_ceramics.ports.errors import SignInUnavailable
from asmbly_ceramics.ports.staff import NotAllowed, NotSignedIn, StaffMember
from tests.adapters.conftest import assert_nothing_holds
from tests.domain.builders import STAFF, an_address

ISSUER = "https://cognito-idp.us-east-2.amazonaws.com/us-east-2_MadeUpPool"
ORIGIN = "https://sign-in.example.org"
CLIENT_ID = "made-up-client-id"
KID = "made-up-key"
STAFF_EMAIL = an_address("kiln.tech")
VERIFIER = "made-up-verifier-made-up-verifier-made-up-verifier"
CODE = "made-up-code"
STATE = "made-up-state"
REDIRECT = "https://ceramics.example.org/console/auth/callback"

PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_of(key: rsa.RSAPrivateKey, kid: str = KID) -> PyJWK:
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return PyJWK({**public, "kid": kid, "alg": "RS256", "use": "sig"})


class Keys:
    def __init__(self, key: rsa.RSAPrivateKey = PRIVATE, fail: Exception | None = None) -> None:
        self.jwk = jwk_of(key)
        self.fail = fail

    def get_signing_key_from_jwt(self, token: str) -> PyJWK:
        if self.fail is not None:
            raise self.fail
        jwt.get_unverified_header(token)  # a malformed token fails here, as PyJWKClient's does
        return self.jwk


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    values: dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "token_use": "id",
        "exp": now + 3600,
        "iat": now,
        "cognito:username": STAFF,
        "cognito:groups": ["ceramics", "front-desk"],
        "email": STAFF_EMAIL,
        "email_verified": True,
    }
    values.update(overrides)
    return {name: value for name, value in values.items() if value is not None}


def a_token(
    named: dict[str, Any] | None = None, /, *, key: rsa.RSAPrivateKey = PRIVATE, **overrides: Any
) -> str:
    """A signed ID token; `named` sets claims whose names aren't identifiers."""
    return jwt.encode(claims(**(named or {}), **overrides), key, algorithm="RS256", headers={"kid": KID})


def tokens(keys: SigningKeys | None = None, transport: Any = None) -> CognitoStaffTokens:
    return CognitoStaffTokens(
        issuer=ISSUER, sign_in_origin=ORIGIN, client_id=CLIENT_ID, keys=keys or Keys(), transport=transport
    )


def test_valid_id_token_in_ceramics_returns_username_and_verified_email() -> None:
    assert tokens().verify(a_token()) == StaffMember(STAFF, STAFF_EMAIL)


@pytest.mark.parametrize("verified", [False, None, "true", 1])
def test_unverified_email_is_none(verified: Any) -> None:
    member = tokens().verify(a_token(email_verified=verified))
    assert member == StaffMember(STAFF, None)


def test_expired_token_is_not_signed_in(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    old = int(time.time()) - 7200
    with pytest.raises(NotSignedIn) as raised:
        tokens().verify(a_token(exp=old, iat=old - 3600))
    assert_not_chained(raised.value)
    assert [vars(r)["reason"] for r in caplog.records] == ["expired"]


@pytest.mark.parametrize(
    "token",
    [
        lambda: a_token(iss="https://cognito-idp.us-east-2.amazonaws.com/us-east-2_Another"),
        lambda: a_token(aud="another-client"),
        lambda: a_token(aud=[CLIENT_ID, "another-client"]),
        lambda: a_token(key=OTHER),
        lambda: a_token(token_use=None),
        lambda: a_token({"cognito:username": None}),
        lambda: a_token(exp=None),
        lambda: "not.a.token",
        lambda: "",
    ],
    ids=[
        "issuer",
        "audience",
        "two-audiences",
        "signature",
        "no-token-use",
        "no-username",
        "no-exp",
        "junk",
        "empty",
    ],
)
def test_wrong_issuer_audience_or_signature_is_not_signed_in(token: Any) -> None:
    with pytest.raises(NotSignedIn) as raised:
        tokens().verify(token())
    assert_not_chained(raised.value)


def assert_not_chained(error: BaseException) -> None:
    """PyJWT's error text can quote the token's header (the caller's text): never chained."""
    assert error.__cause__ is None
    assert error.__suppress_context__


def test_access_token_is_refused() -> None:
    with pytest.raises(NotSignedIn):
        tokens().verify(a_token(token_use="access"))


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forged(algorithm: str, secret: bytes | None) -> str:
    header = b64(json.dumps({"alg": algorithm, "typ": "JWT", "kid": KID}).encode())
    payload = b64(json.dumps(claims()).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = b"" if secret is None else hmac.new(secret, signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{b64(signature)}"


def test_hs256_token_is_refused() -> None:
    # Algorithm confusion: an HMAC token keyed with the public key's bytes, and "none".
    public_pem = PRIVATE.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    for token in (forged("HS256", public_pem), forged("none", None)):
        with pytest.raises(NotSignedIn):
            tokens().verify(token)


@pytest.mark.parametrize("username", [STAFF_EMAIL, "512" + "5550100", "a" * 41, "kiln tech"])
def test_a_username_that_isnt_a_handle_is_not_signed_in(username: str) -> None:
    with pytest.raises(NotSignedIn):
        tokens().verify(a_token({"cognito:username": username}))


def test_a_sub_uuid_username_is_a_handle() -> None:
    sub = "3f2a9c1e-0b7d-4e5f-9a8b-1c2d3e4f5a6b"
    assert tokens().verify(a_token({"cognito:username": sub})).username == sub


def test_signed_in_without_ceramics_group_is_not_allowed() -> None:
    with pytest.raises(NotAllowed) as refused:
        tokens().verify(a_token({"cognito:groups": ["front-desk"]}))
    assert refused.value.username == STAFF


@pytest.mark.parametrize("groups", [None, "ceramics", {"ceramics": True}])
def test_missing_groups_claim_is_not_allowed(groups: Any) -> None:
    with pytest.raises(NotAllowed):
        tokens().verify(a_token({"cognito:groups": groups}))


def test_keys_unavailable_is_sign_in_unavailable_not_not_signed_in() -> None:
    down = Keys(fail=PyJWKClientConnectionError("made-up outage"))
    with pytest.raises(SignInUnavailable):
        tokens(down).verify(a_token())
    unknown_kid = Keys(fail=PyJWKClientError("no matching key"))
    with pytest.raises(NotSignedIn) as raised:
        tokens(unknown_kid).verify(a_token())
    assert_not_chained(raised.value)


def test_sign_in_url_has_pkce_state_and_openid() -> None:
    url = tokens().sign_in_url(state=STATE, code_challenge=s256(VERIFIER), redirect_uri=REDIRECT)
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{ORIGIN}/oauth2/authorize"
    assert parse_qs(parts.query) == {
        "response_type": ["code"],
        "client_id": [CLIENT_ID],
        "redirect_uri": [REDIRECT],
        "scope": ["openid email"],
        "state": [STATE],
        "code_challenge": [s256(VERIFIER)],
        "code_challenge_method": ["S256"],
    }


def test_sign_out_url_has_client_and_logout_uri() -> None:
    url = tokens().sign_out_url(redirect_uri="https://ceramics.example.org/console/signed-out")
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{ORIGIN}/logout"
    assert parse_qs(parts.query) == {
        "client_id": [CLIENT_ID],
        "logout_uri": ["https://ceramics.example.org/console/signed-out"],
    }


class Transport:
    def __init__(self, status: int = 200, body: Any = None, fail: Exception | None = None) -> None:
        self.status, self.body, self.fail = status, body, fail
        self.posts: list[tuple[str, dict[str, list[str]], dict[str, str]]] = []

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        self.posts.append((url, parse_qs(body.decode()), headers))
        if self.fail is not None:
            raise self.fail
        return self.status, json.dumps(self.body).encode() if not isinstance(self.body, bytes) else self.body


def test_exchange_posts_code_and_verifier_and_verifies_the_result() -> None:
    token = a_token()
    transport = Transport(body={"id_token": token, "access_token": "x", "token_type": "Bearer"})
    assert (
        tokens(transport=transport).exchange(code=CODE, code_verifier=VERIFIER, redirect_uri=REDIRECT)
        == token
    )
    [(url, form, headers)] = transport.posts
    assert url == f"{ORIGIN}/oauth2/token"
    assert headers == {"Content-Type": "application/x-www-form-urlencoded"}
    assert form == {
        "grant_type": ["authorization_code"],
        "client_id": [CLIENT_ID],
        "code": [CODE],
        "redirect_uri": [REDIRECT],
        "code_verifier": [VERIFIER],
    }


def test_exchange_refuses_a_token_that_doesnt_verify_but_returns_one_outside_the_group() -> None:
    forged = Transport(body={"id_token": a_token(key=OTHER)})
    with pytest.raises(NotSignedIn):
        tokens(transport=forged).exchange(code=CODE, code_verifier=VERIFIER, redirect_uri=REDIRECT)
    outsider = a_token({"cognito:groups": []})
    signed_in = Transport(body={"id_token": outsider})
    assert (
        tokens(transport=signed_in).exchange(code=CODE, code_verifier=VERIFIER, redirect_uri=REDIRECT)
        == outsider
    )
    for body in ({}, {"id_token": 5}, b"not json", [1]):
        with pytest.raises(NotSignedIn):
            tokens(transport=Transport(body=body)).exchange(
                code=CODE, code_verifier=VERIFIER, redirect_uri=REDIRECT
            )


def test_exchange_error_reports_only_the_oauth_error_code(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    transport = Transport(400, {"error": "invalid_grant", "error_description": "code " + CODE + " is used"})
    with pytest.raises(NotSignedIn):
        tokens(transport=transport).exchange(code=CODE, code_verifier=VERIFIER, redirect_uri=REDIRECT)
    [record] = caplog.records
    assert (vars(record)["reason"], vars(record)["error_code"]) == ("exchange", "invalid_grant")
    assert_nothing_holds(caplog.records, CODE, VERIFIER)


@pytest.mark.parametrize(
    "transport", [Transport(fail=TimeoutError()), Transport(fail=OSError()), Transport(503, {})], ids=str
)
def test_a_token_endpoint_that_cant_be_reached_is_sign_in_unavailable(transport: Transport) -> None:
    with pytest.raises(SignInUnavailable):
        tokens(transport=transport).exchange(code=CODE, code_verifier=VERIFIER, redirect_uri=REDIRECT)


def test_no_token_code_or_verifier_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="asmbly_ceramics")
    token = a_token({"cognito:groups": []})
    with pytest.raises(NotAllowed):
        tokens().verify(token)
    with pytest.raises(NotSignedIn):
        tokens().verify(a_token(aud="another-client"))
    with pytest.raises(NotSignedIn):
        tokens(transport=Transport(400, {"error": "invalid_request"})).exchange(
            code=CODE, code_verifier=VERIFIER, redirect_uri=REDIRECT
        )
    assert caplog.records
    assert_nothing_holds(caplog.records, token, CODE, VERIFIER, STAFF_EMAIL, STATE)


@pytest.mark.parametrize(
    "arguments",
    [
        {"issuer": "http://cognito.example.org"},
        {"sign_in_origin": "http://sign-in.example.org"},
        {"sign_in_origin": "https://sign-in.example.org/path"},
        {"client_id": ""},
    ],
)
def test_the_configuration_is_checked(arguments: dict[str, str]) -> None:
    values: dict[str, Any] = {"issuer": ISSUER, "sign_in_origin": ORIGIN, "client_id": CLIENT_ID, **arguments}
    with pytest.raises(ValueError, match=r"https|client"):
        CognitoStaffTokens(**values, keys=Keys())


def test_the_default_key_set_and_transport_need_no_network_to_build() -> None:
    built = CognitoStaffTokens(issuer=ISSUER, sign_in_origin=ORIGIN, client_id=CLIENT_ID)
    assert built.sign_out_url(redirect_uri=REDIRECT).startswith(ORIGIN)
    with pytest.raises(ValueError, match="https"):
        UrllibTransport().post("http://sign-in.example.org/oauth2/token", b"", {})


class Answer:
    status = 200

    def __enter__(self) -> Answer:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def read(self) -> bytes:
        return b'{"id_token": "x"}'


def test_the_urllib_transport_posts_with_a_timeout_and_returns_error_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, bytes | None, float]] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> Answer:
        seen.append((request.full_url, request.data if isinstance(request.data, bytes) else None, timeout))
        return Answer()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert UrllibTransport().post(f"{ORIGIN}/oauth2/token", b"a=1", {}) == (200, b'{"id_token": "x"}')
    assert seen == [(f"{ORIGIN}/oauth2/token", b"a=1", 5)]

    def refused(request: urllib.request.Request, timeout: float) -> Answer:
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", Message(), io.BytesIO(b"{}"))

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    assert UrllibTransport().post(f"{ORIGIN}/oauth2/token", b"", {}) == (400, b"{}")


def test_a_key_set_that_isnt_json_is_sign_in_unavailable() -> None:
    with pytest.raises(SignInUnavailable):
        tokens(Keys(fail=json.JSONDecodeError("made-up", "", 0))).verify(a_token())


def test_a_token_answer_cut_short_is_sign_in_unavailable() -> None:
    transport = Transport(fail=http.client.IncompleteRead(b""))
    with pytest.raises(SignInUnavailable):
        tokens(transport=transport).exchange(code=CODE, code_verifier=VERIFIER, redirect_uri=REDIRECT)


def test_a_key_set_connection_reset_is_sign_in_unavailable() -> None:
    with pytest.raises(SignInUnavailable):
        tokens(Keys(fail=ConnectionResetError())).verify(a_token())


# The throttled key set (phase 8) --------------------------------------------------------


class Fetches:
    """A key set fetch that counts its calls; `fail` makes the next ones fail."""

    def __init__(self, *keys: PyJWK) -> None:
        self.keys = list(keys)
        self.count = 0
        self.fail: Exception | None = None

    def __call__(self) -> list[PyJWK]:
        self.count += 1
        if self.fail is not None:
            raise self.fail
        return self.keys


class Ticks:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def a_token_with_kid(kid: str, key: rsa.RSAPrivateKey = PRIVATE) -> str:
    return jwt.encode(claims(), key, algorithm="RS256", headers={"kid": kid})


def test_many_unknown_kids_fetch_the_key_set_once_a_minute() -> None:
    fetch, clock = Fetches(jwk_of(PRIVATE)), Ticks()
    verifier = tokens(keys=ThrottledSigningKeys(fetch, clock=clock))
    assert verifier.verify(a_token()).username == STAFF
    assert fetch.count == 1
    for n in range(50):
        with pytest.raises(NotSignedIn):
            verifier.verify(a_token_with_kid(f"made-up-kid-{n}"))
    assert fetch.count == 1  # within a minute of the last fetch: refused without one
    clock.now += KEYS_REFETCH_SECONDS
    for n in range(50):
        with pytest.raises(NotSignedIn):
            verifier.verify(a_token_with_kid(f"made-up-kid-later-{n}"))
    assert fetch.count == 2  # one fetch for the whole minute's unknown kids
    assert verifier.verify(a_token()).username == STAFF  # a known kid never fetches
    assert fetch.count == 2


def test_a_rotated_key_is_fetched_and_the_set_refreshes_hourly() -> None:
    rotated = jwk_of(OTHER, "rotated-key")
    fetch, clock = Fetches(jwk_of(PRIVATE)), Ticks()
    keys = ThrottledSigningKeys(fetch, clock=clock)
    keys.get_signing_key_from_jwt(a_token())
    clock.now += KEYS_REFETCH_SECONDS
    fetch.keys.append(rotated)
    assert keys.get_signing_key_from_jwt(a_token_with_kid("rotated-key", OTHER)).key_id == "rotated-key"
    assert fetch.count == 2
    clock.now += KEYS_LIFESPAN_SECONDS
    keys.get_signing_key_from_jwt(a_token())
    assert fetch.count == 3


def test_a_failed_fetch_is_unavailable_and_not_retried_within_a_minute() -> None:
    fetch, clock = Fetches(jwk_of(PRIVATE)), Ticks()
    fetch.fail = PyJWKClientConnectionError("made-up outage")
    verifier = tokens(keys=ThrottledSigningKeys(fetch, clock=clock))
    for _ in range(5):
        with pytest.raises(SignInUnavailable):
            verifier.verify(a_token())
    assert fetch.count == 1
    fetch.fail = None
    clock.now += KEYS_REFETCH_SECONDS
    assert verifier.verify(a_token()).username == STAFF
    assert fetch.count == 2


def test_a_token_without_a_kid_is_refused_without_a_fetch() -> None:
    fetch = Fetches(jwk_of(PRIVATE))
    verifier = tokens(keys=ThrottledSigningKeys(fetch))
    with pytest.raises(NotSignedIn):
        verifier.verify(jwt.encode(claims(), PRIVATE, algorithm="RS256"))
    with pytest.raises(NotSignedIn):
        verifier.verify("not-a-token")
    assert fetch.count == 0


def test_a_cold_container_retries_the_key_set_after_a_few_seconds() -> None:
    fetch, clock = Fetches(jwk_of(PRIVATE)), Ticks()
    fetch.fail = PyJWKClientConnectionError("made-up outage")
    verifier = tokens(keys=ThrottledSigningKeys(fetch, clock=clock))
    with pytest.raises(SignInUnavailable):
        verifier.verify(a_token())
    fetch.fail = None
    clock.now += KEYS_FIRST_RETRY_SECONDS
    assert verifier.verify(a_token()).username == STAFF
    assert fetch.count == 2


def test_a_failed_refresh_keeps_the_key_set_it_holds() -> None:
    fetch, clock = Fetches(jwk_of(PRIVATE)), Ticks()
    verifier = tokens(keys=ThrottledSigningKeys(fetch, clock=clock))
    verifier.verify(a_token())
    clock.now += KEYS_LIFESPAN_SECONDS
    fetch.fail = PyJWKClientConnectionError("made-up outage")
    assert verifier.verify(a_token()).username == STAFF  # stale but held: still checked
    assert verifier.verify(a_token()).username == STAFF
    assert fetch.count == 2  # the next refresh waits a minute


@pytest.mark.parametrize(
    "failure",
    [
        PyJWKClientError("The JWKS endpoint did not contain any signing keys"),
        PyJWKSetError("made-up malformed key set"),
        ValueError("made-up body that isn't JSON"),
    ],
)
def test_a_refresh_that_reads_a_bad_key_set_keeps_the_set_it_holds(
    failure: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    fetch, clock = Fetches(jwk_of(PRIVATE)), Ticks()
    verifier = tokens(keys=ThrottledSigningKeys(fetch, clock=clock))
    verifier.verify(a_token())
    clock.now += KEYS_LIFESPAN_SECONDS
    fetch.fail = failure
    assert verifier.verify(a_token()).username == STAFF  # the held set still checks it
    assert fetch.count == 2
    [record] = [r for r in caplog.records if r.getMessage() == "jwks_refresh_failed"]
    assert vars(record)["error_code"] == "jwks_unreadable"
    assert_nothing_holds(caplog.records, str(failure))


def test_a_refresh_that_returns_no_keys_keeps_the_set_it_holds() -> None:
    fetch, clock = Fetches(jwk_of(PRIVATE)), Ticks()
    verifier = tokens(keys=ThrottledSigningKeys(fetch, clock=clock))
    verifier.verify(a_token())
    clock.now += KEYS_LIFESPAN_SECONDS
    fetch.keys = []
    assert verifier.verify(a_token()).username == STAFF
    assert fetch.count == 2


def test_a_first_fetch_of_an_empty_key_set_signs_no_one_in() -> None:
    fetch = Fetches()
    verifier = tokens(keys=ThrottledSigningKeys(fetch))
    with pytest.raises(NotSignedIn):
        verifier.verify(a_token())
