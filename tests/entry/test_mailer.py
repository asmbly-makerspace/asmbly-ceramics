"""The mailer's handler: each stream record's key to `SendPendingEmail`, and what Lambda retries."""

import logging
from typing import Any

import pytest

from asmbly_ceramics.adapters.aws import keys
from asmbly_ceramics.domain.email import EmailKind, EmailStatus, rejection_occasion
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.entry import mailer
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.settings import SettingsError
from tests.domain.builders import NOW, TEST_EMAIL, TEST_NAME, TEST_PHONE
from tests.use_cases.conftest import World
from tests.use_cases.conftest import world as world  # the fakes and use cases
from tests.use_cases.flows import dropped_off, email_of
from tests.use_cases.test_emails import assert_nothing_personal_logged, on_unknown_claims


class FakeSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[DropOffId, EmailKind, str]] = []
        self.error = error

    def __call__(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str) -> EmailStatus | None:
        self.calls.append((drop_off_id, kind, occasion))
        if self.error is not None:
            raise self.error
        return EmailStatus.SENT


def record(
    number: int, kind: EmailKind = EmailKind.RECEIVED, occasion: str = "", sequence: str = "1"
) -> dict[str, Any]:
    key = keys.email_key(DropOffId(number), kind, occasion)
    return {
        "eventName": "INSERT",
        "dynamodb": {
            "Keys": key,
            # The image holds the person's details; the handler must never read them.
            "NewImage": {
                **key,
                "name": {"S": TEST_NAME},
                "email": {"S": TEST_EMAIL},
                "phone": {"S": TEST_PHONE},
            },
            "SequenceNumber": sequence,
        },
    }


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> FakeSender:
    fake = FakeSender()
    monkeypatch.setattr(mailer, "_sender", fake)
    return fake


def test_each_record_sends_its_email(sender: FakeSender) -> None:
    result = mailer.handler({"Records": [record(12), record(13, sequence="2")]}, None)
    assert result == {"batchItemFailures": []}
    assert sender.calls == [(DropOffId(12), EmailKind.RECEIVED, ""), (DropOffId(13), EmailKind.RECEIVED, "")]


def test_a_crash_reports_the_record_for_retry(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(mailer, "_sender", FakeSender(RuntimeError(TEST_EMAIL)))
    with caplog.at_level(logging.INFO):
        result = mailer.handler({"Records": [record(12, sequence="77")]}, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "77"}]}
    [line] = [r for r in caplog.records if getattr(r, "event", None) == "mailer_crashed"]
    assert line.__dict__["drop_off_id"] == "AC-12"
    assert line.__dict__["error_code"] == "RuntimeError"
    assert TEST_EMAIL not in caplog.text


def test_a_send_failure_is_not_retried_by_lambda(
    monkeypatch: pytest.MonkeyPatch, world: World, caplog: pytest.LogCaptureFixture
) -> None:
    # The real use case on the fakes: SES refuses, the email is marked failed and
    # logged, and Lambda isn't asked to retry (the send may have half happened).
    monkeypatch.setattr(mailer, "_sender", world.send_email)
    drop_off_id = dropped_off(world, 12)
    world.mailer.fail_with = "MessageRejected"
    with caplog.at_level(logging.INFO):
        result = mailer.handler({"Records": [record(drop_off_id.number)]}, None)
    assert result == {"batchItemFailures": []}
    assert email_of(world, drop_off_id, EmailKind.RECEIVED).status is EmailStatus.FAILED
    [failed] = [r for r in caplog.records if getattr(r, "event", None) == "email_failed"]
    assert failed.__dict__["drop_off_id"] == str(drop_off_id)
    assert TEST_EMAIL not in caplog.text


