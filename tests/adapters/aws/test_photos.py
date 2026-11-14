"""`S3PhotoStore`'s requests and failures, on `Stubber` and moto."""

import base64
import json
import logging
from typing import TYPE_CHECKING, Any

import pytest
from botocore.exceptions import ReadTimeoutError
from botocore.stub import ANY, Stubber

from asmbly_ceramics.adapters.aws.clients import CLIENT_CONFIG
from asmbly_ceramics.adapters.aws.photos import (
    PHOTO_INDEXES_EVER,
    S3PhotoStore,
    all_photo_keys,
    upload_key,
    used_key,
)
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import PHOTO_MAX_BYTES, PHOTOS_MAX
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRef, PhotoSize
from asmbly_ceramics.ports.errors import PhotosUnavailable
from asmbly_ceramics.ports.photos import PhotosAlreadyKept, UploadMissing
from tests.adapters.conftest import BUCKET, REGION, a_client, assert_nothing_holds
from tests.domain.builders import NOW, TEST_EMAIL

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client
else:
    S3Client = Any

AC12 = DropOffId(12)
SLOT = "A" * 22
AWS_TEXT = "Access denied for an object uploaded by " + TEST_EMAIL


def photo(n: int) -> CheckedPhoto:
    return CheckedPhoto(full=b"FULL-%d" % n, thumb=b"THUMB-%d" % n)


def a_put(key: str, body: bytes) -> dict[str, Any]:
    return {"Bucket": BUCKET, "Key": key, "Body": body, "ContentType": "image/jpeg", "IfNoneMatch": "*"}


def test_upload_slots_sign_exact_key_size_and_type_conditions() -> None:
    client = a_client("s3", CLIENT_CONFIG)
    [slot] = S3PhotoStore(client, BUCKET).upload_slots(1, NOW)
    fields = dict(slot.post.fields)
    policy = json.loads(base64.b64decode(fields["policy"]))
    conditions = policy["conditions"]
    assert {"key": upload_key(slot.slot_id)} in conditions  # exactly one key
    assert ["content-length-range", 1, PHOTO_MAX_BYTES] in conditions  # 1 byte to 10 MB
    assert ["starts-with", "$Content-Type", "image/"] in conditions
    assert {"success_action_status": "204"} in conditions
    assert {"bucket": BUCKET} in conditions
    assert fields["key"] == upload_key(slot.slot_id)
    assert fields["success_action_status"] == "204"
    assert "x-amz-signature" in fields
    # The regional virtual-hosted host the form's CSP `connect-src` allows (phase 6, 7).
    assert slot.post.url == f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"
    # Signed for UPLOAD_SLOT_LIFETIME (900 seconds) from when it was signed.
    assert policy["expiration"].endswith("Z")


def test_upload_slots_sign_for_900_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = a_client("s3")
    seen: list[int] = []
    original = client.generate_presigned_post

    def spy(**kwargs: Any) -> Any:
        seen.append(kwargs["ExpiresIn"])
        return original(**kwargs)

    monkeypatch.setattr(client, "generate_presigned_post", spy)
    S3PhotoStore(client, BUCKET).upload_slots(3, NOW)
    assert seen == [900, 900, 900]


def listed(*keys: str) -> dict[str, Any]:
    return {"Contents": [{"Key": key} for key in keys], "KeyCount": len(keys)}


LIST_REQUEST = {"Bucket": BUCKET, "Prefix": f"uploads/{SLOT}/", "MaxKeys": 10}


def test_read_upload_missing_object_is_upload_missing() -> None:
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_response("list_objects_v2", listed(), LIST_REQUEST)
        with pytest.raises(UploadMissing):
            S3PhotoStore(client, BUCKET).read_upload(SLOT)
        stubber.assert_no_pending_responses()  # no GET of a key the listing didn't show


def test_a_403_is_never_read_as_absent() -> None:
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_client_error("list_objects_v2", service_error_code="AccessDenied", http_status_code=403)
        stubber.add_response("list_objects_v2", listed(upload_key(SLOT)))
        stubber.add_client_error("get_object", service_error_code="AccessDenied", http_status_code=403)
        store = S3PhotoStore(client, BUCKET)
        for _ in range(2):
            with pytest.raises(PhotosUnavailable) as raised:
                store.read_upload(SLOT)
            assert raised.value.code == "AccessDenied"


