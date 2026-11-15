"""After a web request's work deadline, the adapters refuse new work but still clean up.

A submit cut off after keeping photos must still delete them (no photo without a
record, #7; decision 0004): the photo store's delete and the submission's re-read run
under the later cleanup deadline, and a commit refused before sending is
`RecordsUnavailable` (nothing landed), not `CommitOutcomeUnknown`.
"""

from typing import TYPE_CHECKING, Any

import pytest

from asmbly_ceramics import deadline
from asmbly_ceramics.adapters.aws.deadline import check_deadline
from asmbly_ceramics.adapters.aws.photos import S3PhotoStore
from asmbly_ceramics.adapters.aws.records import DynamoDbRecords
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.ports.errors import PhotosUnavailable, RecordsUnavailable
from asmbly_ceramics.ports.records import Put
from tests.adapters.conftest import BUCKET, TABLE
from tests.domain.builders import a_drop_off

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_s3.client import S3Client
else:
    DynamoDBClient = S3Client = Any

KEPT = "dropoffs/AC-7/1.jpg"


def past_work_deadline() -> Any:
    """Inside a request whose work deadline has passed and whose cleanup deadline hasn't."""
    return deadline.request_deadline(seconds=-1, cleanup_seconds=600)


def test_the_cleanup_deadline_comes_after_the_work_deadline() -> None:
    now = [0.0]
    with deadline.request_deadline(clock=lambda: now[0]):
        now[0] = deadline.REQUEST_BUDGET_SECONDS
        assert deadline.passed(lambda: now[0])
        with deadline.cleanup():
            assert not deadline.passed(lambda: now[0])
            now[0] = deadline.CLEANUP_BUDGET_SECONDS
            assert deadline.passed(lambda: now[0])
    from asmbly_ceramics.adapters.aws.clients import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS

    assert deadline.CLEANUP_BUDGET_SECONDS + CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS < 29


def test_kept_photos_are_still_deleted_after_the_work_deadline(s3: S3Client) -> None:
    check_deadline(s3)
    s3.put_object(Bucket=BUCKET, Key=KEPT, Body=b"photo")
    store = S3PhotoStore(s3, BUCKET)
    with past_work_deadline():
        with pytest.raises(PhotosUnavailable):  # new work is refused: DeadlinePassed
            store.read_upload("a" * 22)
        store.delete_drop_off(DropOffId(7))
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="dropoffs/").get("KeyCount") == 0


def test_keep_cut_off_by_the_deadline_cleans_up_and_leaves_nothing_for_the_backstop(
    s3: S3Client, caplog: pytest.LogCaptureFixture
) -> None:
    from asmbly_ceramics.domain.photos import CheckedPhoto

    check_deadline(s3)
    store = S3PhotoStore(s3, BUCKET)
    photo = CheckedPhoto(full=b"full", thumb=b"thumb")
    with past_work_deadline(), pytest.raises(PhotosUnavailable):
        store.keep(DropOffId(7), [photo])
    assert not [r for r in caplog.records if getattr(r, "event", None) == "photos_not_deleted"]
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="dropoffs/").get("KeyCount") == 0


def test_a_commit_refused_by_the_deadline_is_unavailable_and_the_re_read_still_runs(
    dynamodb: DynamoDBClient,
) -> None:
    check_deadline(dynamodb)
    records = DynamoDbRecords(dynamodb, TABLE)
    with past_work_deadline():
        with pytest.raises(RecordsUnavailable) as refused:
            records.commit([Put(a_drop_off(7))])
        assert refused.value.code == "DeadlinePassed"
        assert type(refused.value) is RecordsUnavailable  # not CommitOutcomeUnknown: nothing was sent
        assert records.submission("s" * 43) is None  # the re-read is a cleanup
        with pytest.raises(RecordsUnavailable):
            records.drop_off(DropOffId(7))
    assert records.drop_off(DropOffId(7)) is None


