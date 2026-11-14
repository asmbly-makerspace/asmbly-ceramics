"""Across the AWS adapters: a failure is reported by its code, never by AWS's message."""

import logging
from collections.abc import Callable
from typing import Any

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from botocore.stub import Stubber

from asmbly_ceramics.adapters.aws.errors import aws_error_code, retry_attempts
from asmbly_ceramics.adapters.aws.ids import DynamoDbIdNumbers
from asmbly_ceramics.adapters.aws.mailer import SesMailer
from asmbly_ceramics.adapters.aws.photos import S3PhotoStore
from asmbly_ceramics.adapters.aws.rate_limit import DynamoDbRateLimiter
from asmbly_ceramics.adapters.aws.records import DynamoDbRecords
from asmbly_ceramics.adapters.aws.secrets import SsmSecrets
from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import DEVICE_LIMIT
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRef, PhotoSize
from asmbly_ceramics.ports.errors import PortError
from asmbly_ceramics.ports.records import Put
from asmbly_ceramics.ports.secrets import SecretName
from tests.adapters.aws.test_mailer import an_email
from tests.adapters.conftest import BUCKET, TABLE, a_client, assert_nothing_holds
from tests.domain.builders import NOW, TEST_NAME, a_drop_off, an_address

LEAKED = an_address("made.up.leak")
AWS_TEXT = f"Validation failed for an item holding {LEAKED} ({TEST_NAME})"

Case = tuple[str, str, Callable[[Any], Any]]
CASES: list[Case] = [
    ("dynamodb", "transact_write_items", lambda c: DynamoDbRecords(c, TABLE).commit([Put(a_drop_off(1))])),
    ("dynamodb", "get_item", lambda c: DynamoDbRecords(c, TABLE).drop_off(DropOffId(1))),
    ("dynamodb", "query", lambda c: DynamoDbRecords(c, TABLE).drop_offs_in({DropOffState.WAITING})),
    ("dynamodb", "update_item", lambda c: DynamoDbIdNumbers(c, TABLE).next_drop_off_id()),
    ("dynamodb", "get_item", lambda c: DynamoDbRateLimiter(c, TABLE).hit("made-up-hash", DEVICE_LIMIT, NOW)),
    ("s3", "get_object", lambda c: S3PhotoStore(c, BUCKET).read(PhotoRef(DropOffId(1), 1), PhotoSize.FULL)),
    ("s3", "put_object", lambda c: S3PhotoStore(c, BUCKET).discard_uploads(["A" * 22])),
    ("s3", "delete_objects", lambda c: S3PhotoStore(c, BUCKET).delete_drop_off(DropOffId(1))),
    ("sesv2", "send_email", lambda c: SesMailer(c).send(an_email())),
    ("ssm", "get_parameter", lambda c: SsmSecrets(c, "stage").get(SecretName.HASH_KEY)),
]


@pytest.mark.parametrize(("service", "operation", "call"), CASES, ids=[f"{s}-{o}" for s, o, _ in CASES])
def test_adapters_never_log_an_aws_error_message(
    service: str, operation: str, call: Callable[[Any], Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client = a_client(service)
    with Stubber(client) as stubber:
        stubber.add_client_error(
            operation, service_error_code="ValidationException", service_message=AWS_TEXT
        )
        with pytest.raises(PortError) as raised:
            call(client)
        stubber.assert_no_pending_responses()
    # Not a masked `StubAssertionError` (a `BotoCoreError`, which adapters also turn into
    # their port's error).
    assert getattr(raised.value, "code", None) == "ValidationException"
    assert LEAKED not in str(raised.value)
    assert TEST_NAME not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__  # `from None`: no traceback carries the message
    assert_nothing_holds(caplog.records, LEAKED, TEST_NAME)


def test_keep_never_logs_the_message_either(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_client_error("put_object", service_error_code="InternalError", service_message=AWS_TEXT)
        with pytest.raises(PortError):
            S3PhotoStore(client, BUCKET).keep(DropOffId(1), [CheckedPhoto(full=b"F", thumb=b"T")])
    assert_nothing_holds(caplog.records, LEAKED)


def a_client_error(code: Any, **metadata: Any) -> ClientError:
    response: Any = {"Error": {"Code": code, "Message": AWS_TEXT}, "ResponseMetadata": metadata}
    return ClientError(response, "Op")


def test_the_code_is_kept_only_when_it_has_a_codes_shape() -> None:
    assert aws_error_code(a_client_error("ThrottlingException")) == "ThrottlingException"
    assert aws_error_code(a_client_error(LEAKED)) == "unknown"
    assert aws_error_code(a_client_error(None)) == "unknown"
    assert aws_error_code(ClientError({}, "Op")) == "unknown"
    assert aws_error_code(ReadTimeoutError(endpoint_url="https://example.org")) == "ReadTimeoutError"


def test_retry_attempts_reads_botocores_count() -> None:
    assert retry_attempts(a_client_error("X", RetryAttempts=2)) == 2
    assert retry_attempts(a_client_error("X")) == 0
    assert retry_attempts(a_client_error("X", RetryAttempts="2")) == 0
