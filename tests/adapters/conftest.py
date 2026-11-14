"""Fixtures for the adapters' tests: AWS on moto or on botocore's `Stubber`, never the
real account.

Every AWS fixture sets made-up credentials and us-east-2 and clears any profile first,
so no test can reach an account even by mistake.
"""

import logging
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any

import boto3
import pytest
from moto import mock_aws

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_s3.client import S3Client
else:
    DynamoDBClient = S3Client = Any

TABLE = "asmbly-ceramics-test-records"
BUCKET = "asmbly-ceramics-test-photos"
REGION = "us-east-2"


@pytest.fixture
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")


def create_table(client: DynamoDBClient) -> None:
    """The table phase 7's template makes: `PK`/`SK`, `GSI1` and `GSI2`, all strings."""
    names = ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
    client.create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": name, "AttributeType": "S"} for name in names],
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": index,
                "KeySchema": [
                    {"AttributeName": f"{index}PK", "KeyType": "HASH"},
                    {"AttributeName": f"{index}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for index in ("GSI1", "GSI2")
        ],
    )


@pytest.fixture
def dynamodb(aws_env: None) -> Iterator[DynamoDBClient]:
    with mock_aws():
        client = boto3.client("dynamodb", region_name=REGION)
        create_table(client)
        yield client


@pytest.fixture
def s3(aws_env: None) -> Iterator[S3Client]:
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
        yield client


def a_client(service: str) -> Any:
    """A client for `Stubber`: made-up credentials, us-east-2, no network."""
    return boto3.client(
        service,  # type: ignore[call-overload]  # any service name, for Stubber tests
        region_name=REGION,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


def record_texts(records: Iterable[logging.LogRecord]) -> list[str]:
    """Each record's message and every attribute value, extras included, as text."""
    return [f"{record.getMessage()} {vars(record)!r}" for record in records]


def assert_nothing_holds(records: Iterable[logging.LogRecord], *values: str) -> None:
    """No captured record holds any of `values` (a made-up name, address, token...)."""
    texts = record_texts(records)
    for value in values:
        assert value
        assert not [text for text in texts if value in text]