def test_read_upload_of_a_discarded_slot_is_upload_missing() -> None:
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_response("list_objects_v2", listed(upload_key(SLOT), used_key(SLOT)), LIST_REQUEST)
        with pytest.raises(UploadMissing):
            S3PhotoStore(client, BUCKET).read_upload(SLOT)
        stubber.assert_no_pending_responses()


def test_read_upload_asks_for_one_byte_over_the_limit_and_refuses_a_larger_object() -> None:
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_response("list_objects_v2", listed(upload_key(SLOT)))
        stubber.add_response(
            "get_object",
            {"ContentRange": f"bytes 0-{PHOTO_MAX_BYTES}/{PHOTO_MAX_BYTES + 1}"},
            {"Bucket": BUCKET, "Key": upload_key(SLOT), "Range": f"bytes=0-{PHOTO_MAX_BYTES}"},
        )
        with pytest.raises(UploadMissing):
            S3PhotoStore(client, BUCKET).read_upload(SLOT)
        stubber.assert_no_pending_responses()


def test_a_malformed_slot_id_is_never_sent_to_s3() -> None:
    client = a_client("s3")
    with Stubber(client):  # no response queued: any call would fail
        store = S3PhotoStore(client, BUCKET)
        for bad in ("../../dropoffs/AC-1", "A" * 21, "A" * 22 + "\n", "A" * 21 + "/"):
            with pytest.raises(UploadMissing):
                store.read_upload(bad)
        store.discard_uploads(["../../dropoffs/AC-1", "A" * 23])
        with pytest.raises(TypeError):
            store.discard_uploads(SLOT)


def test_discard_uploads_marks_the_slot_used_and_deletes_the_upload() -> None:
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_response("put_object", {}, {"Bucket": BUCKET, "Key": used_key(SLOT), "Body": b""})
        stubber.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": upload_key(SLOT)})
        S3PhotoStore(client, BUCKET).discard_uploads([SLOT])
        stubber.add_client_error("put_object", service_error_code="SlowDown", http_status_code=503)
        with pytest.raises(PhotosUnavailable) as raised:
            S3PhotoStore(client, BUCKET).discard_uploads([SLOT])
        stubber.assert_no_pending_responses()
    assert raised.value.code == "SlowDown"


def test_keep_writes_full_and_thumbnail_with_if_none_match_and_leaves_the_uploads() -> None:
    client = a_client("s3")
    with Stubber(client) as stubber:
        for n in (1, 2):
            stubber.add_response("put_object", {}, a_put(f"dropoffs/AC-12/{n}.jpg", b"FULL-%d" % n))
            stubber.add_response("put_object", {}, a_put(f"dropoffs/AC-12/{n}-thumb.jpg", b"THUMB-%d" % n))
        refs = S3PhotoStore(client, BUCKET).keep(AC12, [photo(1), photo(2)])
        stubber.assert_no_pending_responses()  # no delete of any upload
    assert refs == (PhotoRef(AC12, 1), PhotoRef(AC12, 2))


@pytest.mark.parametrize(
    ("code", "status"), [("PreconditionFailed", 412), ("ConditionalRequestConflict", 409)]
)
def test_keep_precondition_failed_is_photos_already_kept_and_deletes_only_its_own_writes(
    code: str, status: int
) -> None:
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_response("put_object", {})  # 1.jpg
        stubber.add_response("put_object", {})  # 1-thumb.jpg
        stubber.add_client_error(
            "put_object", service_error_code=code, http_status_code=status
        )  # 2.jpg exists
        stubber.add_response(
            "delete_objects",
            {},
            {
                "Bucket": BUCKET,
                "Delete": {
                    "Objects": [{"Key": "dropoffs/AC-12/1.jpg"}, {"Key": "dropoffs/AC-12/1-thumb.jpg"}],
                    "Quiet": True,
                },
            },
        )
        with pytest.raises(PhotosAlreadyKept):
            S3PhotoStore(client, BUCKET).keep(AC12, [photo(1), photo(2)])
        # A delete of other keys fails Stubber's check with a `BotoCoreError`, which the
        # cleanup suppresses: only the queue still holding the delete shows it.
        stubber.assert_no_pending_responses()