def test_a_pending_email_is_sent_through_the_real_use_case(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    monkeypatch.setattr(mailer, "_sender", world.send_email)
    drop_off_id = dropped_off(world, 13)
    assert mailer.handler({"Records": [record(drop_off_id.number)]}, None) == {"batchItemFailures": []}
    assert email_of(world, drop_off_id, EmailKind.RECEIVED).status is EmailStatus.SENT
    assert len(world.mailer.sent) == 1


def test_a_claim_that_landed_behind_an_unknown_outcome_isnt_retried(
    monkeypatch: pytest.MonkeyPatch, world: World, caplog: pytest.LogCaptureFixture
) -> None:
    records = on_unknown_claims(world)  # AC-1's claim lands, then its commit raises CommitOutcomeUnknown
    monkeypatch.setattr(mailer, "_sender", world.send_email)
    with caplog.at_level(logging.INFO):
        result = mailer.handler({"Records": [record(1, sequence="9")]}, None)
    assert result == {"batchItemFailures": []}
    assert not records.armed  # the claim went through the unknown-outcome path
    [unknown] = [r for r in caplog.records if r.getMessage() == "email_claim_unknown"]
    assert getattr(unknown, "outcome", None) == "held"
    assert email_of(world, DropOffId(1), EmailKind.RECEIVED).status is EmailStatus.SENT
    assert len(world.mailer.sent) == 1
    assert not [r for r in caplog.records if getattr(r, "event", None) == "mailer_crashed"]
    assert_nothing_personal_logged(caplog)


def test_a_claim_that_didnt_land_behind_an_unknown_outcome_is_retried(
    monkeypatch: pytest.MonkeyPatch, world: World, caplog: pytest.LogCaptureFixture
) -> None:
    on_unknown_claims(world).lands = False
    monkeypatch.setattr(mailer, "_sender", world.send_email)
    with caplog.at_level(logging.INFO):
        result = mailer.handler({"Records": [record(1, sequence="9")]}, None)
        assert result == {"batchItemFailures": [{"itemIdentifier": "9"}]}
        assert world.mailer.sent == []
        assert mailer.handler({"Records": [record(1, sequence="9")]}, None) == {"batchItemFailures": []}
    assert len(world.mailer.sent) == 1
    assert_nothing_personal_logged(caplog)


def test_a_record_that_isn_t_an_email_is_logged_and_skipped(
    sender: FakeSender, caplog: pytest.LogCaptureFixture
) -> None:
    stray = {"dynamodb": {"Keys": {"PK": {"S": "DROPOFF#AC-12"}, "SK": {"S": "META"}}, "SequenceNumber": "5"}}
    with caplog.at_level(logging.INFO):
        result = mailer.handler({"Records": [stray, {"dynamodb": None}]}, None)
    assert result == {"batchItemFailures": []}
    assert sender.calls == []
    assert [getattr(r, "event", None) for r in caplog.records].count("mailer_bad_key") == 2
    assert "DROPOFF" not in caplog.text


def test_the_handler_never_reads_personal_fields_from_the_image(sender: FakeSender) -> None:
    occasion = rejection_occasion(NOW)
    event = record(12, EmailKind.REJECTED, occasion)
    event["dynamodb"]["NewImage"] = _Exploding()
    mailer.handler({"Records": [event]}, None)
    assert sender.calls == [(DropOffId(12), EmailKind.REJECTED, occasion)]


class _Exploding(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        raise AssertionError("the handler read the image")

    def get(self, key: str, default: Any = None) -> Any:
        raise AssertionError("the handler read the image")


def test_the_sender_is_built_once_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from asmbly_ceramics import composition, logs
    from tests.test_settings import ENVIRONMENT

    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    built: list[object] = []

    def build_mailer(settings: object) -> object:
        built.append(settings)
        return FakeSender()

    monkeypatch.setattr(mailer, "_sender", None)
    monkeypatch.setattr(composition, "build_mailer", build_mailer)
    monkeypatch.setattr(logs, "configure_logging", lambda level, version: None)
    first = mailer.sender()
    assert mailer.sender() is first
    assert len(built) == 1


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            SettingsError("INITIAL_SENDING_ADDRESS is not an asmbly.org address"),
            "SettingsError.INITIAL_SENDING_ADDRESS",
        ),
        (
            RecordsUnavailable("ProvisionedThroughputExceededException"),
            "ProvisionedThroughputExceededException",
        ),
        (ValueError(f"bad address {TEST_EMAIL} for {TEST_NAME}"), "ValueError"),
    ],
)
def test_a_mailer_that_can_t_start_raises_and_logs_a_code_only(
    error: Exception, code: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Lambda's traceback and the log get a code or the class name, never the text; the
    whole batch is retried."""

    def broken() -> object:
        raise error

    monkeypatch.setattr(mailer, "sender", broken)
    caplog.set_level(logging.INFO)

    with pytest.raises(mailer.MailerStartFailed) as raised:
        mailer.handler({"Records": [record(12)]}, None)

    assert raised.value.code == code
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    for text in (str(raised.value), repr(vars(raised.value)), caplog.text):
        assert TEST_NAME not in text
        assert TEST_EMAIL not in text
    [logged] = [r for r in caplog.records if r.getMessage() == "mailer_start_failed"]
    assert logged.levelno == logging.ERROR
    assert vars(logged)["error_code"] == code
