"""The composition root builds each function's use cases on stubbed AWS clients."""

import base64
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from asmbly_ceramics.adapters.aws.clients import (
    CLIENT_CONFIG,
    CONNECT_TIMEOUT_SECONDS,
    CloserClients,
    ConsoleClients,
    FormClients,
    MailerClients,
)
from asmbly_ceramics.adapters.aws.photos import S3PhotoStore
from asmbly_ceramics.composition import build_form_services, build_mailer
from asmbly_ceramics.settings import Settings
from asmbly_ceramics.use_cases.emails import SendPendingEmail
from asmbly_ceramics.use_cases.firing_log import FiringLog
from asmbly_ceramics.use_cases.loads import CorrectStepTime, SaveFiringRecord
from asmbly_ceramics.web.app import WebServices
from tests.test_settings import ENVIRONMENT

KEY = base64.b64encode(bytes(range(32))).decode()  # a made-up value, built in code
SETTINGS = Settings.from_environment(ENVIRONMENT)


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")


@pytest.fixture
def form_clients() -> Iterator[tuple[FormClients, Stubber]]:
    region = SETTINGS.region
    clients = FormClients(
        boto3.client("dynamodb", region_name=region, config=CLIENT_CONFIG),
        boto3.client("s3", region_name=region, config=CLIENT_CONFIG),
        boto3.client("ssm", region_name=region, config=CLIENT_CONFIG),
    )
    with Stubber(clients.ssm) as ssm:
        yield clients, ssm


@pytest.fixture
def console_clients() -> Iterator[tuple[ConsoleClients, Stubber]]:
    region = SETTINGS.region
    clients = ConsoleClients(
        boto3.client("dynamodb", region_name=region, config=CLIENT_CONFIG),
        boto3.client("s3", region_name=region, config=CLIENT_CONFIG),
        boto3.client("ssm", region_name=region, config=CLIENT_CONFIG),
        boto3.client("sesv2", region_name=region),
    )
    with Stubber(clients.ssm) as ssm:
        yield clients, ssm


def test_form_services_build_on_stubbed_clients(form_clients: tuple[FormClients, Stubber]) -> None:
    clients, ssm = form_clients
    ssm.add_response(
        "get_parameter",
        {"Parameter": {"Value": KEY}},
        {"Name": "/asmbly-ceramics/stage/form-key", "WithDecryption": True},
    )
    services, web_settings = build_form_services(SETTINGS, clients)
    ssm.assert_no_pending_responses()
    assert isinstance(services, WebServices)
    assert len(web_settings.cookie_key) == 32
    assert web_settings.site_url == SETTINGS.site_url
    assert web_settings.version == SETTINGS.version
    # The S3 client presigns to the host the form's CSP allows.
    slot = S3PhotoStore(clients.s3, SETTINGS.photo_bucket).upload_slots(1, datetime.now(UTC))[0]
    assert slot.post.url.startswith(web_settings.photo_upload_origin)


def test_the_mailer_builds() -> None:
    sender = build_mailer(SETTINGS, MailerClients.build(SETTINGS.region))
    assert isinstance(sender, SendPendingEmail)
    config: Any = MailerClients.build(SETTINGS.region).ses.meta.config
    assert config.read_timeout == 30
    assert config.retries == {"total_max_attempts": 1, "mode": "standard"}
    assert config.connect_timeout == CONNECT_TIMEOUT_SECONDS


@pytest.mark.parametrize("bundle", [FormClients, ConsoleClients, MailerClients, CloserClients])
def test_every_built_client_stops_at_the_deadline(
    bundle: type[FormClients] | type[ConsoleClients] | type[MailerClients] | type[CloserClients],
) -> None:
    from asmbly_ceramics import deadline
    from asmbly_ceramics.adapters.aws.deadline import DeadlinePassed

    clients = bundle.build("us-east-2")
    calls: dict[str, Any] = {
        "dynamodb": lambda c: c.get_item(TableName="t", Key={"PK": {"S": "a"}}),
        "s3": lambda c: c.list_objects_v2(Bucket="b"),
        "ssm": lambda c: c.get_parameter(Name="/n"),
        "ses": lambda c: c.get_account(),
    }
    for name, call in calls.items():
        if hasattr(clients, name):
            with deadline.request_deadline(-1, cleanup_seconds=-1), pytest.raises(DeadlinePassed):
                call(getattr(clients, name))


def test_the_mailer_never_seeds_the_studio() -> None:
    from asmbly_ceramics.use_cases.studio import StudioNotSeeded

    clients = MailerClients(
        boto3.client("dynamodb", region_name="us-east-2", config=CLIENT_CONFIG),
        boto3.client("s3", region_name="us-east-2", config=CLIENT_CONFIG),
        boto3.client("sesv2", region_name="us-east-2"),
    )
    sender = build_mailer(SETTINGS, clients)
    with Stubber(clients.dynamodb) as dynamodb:
        dynamodb.add_response("get_item", {})  # no studio stored; no transaction may follow
        with pytest.raises(StudioNotSeeded):
            sender._studio()
        dynamodb.assert_no_pending_responses()


