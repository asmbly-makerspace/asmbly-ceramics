"""A web request's deadline: set by `RequestDeadline`, checked before each AWS attempt."""

import asyncio
from typing import Any

import boto3
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from asmbly_ceramics import deadline
from asmbly_ceramics.adapters.aws.clients import CLIENT_CONFIG
from asmbly_ceramics.adapters.aws.deadline import DeadlinePassed, check_deadline, refuse_after_deadline
from asmbly_ceramics.adapters.aws.errors import aws_error_code
from asmbly_ceramics.web.app import RequestDeadline


def test_no_deadline_outside_a_request() -> None:
    assert not deadline.passed()
    refuse_after_deadline()  # the mailer's calls are never refused


def test_the_deadline_passes_after_its_budget() -> None:
    now = [100.0]
    with deadline.request_deadline(20, clock=lambda: now[0]):
        assert not deadline.passed(lambda: now[0])
        now[0] = 119.9
        assert not deadline.passed(lambda: now[0])
        now[0] = 120.0
        assert deadline.passed(lambda: now[0])
    assert not deadline.passed(lambda: now[0])  # reset when the request ends


def test_the_budget_leaves_room_for_one_last_attempt_under_the_timeout() -> None:
    from asmbly_ceramics.adapters.aws.clients import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS

    assert deadline.REQUEST_BUDGET_SECONDS + CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS < 29


@pytest.fixture
def fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")


def test_a_client_sends_nothing_once_the_deadline_has_passed(fake_credentials: None) -> None:
    # A port nobody listens on: if the hook let the request through, it would fail
    # with a connection error instead.
    client = boto3.client(
        "dynamodb", region_name="us-east-2", config=CLIENT_CONFIG, endpoint_url="http://127.0.0.1:9"
    )
    check_deadline(client)
    check_deadline(client)  # registering twice is harmless
    with deadline.request_deadline(-1), pytest.raises(DeadlinePassed) as raised:
        client.get_item(TableName="t", Key={"PK": {"S": "a"}})
    assert aws_error_code(raised.value) == "DeadlinePassed"


def test_each_http_request_runs_under_its_own_deadline() -> None:
    seen: list[bool] = []

    async def page(request: Request) -> PlainTextResponse:
        seen.append(deadline._deadlines.get() is not None)
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", page)])
    app.add_middleware(RequestDeadline, seconds=-1)
    with TestClient(app) as client:
        assert client.get("/").text == "ok"
    assert seen == [True]
    assert not deadline.passed()


def test_other_scopes_pass_straight_through() -> None:
    calls: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        calls.append(scope["type"])
        assert deadline._deadlines.get() is None

    nothing: Any = None
    asyncio.run(RequestDeadline(inner)({"type": "lifespan"}, nothing, nothing))
    assert calls == ["lifespan"]