def test_keep_failure_cleans_up_what_it_wrote() -> None:
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_response("put_object", {})
        stubber.add_client_error("put_object", service_error_code="SlowDown", http_status_code=503)
        stubber.add_response(
            "delete_objects", {}, {"Bucket": BUCKET, "Delete": {"Objects": [{"Key": ANY}], "Quiet": True}}
        )
        with pytest.raises(PhotosUnavailable) as raised:
            S3PhotoStore(client, BUCKET).keep(AC12, [photo(1)])
        stubber.assert_no_pending_responses()  # the cleanup's delete was sent as expected
    assert raised.value.code == "SlowDown"


def test_keep_onto_a_kept_photo_deletes_only_its_own_writes_on_moto(s3: S3Client) -> None:
    s3.put_object(Bucket=BUCKET, Key="dropoffs/AC-12/2.jpg", Body=b"KEPT-BEFORE")
    with pytest.raises(PhotosAlreadyKept):
        S3PhotoStore(s3, BUCKET).keep(AC12, [photo(1), photo(2)])
    left = s3.list_objects_v2(Bucket=BUCKET, Prefix="dropoffs/AC-12/")
    assert [item["Key"] for item in left.get("Contents", [])] == ["dropoffs/AC-12/2.jpg"]
    kept = s3.get_object(Bucket=BUCKET, Key="dropoffs/AC-12/2.jpg")["Body"].read()
    assert kept == b"KEPT-BEFORE"  # neither overwritten nor deleted


def test_keep_network_failure_cleans_up_and_a_failed_cleanup_still_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    client = a_client("s3")
    calls: list[str] = []

    def put(**kwargs: Any) -> None:
        calls.append(kwargs["Key"])
        if len(calls) == 2:
            raise ReadTimeoutError(endpoint_url="https://s3.us-east-2.amazonaws.com")

    def delete(**kwargs: Any) -> dict[str, Any]:
        return {"Errors": [{"Key": "dropoffs/AC-12/1.jpg", "Code": "AccessDenied", "Message": AWS_TEXT}]}

    client.put_object = put  # a stand-in for the network
    client.delete_objects = delete
    with pytest.raises(PhotosUnavailable) as raised:
        S3PhotoStore(client, BUCKET).keep(AC12, [photo(1)])
    assert raised.value.code == "ReadTimeoutError"
    [event] = [r for r in caplog.records if vars(r).get("event") == "photos_not_deleted"]
    assert vars(event)["drop_off_id"] == "AC-12"
    assert_nothing_holds(caplog.records, AWS_TEXT, TEST_EMAIL)


def test_delete_drop_off_deletes_the_twelve_keys_in_one_call_without_listing() -> None:
    client = a_client("s3")
    keys = all_photo_keys(AC12)
    assert len(keys) == 12
    assert "dropoffs/AC-12/6-thumb.jpg" in keys
    with Stubber(client) as stubber:
        stubber.add_response(
            "delete_objects",
            {"Deleted": []},
            {"Bucket": BUCKET, "Delete": {"Objects": [{"Key": key} for key in keys], "Quiet": True}},
        )
        S3PhotoStore(client, BUCKET).delete_drop_off(AC12)
        stubber.assert_no_pending_responses()


def test_delete_drop_off_covers_every_index_ever_allowed_not_todays_limit() -> None:
    # Built from PHOTO_INDEXES_EVER, so a lower PHOTOS_MAX later still deletes an older
    # drop-off's sixth photo; raise it with PHOTOS_MAX, never lower it.
    assert PHOTOS_MAX <= PHOTO_INDEXES_EVER
    assert len(all_photo_keys(AC12)) == 2 * PHOTO_INDEXES_EVER
    assert f"dropoffs/AC-12/{PHOTO_INDEXES_EVER}-thumb.jpg" in all_photo_keys(AC12)