def test_the_clients_are_built_once_per_container() -> None:
    assert FormClients.build("us-east-2") is FormClients.build("us-east-2")
    assert MailerClients.build("us-east-2") is MailerClients.build("us-east-2")
    assert ConsoleClients.build("us-east-2") is ConsoleClients.build("us-east-2")
    assert CloserClients.build("us-east-2") is CloserClients.build("us-east-2")


def test_the_console_s_test_email_client_tries_once_within_a_request() -> None:
    config: Any = ConsoleClients.build(SETTINGS.region).ses.meta.config
    assert config.retries == {"total_max_attempts": 1, "mode": "standard"}
    assert config.read_timeout < 29  # inside the console function's timeout


def test_the_closer_builds_and_never_seeds_the_studio() -> None:
    from asmbly_ceramics.composition import build_closer
    from asmbly_ceramics.use_cases.close import CloseFinished
    from asmbly_ceramics.use_cases.studio import StudioNotSeeded

    clients = CloserClients(
        boto3.client("dynamodb", region_name="us-east-2", config=CLIENT_CONFIG),
        boto3.client("s3", region_name="us-east-2", config=CLIENT_CONFIG),
    )
    closer = build_closer(SETTINGS, clients)
    assert isinstance(closer, CloseFinished)
    with Stubber(clients.dynamodb) as dynamodb:
        dynamodb.add_response("get_item", {})
        with pytest.raises(StudioNotSeeded):
            closer._studio()
        dynamodb.assert_no_pending_responses()


def test_the_entry_points_never_import_the_local_fakes_app() -> None:
    code = (
        "import sys, asmbly_ceramics.composition, asmbly_ceramics.entry.mailer, asmbly_ceramics.entry.close\n"
        "import asmbly_ceramics.web.app\n"
        "assert 'asmbly_ceramics.web.local' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 (a fixed command)


def test_console_services_build_on_stubbed_clients_reading_only_the_session_key(
    console_clients: tuple[ConsoleClients, Stubber],
) -> None:
    from asmbly_ceramics.adapters.aws.staff_tokens import CognitoStaffTokens
    from asmbly_ceramics.composition import build_console_services
    from asmbly_ceramics.settings import StaffSignIn
    from asmbly_ceramics.web.console import ConsoleServices
    from tests.test_settings import STAFF_ENVIRONMENT

    clients, ssm = console_clients
    ssm.add_response(
        "get_parameter",
        {"Parameter": {"Value": KEY}},
        {"Name": "/asmbly-ceramics/stage/session-key", "WithDecryption": True},
    )
    staff = StaffSignIn.from_environment(STAFF_ENVIRONMENT)
    services, web_settings = build_console_services(SETTINGS, staff, clients)
    ssm.assert_no_pending_responses()
    assert isinstance(services, ConsoleServices)
    assert isinstance(services.staff_tokens, CognitoStaffTokens)
    assert isinstance(services.save_firing_record, SaveFiringRecord)
    assert isinstance(services.correct_step_time, CorrectStepTime)
    assert isinstance(services.firing_log, FiringLog)
    assert services.site_url == SETTINGS.site_url
    assert services.callback_url == SETTINGS.site_url + "/console/auth/callback"
    assert services.signed_out_url == SETTINGS.site_url + "/console/signed-out"
    assert web_settings.cookie_key == bytes(range(32))  # the session key, read at start
    sign_in = services.staff_tokens.sign_in_url(
        state="s", code_challenge="c", redirect_uri=services.callback_url
    )
    assert sign_in.startswith(STAFF_ENVIRONMENT["STAFF_SIGN_IN_URL"] + "/oauth2/authorize?")


def test_the_console_refuses_to_start_without_its_staff_values(monkeypatch: pytest.MonkeyPatch) -> None:
    from asmbly_ceramics.composition import build_console_services
    from asmbly_ceramics.settings import SettingsError

    for name in ("STAFF_ISSUER", "STAFF_SIGN_IN_URL", "STAFF_CLIENT_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SettingsError, match="STAFF_ISSUER"):
        build_console_services(SETTINGS)


def test_the_console_app_has_no_form_route(
    console_clients: tuple[ConsoleClients, Stubber], monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.testclient import TestClient

    from asmbly_ceramics import composition
    from tests.test_settings import STAFF_ENVIRONMENT

    clients, ssm = console_clients
    ssm.add_response("get_parameter", {"Parameter": {"Value": KEY}})
    for name, value in STAFF_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ConsoleClients, "build", lambda region: clients)
    app = composition.console_app(SETTINGS)
    with TestClient(app, base_url=SETTINGS.site_url) as client:
        assert client.get("/", follow_redirects=False).status_code == 404
        assert client.get("/console", follow_redirects=False).status_code == 302
