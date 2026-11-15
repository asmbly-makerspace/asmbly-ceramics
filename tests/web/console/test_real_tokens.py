"""The console's per-request check through phase 4's real verifier (`CognitoStaffTokens`
on a `ThrottledSigningKeys`), with tokens signed by an RSA key made in the test and a
local key set: no network."""

import base64
import json
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from starlette.testclient import TestClient

from asmbly_ceramics.adapters.aws.staff_tokens import CognitoStaffTokens, ThrottledSigningKeys
from asmbly_ceramics.ports.secrets import SecretName
from asmbly_ceramics.web.app import create_app
from asmbly_ceramics.web.console.session import SESSION_COOKIE, seal_session
from tests.adapters.aws.test_staff_tokens import (
    CLIENT_ID,
    ISSUER,
    KID,
    ORIGIN,
    OTHER,
    PRIVATE,
    claims,
    jwk_of,
)
from tests.domain.builders import STAFF
from tests.use_cases.conftest import World
from tests.web.conftest import SITE
from tests.web.console.conftest import console_services, console_settings


@pytest.fixture
def client(world: World) -> Iterator[TestClient]:
    tokens = CognitoStaffTokens(
        issuer=ISSUER,
        sign_in_origin=ORIGIN,
        client_id=CLIENT_ID,
        keys=ThrottledSigningKeys(lambda: [jwk_of(PRIVATE)]),
    )
    services = replace(console_services(world), staff_tokens=tokens)
    with TestClient(create_app(None, console_settings(world), services), base_url=SITE) as test_client:
        yield test_client


def signed(key: Any = PRIVATE, algorithm: str = "RS256", kid: str = KID, **overrides: Any) -> str:
    named = {k.replace("__", ":"): v for k, v in overrides.items()}
    return jwt.encode(claims(**named), key, algorithm=algorithm, headers={"kid": kid})


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unsigned() -> str:
    header = b64(json.dumps({"alg": "none", "typ": "JWT", "kid": KID}).encode())
    return f"{header}.{b64(json.dumps(claims()).encode())}."


def hs256_with_the_public_key() -> str:
    public = PRIVATE.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    body = b64(json.dumps(claims()).encode())
    import hashlib
    import hmac

    mac = hmac.new(public, f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{b64(mac)}"


def sealed(world: World, token: str) -> str:
    return seal_session(token, world.secrets.get(SecretName.SESSION_KEY))


def answer(client: TestClient, world: World, token: str) -> int:
    client.cookies.set(SESSION_COOKIE, sealed(world, token))
    return client.get("/console", follow_redirects=False).status_code


def test_a_valid_id_token_is_accepted(client: TestClient, world: World) -> None:
    client.cookies.set(SESSION_COOKIE, sealed(world, signed()))
    page = client.get("/console", follow_redirects=False)
    assert page.status_code == 200
    assert f"Signed in as <strong>{STAFF}</strong>" in page.text


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(
            lambda: signed(iss="https://cognito-idp.us-east-2.amazonaws.com/us-east-2_Other"), id="wrong-iss"
        ),
        pytest.param(lambda: signed(aud="made-up-other-client"), id="another-client"),
        pytest.param(lambda: signed(token_use="access"), id="access-token"),
        pytest.param(lambda: signed(exp=int(time.time()) - 120), id="expired"),
        pytest.param(lambda: signed(key=OTHER), id="bad-signature"),
        pytest.param(lambda: signed(kid="made-up-unknown-kid"), id="key-not-in-the-set"),
        pytest.param(unsigned, id="alg-none"),
        pytest.param(hs256_with_the_public_key, id="hs256-with-the-public-key"),
    ],
)
def test_a_token_that_doesn_t_verify_is_refused_and_cleared(
    client: TestClient, world: World, token: Any
) -> None:
    client.cookies.set(SESSION_COOKIE, sealed(world, token()))
    response = client.get("/console/drop-offs/AC-1", follow_redirects=False)
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.headers["location"]).query)["next"] == ["/console/drop-offs/AC-1"]
    assert "max-age=0" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize("groups", [["front-desk"], [], None])
def test_a_valid_token_outside_the_group_is_not_allowed(
    client: TestClient, world: World, groups: Any
) -> None:
    assert answer(client, world, signed(cognito__groups=groups)) == 403


def test_a_valid_token_sealed_with_another_environment_s_key_is_no_session(
    client: TestClient, world: World
) -> None:
    """Stage and prod share the client; each has its own session key."""
    token = signed()
    client.cookies.set(SESSION_COOKIE, seal_session(token, b"another-environment-key-0123456789"))
    assert client.get("/console", follow_redirects=False).status_code == 302
    client.cookies.set(SESSION_COOKIE, token)  # the bare token, unsealed
    assert client.get("/console", follow_redirects=False).status_code == 302
    assert answer(client, world, token) == 200


def test_the_real_sign_in_address_asks_for_openid_only_with_pkce(client: TestClient) -> None:
    response = client.get("/console/auth/sign-in", follow_redirects=False)
    location = response.headers["location"]
    assert location.startswith(f"{ORIGIN}/oauth2/authorize?")
    query = parse_qs(urlsplit(location).query)
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [f"{SITE}/console/auth/callback"]
