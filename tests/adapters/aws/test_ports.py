"""Each adapter satisfies its port: mypy checks these assignments, and the test builds
each one without a network call."""

from asmbly_ceramics.adapters.aws.ids import DynamoDbIdNumbers
from asmbly_ceramics.adapters.aws.mailer import SesMailer
from asmbly_ceramics.adapters.aws.photos import S3PhotoStore
from asmbly_ceramics.adapters.aws.rate_limit import DynamoDbRateLimiter
from asmbly_ceramics.adapters.aws.records import DynamoDbRecords
from asmbly_ceramics.adapters.aws.secrets import SsmSecrets
from asmbly_ceramics.adapters.aws.staff_tokens import CognitoStaffTokens
from asmbly_ceramics.adapters.clock import SystemClock
from asmbly_ceramics.adapters.images import PillowPhotoInspector
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.ids import IdNumbers
from asmbly_ceramics.ports.images import PhotoInspector
from asmbly_ceramics.ports.mailer import Mailer
from asmbly_ceramics.ports.photos import PhotoStore
from asmbly_ceramics.ports.rate_limit import RateLimiter
from asmbly_ceramics.ports.records import Records
from asmbly_ceramics.ports.secrets import Secrets
from asmbly_ceramics.ports.staff import StaffTokens
from tests.adapters.conftest import BUCKET, TABLE, a_client


def test_each_adapter_satisfies_its_port() -> None:
    dynamodb = a_client("dynamodb")
    records: Records = DynamoDbRecords(dynamodb, TABLE)
    ids: IdNumbers = DynamoDbIdNumbers(dynamodb, TABLE)
    limiter: RateLimiter = DynamoDbRateLimiter(dynamodb, TABLE)
    photos: PhotoStore = S3PhotoStore(a_client("s3"), BUCKET)
    inspector: PhotoInspector = PillowPhotoInspector()
    mailer: Mailer = SesMailer(a_client("sesv2"))
    secrets: Secrets = SsmSecrets(a_client("ssm"), "stage")
    clock: Clock = SystemClock()
    tokens: StaffTokens = CognitoStaffTokens(
        issuer="https://cognito-idp.us-east-2.amazonaws.com/us-east-2_MadeUpPool",
        sign_in_origin="https://sign-in.example.org",
        client_id="made-up-client-id",
    )
    assert all((records, ids, limiter, photos, inspector, mailer, secrets, clock, tokens))