def test_delete_drop_off_with_nothing_left_succeeds(s3: S3Client) -> None:
    S3PhotoStore(s3, BUCKET).delete_drop_off(AC12)


def test_a_per_key_delete_error_is_photos_unavailable_with_its_code(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_response(
            "delete_objects",
            {"Errors": [{"Key": "dropoffs/AC-12/1.jpg", "Code": "AccessDenied", "Message": AWS_TEXT}]},
        )
        with pytest.raises(PhotosUnavailable) as raised:
            S3PhotoStore(client, BUCKET).delete_drop_off(AC12)
    assert raised.value.code == "AccessDenied"
    [record] = [r for r in caplog.records if vars(r).get("event") == "aws_call_failed"]
    assert (vars(record)["drop_off_id"], vars(record)["error_code"]) == ("AC-12", "AccessDenied")
    assert_nothing_holds(caplog.records, AWS_TEXT)


def test_read_of_a_gone_photo_is_upload_missing_and_an_outage_is_unavailable() -> None:
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
        stubber.add_client_error("get_object", service_error_code="InternalError", http_status_code=500)
        store = S3PhotoStore(client, BUCKET)
        with pytest.raises(UploadMissing):
            store.read(PhotoRef(AC12, 1), PhotoSize.THUMB)
        with pytest.raises(PhotosUnavailable) as raised:
            store.read(PhotoRef(AC12, 1), PhotoSize.FULL)
        stubber.assert_no_pending_responses()
    assert raised.value.code == "InternalError"


def test_no_object_key_or_upload_id_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="asmbly_ceramics")
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "list_objects_v2", service_error_code="InternalError", service_message=AWS_TEXT
        )
        stubber.add_response("list_objects_v2", listed(upload_key(SLOT)))
        stubber.add_client_error("get_object", service_error_code="InternalError", service_message=AWS_TEXT)
        store = S3PhotoStore(client, BUCKET)
        for _ in range(2):
            with pytest.raises(PhotosUnavailable):
                store.read_upload(SLOT)
    assert caplog.records
    assert_nothing_holds(caplog.records, SLOT, "uploads/", AWS_TEXT, TEST_EMAIL)


def test_a_put_answered_after_a_retry_is_left_for_the_backstop(caplog: pytest.LogCaptureFixture) -> None:
    # A retried put that landed the first time answers 412 for its own object: not
    # "already kept", and not deleted (it can't be told from a photo kept before).
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    client = a_client("s3")
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "put_object",
            service_error_code="PreconditionFailed",
            http_status_code=412,
            response_meta={"RetryAttempts": 1},
        )
        with pytest.raises(PhotosUnavailable):
            S3PhotoStore(client, BUCKET).keep(AC12, [photo(1)])
        stubber.assert_no_pending_responses()
    [event] = [r for r in caplog.records if vars(r).get("event") == "photos_not_deleted"]
    assert (vars(event)["drop_off_id"], vars(event)["error_code"]) == ("AC-12", "PreconditionFailed")


def test_a_403_on_read_lists_the_prefix_to_tell_gone_from_denied() -> None:
    client = a_client("s3")
    ref = PhotoRef(AC12, 2)
    with Stubber(client) as stubber:
        stubber.add_client_error("get_object", service_error_code="AccessDenied", http_status_code=403)
        stubber.add_response(
            "list_objects_v2",
            listed("dropoffs/AC-12/1.jpg"),
            {"Bucket": BUCKET, "Prefix": "dropoffs/AC-12/", "MaxKeys": 20},
        )
        stubber.add_client_error("get_object", service_error_code="AccessDenied", http_status_code=403)
        stubber.add_response("list_objects_v2", listed("dropoffs/AC-12/2.jpg"))
        store = S3PhotoStore(client, BUCKET)
        with pytest.raises(UploadMissing):
            store.read(ref, PhotoSize.FULL)  # gone
        with pytest.raises(PhotosUnavailable) as raised:
            store.read(ref, PhotoSize.FULL)  # there, but denied
        stubber.assert_no_pending_responses()
    assert raised.value.code == "AccessDenied"