class _AfterFirstAttempt:
    """`deadline.passed` that turns true once the first attempt has been made."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls > 1


def unreachable(service: str) -> Any:
    import boto3

    from asmbly_ceramics.adapters.aws.clients import CLIENT_CONFIG

    client = boto3.client(  # type: ignore[call-overload]
        service,
        region_name="us-east-2",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        config=CLIENT_CONFIG,
        endpoint_url="http://127.0.0.1:9",  # nobody listens: each attempt fails to connect
    )
    check_deadline(client)
    return client


@pytest.mark.parametrize(("header", "number"), [(b"attempt=1; max=3", 1), ("attempt=3; max=3", 3), (None, 2)])
def test_the_attempt_number_comes_from_botocore_s_header(header: Any, number: int) -> None:
    from types import SimpleNamespace

    from asmbly_ceramics.adapters.aws.deadline import attempt

    request = SimpleNamespace(headers={} if header is None else {"amz-sdk-request": header})
    assert attempt(request) == number


def test_a_commit_cut_off_on_a_retry_is_outcome_unknown(
    monkeypatch: pytest.MonkeyPatch, aws_env: None
) -> None:
    from asmbly_ceramics.ports.records import CommitOutcomeUnknown

    monkeypatch.setattr(deadline, "passed", _AfterFirstAttempt())
    records = DynamoDbRecords(unreachable("dynamodb"), TABLE)
    with pytest.raises(CommitOutcomeUnknown) as unknown:
        records.commit([Put(a_drop_off(7))])
    assert unknown.value.code == "DeadlinePassedOnRetry"


def test_keep_cut_off_on_a_retry_leaves_the_photo_for_the_backstop(
    monkeypatch: pytest.MonkeyPatch, aws_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    from asmbly_ceramics.domain.photos import CheckedPhoto

    monkeypatch.setattr(deadline, "passed", _AfterFirstAttempt())
    store = S3PhotoStore(unreachable("s3"), BUCKET)
    with pytest.raises(PhotosUnavailable):
        store.keep(DropOffId(7), [CheckedPhoto(full=b"full", thumb=b"thumb")])
    [left] = [r for r in caplog.records if getattr(r, "event", None) == "photos_not_deleted"]
    assert left.__dict__["drop_off_id"] == "AC-7"


def test_no_retry_sleeps_past_the_deadline(monkeypatch: pytest.MonkeyPatch, aws_env: None) -> None:
    from asmbly_ceramics.adapters.aws.deadline import DeadlinePassedOnRetry, refuse_retry_after_deadline

    sent: list[object] = []
    client = unreachable("dynamodb")
    client.meta.events.register("before-send", lambda **kwargs: sent.append(kwargs), unique_id="spy")
    passed = [False]
    monkeypatch.setattr(deadline, "passed", lambda: passed[0])

    def deadline_passes_after_the_attempt(**kwargs: Any) -> None:
        passed[0] = True

    client.meta.events.register_first("needs-retry", deadline_passes_after_the_attempt, unique_id="flip")
    client.meta.events.unregister("needs-retry", unique_id="asmbly-ceramics-deadline-retry")
    client.meta.events.register_last(
        "needs-retry", refuse_retry_after_deadline, unique_id="asmbly-ceramics-deadline-retry"
    )
    with pytest.raises(DeadlinePassedOnRetry):
        client.get_item(TableName=TABLE, Key={"PK": {"S": "a"}})
    assert len(sent) == 1  # one attempt, then no sleep and no retry


def test_a_success_or_a_refusal_after_the_deadline_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from asmbly_ceramics.adapters.aws.deadline import DeadlinePassedOnRetry, refuse_retry_after_deadline

    monkeypatch.setattr(deadline, "passed", lambda: True)
    ok = SimpleNamespace(status_code=200)
    refused = SimpleNamespace(status_code=400)
    refuse_retry_after_deadline(response=(ok, {}))
    refuse_retry_after_deadline(response=(refused, {"Error": {"Code": "ConditionalCheckFailedException"}}))
    for response in (
        (SimpleNamespace(status_code=500), {}),
        (refused, {"Error": {"Code": "ThrottlingException"}}),
    ):
        with pytest.raises(DeadlinePassedOnRetry):
            refuse_retry_after_deadline(response=response)
    monkeypatch.setattr(deadline, "passed", lambda: False)
    refuse_retry_after_deadline(caught_exception=OSError())


def test_a_cleanup_that_fails_leaves_the_photos_for_the_backstop(
    monkeypatch: pytest.MonkeyPatch, s3: S3Client, caplog: pytest.LogCaptureFixture
) -> None:
    from asmbly_ceramics.domain.photos import CheckedPhoto

    check_deadline(s3)
    store = S3PhotoStore(s3, BUCKET)
    monkeypatch.setattr(store, "_delete", _refuse_delete)
    passed = [False]
    monkeypatch.setattr(deadline, "passed", lambda: passed[0])

    def deadline_passes_after_the_first_put(**kwargs: Any) -> None:
        passed[0] = True

    s3.meta.events.register("after-call.s3.PutObject", deadline_passes_after_the_first_put, unique_id="flip")
    photos = [CheckedPhoto(full=b"full", thumb=b"thumb")]
    with pytest.raises(PhotosUnavailable):
        store.keep(DropOffId(7), photos)
    assert [getattr(r, "event", None) for r in caplog.records].count("photos_not_deleted") == 1


def _refuse_delete(*args: Any) -> None:
    raise PhotosUnavailable("AccessDenied")
