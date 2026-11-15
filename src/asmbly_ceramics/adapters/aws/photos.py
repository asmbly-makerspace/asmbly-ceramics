"""`PhotoStore` on one private S3 bucket.

Layout: a browser uploads to `uploads/<slot id>/0` through a presigned POST whose policy
allows that one key, 1 byte to `PHOTO_MAX_BYTES`, and a `Content-Type` starting
`image/`; `uploads/<slot id>/used` marks a slot used up. Kept photos are
`dropoffs/AC-n/<k>.jpg` and `dropoffs/AC-n/<k>-thumb.jpg`. Keys never hold anything a
person typed, and the slot ID (a bearer handle) is never logged.

Without `s3:ListBucket` S3 answers 403, not 404, for a missing key, so a 403 is never
read as "absent" by itself. A prefix-conditioned `s3:ListBucket` grant doesn't turn a
GET's 403 into 404 (a GET has no prefix), so the store lists instead: `read_upload`
lists the slot's prefix (the form role gets `s3:ListBucket` with `s3:prefix`
`uploads/*`), and `read` lists the drop-off's prefix after a 403 (the console and mailer
roles get it with `s3:prefix` `dropoffs/*`); a key the listing doesn't show is missing.

A retried `PutObject` that landed the first time answers 412 for its own object, so
`keep` reads a 412 after a retry (`RetryAttempts > 0`), or a network error, as an unknown
outcome: that photo is left for the backstop (#19) and logged as `photos_not_deleted`.
"""

import logging
import secrets
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from botocore.exceptions import BotoCoreError, ClientError

from asmbly_ceramics import deadline
from asmbly_ceramics.adapters.aws.deadline import DeadlinePassed
from asmbly_ceramics.adapters.aws.errors import aws_error_code, log_aws_error, retry_attempts
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import PHOTO_MAX_BYTES, UPLOAD_SLOT_LIFETIME
from asmbly_ceramics.domain.photos import (
    CheckedPhoto,
    PhotoRef,
    PhotoSize,
    PresignedPost,
    UploadSlot,
    is_photo_count,
    is_slot_id,
)
from asmbly_ceramics.ports.errors import PhotosUnavailable
from asmbly_ceramics.ports.photos import PhotosAlreadyKept, UploadMissing
from asmbly_ceramics.use_cases.log import log_event

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef
else:
    S3Client = Any
    ObjectIdentifierTypeDef = dict

_MISSING = frozenset({"NoSuchKey", "404", "NotFound"})
_DENIED = frozenset({"AccessDenied", "403"})
_ALREADY_KEPT = frozenset({"PreconditionFailed", "ConditionalRequestConflict"})
_JPEG = "image/jpeg"

PHOTO_INDEXES_EVER = 6
"""The most photos a drop-off has ever been allowed to keep. `delete_drop_off` deletes
both sizes of photos 1 to this, not 1 to `PHOTOS_MAX`, so lowering `PHOTOS_MAX` later
can't strand an older drop-off's photos past its close (#7). Never lower it; a test
fails if `PHOTOS_MAX` grows past it (raise it then, keeping `DeleteObjects` under its
1,000 keys)."""


UPLOADS_PREFIX = "uploads/"
"""Where browsers upload; the template's lifecycle rule and IAM prefixes name it too."""
KEPT_PREFIX = "dropoffs/"
"""Where kept photos live; the template's IAM resources and `s3:prefix` name it too."""


def upload_key(slot_id: str) -> str:
    return f"{UPLOADS_PREFIX}{slot_id}/0"


def used_key(slot_id: str) -> str:
    return f"{UPLOADS_PREFIX}{slot_id}/used"


def photo_key(ref: PhotoRef, size: PhotoSize) -> str:
    return _key(ref.drop_off_id, ref.index, size)


def _key(drop_off_id: DropOffId, index: int, size: PhotoSize) -> str:
    suffix = "-thumb" if size is PhotoSize.THUMB else ""
    return f"{KEPT_PREFIX}{drop_off_id}/{index}{suffix}.jpg"


def all_photo_keys(drop_off_id: DropOffId) -> list[str]:
    """Every key a drop-off's photos can ever have had: both sizes of photos 1 to
    `PHOTO_INDEXES_EVER`."""
    return [
        # Not a `PhotoRef`: an index past today's `PHOTOS_MAX` is still deleted.
        _key(drop_off_id, index, size)
        for index in range(1, PHOTO_INDEXES_EVER + 1)
        for size in PhotoSize
    ]


