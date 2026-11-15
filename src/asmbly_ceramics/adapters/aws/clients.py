"""The botocore settings phase 7's composition root builds every client with.

botocore's defaults (60 s to connect, 60 s per read, and up to 10 tries for DynamoDB)
outlast API Gateway's 30 s and the web functions' 29 s timeout, so a slow AWS call would
end as a gateway timeout with nothing logged. With these, one call gives up in at most
`TOTAL_MAX_ATTEMPTS * (CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS)` seconds plus
botocore's short backoff (under 30 s), and the adapter logs and raises its port's
error. `READ_TIMEOUT_SECONDS` is per socket read, not for a whole response, so a 10 MB
photo still downloads. A web request's whole bound is `asmbly_ceramics.deadline`, which
every client built here checks before each attempt (`deadline.check_deadline`).

SES is the exception: `mailer.SES_CLIENT_CONFIG` makes one attempt (a retried send may
have been sent twice), with the same connect timeout and a longer read for a large
message.

S3 is addressed virtual-hosted on the regional endpoint
(`https://<bucket>.s3.<region>.amazonaws.com/`): without `addressing_style="virtual"`
botocore presigns a POST to the global `https://<bucket>.s3.amazonaws.com/`, which the
form's CSP `connect-src` (`WebSettings.photo_upload_origin`, phase 6 and 7) doesn't
allow, and which a bucket made outside us-east-1 answers with a 307 redirect for a day or
so after it's created.
"""

from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config

from asmbly_ceramics.adapters.aws.deadline import check_deadline

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_s3.client import S3Client
    from mypy_boto3_sesv2.client import SESV2Client
    from mypy_boto3_ssm.client import SSMClient
else:
    DynamoDBClient = S3Client = SESV2Client = SSMClient = Any

CONNECT_TIMEOUT_SECONDS = 2
READ_TIMEOUT_SECONDS = 4
TOTAL_MAX_ATTEMPTS = 3

CLIENT_CONFIG = Config(
    connect_timeout=CONNECT_TIMEOUT_SECONDS,
    read_timeout=READ_TIMEOUT_SECONDS,
    retries={"total_max_attempts": TOTAL_MAX_ATTEMPTS, "mode": "standard"},
    s3={"addressing_style": "virtual"},
)
"""For the DynamoDB, S3 and SSM clients."""


def dynamodb_client(region: str) -> DynamoDBClient:
    client: DynamoDBClient = boto3.client("dynamodb", region_name=region, config=CLIENT_CONFIG)
    check_deadline(client)
    return client


def s3_client(region: str) -> S3Client:
    client: S3Client = boto3.client("s3", region_name=region, config=CLIENT_CONFIG)
    check_deadline(client)
    return client


def ssm_client(region: str) -> SSMClient:
    client: SSMClient = boto3.client("ssm", region_name=region, config=CLIENT_CONFIG)
    check_deadline(client)
    return client


def ses_client(region: str, config: Config) -> SESV2Client:
    """With `mailer.SES_CLIENT_CONFIG` or `mailer.STREAM_SES_CLIENT_CONFIG`: one attempt."""
    client: SESV2Client = boto3.client("sesv2", region_name=region, config=config)
    check_deadline(client)
    return client


def _stream_ses_config() -> Config:
    # Imported here: `mailer` imports this module's timeouts.
    from asmbly_ceramics.adapters.aws.mailer import STREAM_SES_CLIENT_CONFIG

    return STREAM_SES_CLIENT_CONFIG


@dataclass(frozen=True)
class FormClients:
    dynamodb: DynamoDBClient
    s3: S3Client
    ssm: SSMClient

    @staticmethod
    @cache
    def build(region: str) -> FormClients:
        return FormClients(dynamodb_client(region), s3_client(region), ssm_client(region))


@dataclass(frozen=True)
class MailerClients:
    dynamodb: DynamoDBClient
    s3: S3Client
    ses: SESV2Client

    @staticmethod
    @cache
    def build(region: str) -> MailerClients:
        return MailerClients(
            dynamodb_client(region), s3_client(region), ses_client(region, _stream_ses_config())
        )