class S3PhotoStore:
    def __init__(self, client: S3Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def upload_slots(self, count: int, now: datetime) -> list[UploadSlot]:
        if now.utcoffset() is None:
            raise ValueError("an upload slot's time is aware")
        if not is_photo_count(count):
            raise ValueError("1 to 6 upload slots at a time")
        lifetime = int(UPLOAD_SLOT_LIFETIME.total_seconds())
        slots = []
        for _ in range(count):
            slot_id = secrets.token_urlsafe(16)  # 22 characters: `is_slot_id`'s shape
            try:
                post = self._client.generate_presigned_post(
                    Bucket=self._bucket,
                    Key=upload_key(slot_id),
                    Fields={"success_action_status": "204"},
                    # boto3 adds the bucket and the exact key; a field set above needs
                    # its own condition too.
                    Conditions=[
                        {"success_action_status": "204"},
                        ["content-length-range", 1, PHOTO_MAX_BYTES],
                        ["starts-with", "$Content-Type", "image/"],
                    ],
                    ExpiresIn=lifetime,
                )
            except (ClientError, BotoCoreError) as error:
                raise PhotosUnavailable(log_aws_error("generate_presigned_post", error)) from None
            slots.append(
                UploadSlot(
                    slot_id=slot_id,
                    post=PresignedPost(url=post["url"], fields=dict(post["fields"])),
                    expires_at=now + UPLOAD_SLOT_LIFETIME,
                )
            )
        return slots

    def read_upload(self, slot_id: str) -> bytes:
        if not is_slot_id(slot_id):
            raise UploadMissing()  # no storage call for any other shape
        # One listing of the slot's prefix shows both the upload and the `used` marker.
        # A listing answers "absent" plainly, where a GET or HEAD of a missing key answers
        # 403 under a prefix-conditioned `s3:ListBucket` grant.
        try:
            listed = self._client.list_objects_v2(
                Bucket=self._bucket, Prefix=f"{UPLOADS_PREFIX}{slot_id}/", MaxKeys=10
            )
        except (ClientError, BotoCoreError) as error:
            raise PhotosUnavailable(log_aws_error("list_objects_v2", error)) from None
        present = {item.get("Key") for item in listed.get("Contents", [])}
        if used_key(slot_id) in present or upload_key(slot_id) not in present:
            raise UploadMissing()  # discarded (the slot is used up), or never uploaded
        try:
            # At most one byte over the limit is read: enough to tell it is too large.
            response = self._client.get_object(
                Bucket=self._bucket, Key=upload_key(slot_id), Range=f"bytes=0-{PHOTO_MAX_BYTES}"
            )
            if _total_size(response.get("ContentRange")) > PHOTO_MAX_BYTES:
                raise UploadMissing()
            data = response["Body"].read(PHOTO_MAX_BYTES + 1)
        except ClientError as error:
            code = aws_error_code(error)
            if code in _MISSING or code == "InvalidRange":  # an empty object has no byte 0
                raise UploadMissing() from None
            raise PhotosUnavailable(log_aws_error("get_object", error)) from None
        except BotoCoreError as error:
            raise PhotosUnavailable(log_aws_error("get_object", error)) from None
        if not 1 <= len(data) <= PHOTO_MAX_BYTES:
            raise UploadMissing()
        return data

    def discard_uploads(self, slot_ids: Sequence[str]) -> None:
        if isinstance(slot_ids, str):
            raise TypeError("slot_ids is a sequence of slot IDs, not one string")
        for slot_id in slot_ids:
            if not is_slot_id(slot_id):
                continue
            try:
                # The marker first: the POST stays valid until the slot expires, so the
                # browser could upload again, but `read_upload` refuses a marked slot.
                self._client.put_object(Bucket=self._bucket, Key=used_key(slot_id), Body=b"")
                self._client.delete_object(Bucket=self._bucket, Key=upload_key(slot_id))
            except (ClientError, BotoCoreError) as error:
                raise PhotosUnavailable(log_aws_error("discard_uploads", error)) from None

    def keep(self, drop_off_id: DropOffId, photos: Sequence[CheckedPhoto]) -> tuple[PhotoRef, ...]:
        if not is_photo_count(len(photos)):
            raise ValueError("a drop-off keeps 1 to 6 photos")
        refs = tuple(PhotoRef(drop_off_id, index) for index in range(1, len(photos) + 1))
        written: list[str] = []
        try:
            for ref, photo in zip(refs, photos, strict=True):
                for size, data in ((PhotoSize.FULL, photo.full), (PhotoSize.THUMB, photo.thumb)):
                    key = photo_key(ref, size)
                    # Never overwrites (S3 conditional writes): 412 when the key exists,
                    # 409 when another write to it is in flight.
                    self._client.put_object(
                        Bucket=self._bucket, Key=key, Body=data, ContentType=_JPEG, IfNoneMatch="*"
                    )
                    written.append(key)
        except ClientError as error:
            code = log_aws_error("put_object", error, drop_off_id=str(drop_off_id))
            deleted = self._delete_quietly(drop_off_id, written)
            if retry_attempts(error) > 0 or not deleted:
                # An earlier try may have landed this very key: it can't be told from a
                # photo kept before; or the cleanup failed. Left for the backstop.
                _left_for_backstop(drop_off_id, code)
                raise PhotosUnavailable(code) from None
            if code in _ALREADY_KEPT:
                raise PhotosAlreadyKept(drop_off_id) from None
            raise PhotosUnavailable(code) from None
        except BotoCoreError as error:
            code = log_aws_error("put_object", error, drop_off_id=str(drop_off_id))
            deleted = self._delete_quietly(drop_off_id, written)
            # A first attempt refused by the deadline had nothing in flight; any other
            # failure's put may have landed, and a failed cleanup left what was written.
            if type(error) is not DeadlinePassed or not deleted:
                _left_for_backstop(drop_off_id, code)
            raise PhotosUnavailable(code) from None
        return refs

    def read(self, ref: PhotoRef, size: PhotoSize) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=photo_key(ref, size))
            return response["Body"].read()
        except ClientError as error:
            code = aws_error_code(error)
            if code in _MISSING:
                raise UploadMissing() from None
            log_aws_error("get_object", error, drop_off_id=str(ref.drop_off_id))
            if code in _DENIED and not self._listed(photo_key(ref, size)):
                raise UploadMissing() from None  # gone: a GET of a missing key answers 403
            raise PhotosUnavailable(code) from None
        except BotoCoreError as error:
            raise PhotosUnavailable(
                log_aws_error("get_object", error, drop_off_id=str(ref.drop_off_id))
            ) from None

    def _listed(self, key: str) -> bool:
        """Whether `key` exists, by listing its prefix (`s3:ListBucket` on `dropoffs/*`)."""
        prefix = key.rsplit("/", 1)[0] + "/"
        try:
            listed = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix, MaxKeys=20)
        except (ClientError, BotoCoreError) as error:
            raise PhotosUnavailable(log_aws_error("list_objects_v2", error)) from None
        return key in {item.get("Key") for item in listed.get("Contents", [])}

    def delete_drop_off(self, drop_off_id: DropOffId) -> None:
        """One `DeleteObjects` of every key a drop-off can have (`all_photo_keys`: 12),
        without listing (so no `s3:ListBucket`); deleting a key that is gone succeeds."""
        self._delete(drop_off_id, all_photo_keys(drop_off_id))

    def _delete(self, drop_off_id: DropOffId, object_keys: Iterable[str]) -> None:
        objects: list[ObjectIdentifierTypeDef] = [{"Key": key} for key in object_keys]
        if not objects:
            return
        try:
            # A cleanup: still sent after a web request's work deadline (decision 0004).
            with deadline.cleanup():
                response = self._client.delete_objects(
                    Bucket=self._bucket, Delete={"Objects": objects, "Quiet": True}
                )
        except (ClientError, BotoCoreError) as error:
            raise PhotosUnavailable(
                log_aws_error("delete_objects", error, drop_off_id=str(drop_off_id))
            ) from None
        errors = response.get("Errors", [])
        if errors:
            code = str(errors[0].get("Code", ""))
            unavailable = PhotosUnavailable(code)
            log_event(
                "aws_call_failed",
                level=logging.WARNING,
                kind="delete_objects",
                error_code=unavailable.code,
                drop_off_id=str(drop_off_id),
            )
            raise unavailable

    def _delete_quietly(self, drop_off_id: DropOffId, object_keys: list[str]) -> bool:
        """`keep`'s cleanup of what it wrote, before it raises its own error. False when
        the delete failed (logged): the caller leaves the photos for the backstop (#19)."""
        try:
            self._delete(drop_off_id, object_keys)
        except PhotosUnavailable:
            return False
        return True


def _left_for_backstop(drop_off_id: DropOffId, code: str) -> None:
    log_event(
        "photos_not_deleted",
        level=logging.ERROR,
        drop_off_id=str(drop_off_id),
        error_code=PhotosUnavailable(code).code,
    )


def _total_size(content_range: str | None) -> int:
    """The object's size from `bytes 0-10485760/12345678`; 0 when there is none."""
    if not content_range or "/" not in content_range:
        return 0
    total = content_range.rsplit("/", 1)[1]
    return int(total) if total.isdigit() else 0
