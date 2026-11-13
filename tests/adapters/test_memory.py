"""Each in-memory fake keeps its port's contract, failures included.

Phases 2 and 3 test every use case against these fakes, so a fake that is laxer than its
port's contract would let a use case pass here and fail against AWS.
"""

import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from asmbly_ceramics.adapters.memory.clock import FixedClock
from asmbly_ceramics.adapters.memory.ids import MemoryIdNumbers
from asmbly_ceramics.adapters.memory.images import (
    NOT_IMAGE,
    TOO_LARGE,
    TOO_MANY_PIXELS,
    MemoryPhotoInspector,
)
from asmbly_ceramics.adapters.memory.mailer import MemoryMailer
from asmbly_ceramics.adapters.memory.photos import MemoryPhotoStore
from asmbly_ceramics.adapters.memory.rate_limit import MemoryRateLimiter
from asmbly_ceramics.adapters.memory.records import MemoryRecords
from asmbly_ceramics.adapters.memory.secrets import MemorySecrets
from asmbly_ceramics.adapters.memory.staff_tokens import MemoryStaffTokens, s256
from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus, mark_sent, new_email
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import (
    DEVICE_LIMIT,
    PHOTO_MAX_BYTES,
    STUDIO_TZ,
    SUBMISSION_LIFETIME,
    UPLOAD_SLOT_LIFETIME,
)
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRef, PhotoRefusal, PhotoSize
from asmbly_ceramics.domain.studio import CatalogList, SettingChange, starting_studio
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.errors import (
    IdsUnavailable,
    PhotosUnavailable,
    PortError,
    RecordsUnavailable,
    SecretMissing,
    SecretsUnavailable,
    SignInUnavailable,
    Unavailable,
)
from asmbly_ceramics.ports.ids import IdNumbers
from asmbly_ceramics.ports.images import PhotoInspector, PhotoRefused
from asmbly_ceramics.ports.mailer import InlineImage, Mailer, OutgoingEmail, SendFailed
from asmbly_ceramics.ports.photos import PhotosAlreadyKept, PhotoStore, UploadMissing
from asmbly_ceramics.ports.rate_limit import RateLimiter
from asmbly_ceramics.ports.records import MAX_CHANGES, Change, Conflict, Put, Records, Submission, Update
from asmbly_ceramics.ports.secrets import SecretName, Secrets
from asmbly_ceramics.ports.staff import NotAllowed, NotSignedIn, StaffMember, StaffTokens
from tests.domain.builders import (
    NOW,
    STAFF,
    TEST_EMAIL,
    TEST_NAME,
    a_drop_off,
    a_load,
    a_sending_address,
    an_address,
)

NAIVE = datetime(2026, 11, 13, 12, 0)  # noqa: DTZ001 - the naive time the fakes must refuse
TOKEN_HASH = "made-up-token-hash-value"
PHOTO = b"\xff\xd8\xff\xe0MADE-UP-PIXELS"
AWS_TEXT = "Email address is not verified: " + TEST_EMAIL


def a_submission(number: int = 1, token_hash: str = TOKEN_HASH) -> Submission:
    return Submission(
        token_hash=token_hash,
        drop_off_id=DropOffId(number),
        pieces=3,
        firing_type="Bisque",
        glaze_type=None,
        created_at=NOW,
        expires_at=NOW + SUBMISSION_LIFETIME,
    )


def an_email(from_address: str | None = None) -> OutgoingEmail:
    return OutgoingEmail(
        from_address=from_address if from_address is not None else a_sending_address(),
        from_name="Asmbly Ceramics",
        reply_to=a_sending_address(),
        to=TEST_EMAIL,
        subject="AC-1: we received your drop-off",
        html=f"<p>Hello {TEST_NAME}</p>",
        text=f"Hello {TEST_NAME}",
        inline=(InlineImage("photo-1", "AC-1-1.jpg", PHOTO),),
    )


# Records


def test_records_put_stores_version_one_and_refuses_an_existing_key() -> None:
    records = MemoryRecords()
    drop_off = a_drop_off(1)
    records.commit([Put(drop_off)])
    stored = records.drop_off(DropOffId(1))
    assert stored is not None
    assert stored.version == 1
    assert replace(stored, version=0) == drop_off
    with pytest.raises(Conflict) as refused:
        records.commit([Put(drop_off)])
    assert refused.value.ids == ("AC-1",)
    assert records.drop_off(DropOffId(1)) == stored


def test_records_update_refuses_a_stale_version() -> None:
    records = MemoryRecords()
    records.commit([Put(a_load(1))])
    stored = records.load(LoadId(1))
    assert stored is not None
    records.commit([Update(replace(stored, status=LoadStatus.FIRING))])
    fresh = records.load(LoadId(1))
    assert fresh is not None
    assert (fresh.version, fresh.status) == (2, LoadStatus.FIRING)
    with pytest.raises(Conflict) as refused:
        records.commit([Update(replace(stored, status=LoadStatus.FIRED))])
    assert refused.value.ids == ("L-1",)
    assert records.load(LoadId(1)) == fresh


def test_records_update_of_a_missing_item_conflicts() -> None:
    records = MemoryRecords()
    with pytest.raises(Conflict):
        records.commit([Update(replace(a_drop_off(1), version=1))])
    assert records.drop_off(DropOffId(1)) is None
    assert records.commits == []


def test_records_commit_is_all_or_nothing() -> None:
    records = MemoryRecords()
    records.commit([Put(a_drop_off(1))])
    with pytest.raises(Conflict) as refused:
        records.commit([Put(a_drop_off(2)), Put(a_load(1)), Put(a_drop_off(1))])
    assert refused.value.ids == ("AC-1",)
    assert records.drop_off(DropOffId(2)) is None
    assert records.load(LoadId(1)) is None
    assert len(records.commits) == 1


def test_records_refuses_more_than_100_changes() -> None:
    records = MemoryRecords()
    with pytest.raises(ValueError, match="at most 100"):
        records.commit([Put(a_drop_off(n)) for n in range(1, MAX_CHANGES + 2)])
    assert records.drop_offs_in(set(DropOffState)) == []
    records.commit([Put(a_drop_off(n)) for n in range(1, MAX_CHANGES + 1)])
    assert len(records.drop_offs_in(set(DropOffState))) == MAX_CHANGES


def test_records_refuses_two_changes_on_one_key() -> None:
    records = MemoryRecords()
    records.commit([Put(a_drop_off(1))])
    stored = records.drop_off(DropOffId(1))
    assert stored is not None
    with pytest.raises(ValueError, match="one key"):
        records.commit([Update(stored), Update(replace(stored, pieces=4))])
    assert records.drop_off(DropOffId(1)) == stored


def test_records_empty_commit_is_a_no_op_and_not_recorded() -> None:
    records = MemoryRecords()
    records.commit([])
    assert records.commits == []
    records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
    records.commit(())  # nothing is sent, so nothing can fail
    assert records.commits == []
    with pytest.raises(RecordsUnavailable):
        records.commit([Put(a_drop_off(1))])


def test_conflict_refuses_one_string_for_its_ids() -> None:
    with pytest.raises(TypeError, match="sequence of IDs"):
        Conflict("AC-12")
    assert Conflict(["AC-12"]).ids == ("AC-12",)


def test_records_setting_changes_at_one_instant_both_land() -> None:
    records = MemoryRecords()
    first = SettingChange(NOW, STAFF, "Added kiln Helios")
    second = SettingChange(NOW, STAFF, "Added kiln Vulcan")
    records.commit([Put(first), Put(second)])
    assert set(records.history(10)) == {first, second}


def test_records_failure_switch_raises_and_writes_nothing() -> None:
    records = MemoryRecords()
    records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
    with pytest.raises(RecordsUnavailable):
        records.commit([Put(a_drop_off(1))])
    assert records.drop_off(DropOffId(1)) is None
    assert records.commits == []
    records.commit([Put(a_drop_off(1))])  # cleared after it fired
    assert records.drop_off(DropOffId(1)) is not None

    records.fail_reads_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        records.drop_off(DropOffId(1))
    with pytest.raises(RecordsUnavailable):
        records.drop_offs_in({DropOffState.WAITING})


def test_records_email_key_includes_the_occasion() -> None:
    records = MemoryRecords()
    ac1 = DropOffId(1)
    records.commit([Put(new_email(ac1, EmailKind.READY, NOW))])
    # Firing again can never queue a second ready email (#4).
    with pytest.raises(Conflict) as refused:
        records.commit([Put(new_email(ac1, EmailKind.READY, NOW + timedelta(hours=1)))])
    assert refused.value.ids == ("AC-1",)
    first = NOW.isoformat()
    later = (NOW + timedelta(hours=1)).isoformat()
    records.commit([Put(new_email(ac1, EmailKind.REJECTED, NOW, occasion=first))])
    records.commit([Put(new_email(ac1, EmailKind.REJECTED, NOW, occasion=later))])
    with pytest.raises(Conflict):
        records.commit([Put(new_email(ac1, EmailKind.REJECTED, NOW, occasion=later))])
    assert records.email(ac1, EmailKind.READY) is not None
    assert records.email(ac1, EmailKind.RECEIVED) is None
    rejected = records.email(ac1, EmailKind.REJECTED, first)
    assert rejected is not None
    assert rejected.occasion == first
    assert len(records.emails_for(ac1)) == 3


def test_records_lists_filter_and_sort() -> None:
    records = MemoryRecords()
    day = timedelta(days=1)
    records.commit(
        [
            Put(a_drop_off(3, at=NOW)),
            Put(a_drop_off(2, at=NOW)),
            Put(a_drop_off(1, at=NOW + day)),
            Put(a_drop_off(4, DropOffState.REJECTED, at=NOW - day)),
            Put(a_drop_off(5, DropOffState.FIRED, at=NOW + 2 * day)),
            Put(a_load(2, at=NOW)),
            Put(a_load(1, at=NOW)),
            Put(a_load(3, LoadStatus.FIRED, at=NOW + day)),
        ]
    )

    def ids(items: Sequence[DropOff | Load]) -> list[str]:
        return [str(item.id) for item in items]

    assert ids(records.drop_offs_in({DropOffState.WAITING})) == ["AC-2", "AC-3", "AC-1"]
    assert ids(records.drop_offs_created_between(NOW, NOW + day)) == ["AC-2", "AC-3"]
    assert ids(records.drop_offs_created_between(NOW - day, NOW)) == ["AC-4"]
    assert ids(records.drop_offs_rejected_between(NOW - day, NOW)) == ["AC-4"]
    assert records.drop_offs_rejected_between(NOW, NOW + 3 * day) == []
    assert ids(records.loads_in({LoadStatus.LOADING})) == ["L-1", "L-2"]
    assert ids(records.loads_in({LoadStatus.LOADING, LoadStatus.FIRED})) == ["L-1", "L-2", "L-3"]
    today = NOW.date()
    assert ids(records.loads_between(today, today + day)) == ["L-1", "L-2"]
    assert ids(records.loads_between(today + day, date(2027, 1, 1))) == ["L-3"]

    ac1 = DropOffId(1)
    sent = replace(new_email(ac1, EmailKind.RECEIVED, NOW + day), status=EmailStatus.SENDING)
    records.commit([Put(mark_sent(sent, NOW + day)), Put(new_email(ac1, EmailKind.READY, NOW))])
    records.commit([Put(new_email(DropOffId(2), EmailKind.RECEIVED, NOW - day))])
    assert [e.kind for e in records.emails_for(ac1)] == [EmailKind.READY, EmailKind.RECEIVED]
    pending = records.emails_in({EmailStatus.PENDING})
    assert [(str(e.drop_off_id), e.kind) for e in pending] == [
        ("AC-2", EmailKind.RECEIVED),
        ("AC-1", EmailKind.READY),
    ]

    changes = [SettingChange(NOW + timedelta(minutes=n), STAFF, f"change {n}") for n in range(5)]
    records.commit([Put(change) for change in changes])
    assert records.history(3) == [changes[4], changes[3], changes[2]]
    assert records.history(10, before=changes[2].at) == [changes[1], changes[0]]
    with pytest.raises(ValueError, match="limit"):
        records.history(0)


def test_records_is_item_used_for_each_list() -> None:
    records = MemoryRecords()
    assert not records.is_item_used(CatalogList.KILNS, ItemId("athena"))
    glazed = replace(a_drop_off(1), firing_type=ItemId("glaze"), glaze_type=ItemId("house-dip"))
    records.commit(
        [
            Put(glazed),
            Put(a_drop_off(2, DropOffState.CLOSED, reason="cracked")),
            Put(a_load(1, kiln="helios", firing_type="raku")),
        ]
    )
    assert records.is_item_used(CatalogList.KILNS, ItemId("helios"))
    assert not records.is_item_used(CatalogList.KILNS, ItemId("athena"))
    assert records.is_item_used(CatalogList.FIRING_TYPES, ItemId("glaze"))  # by a drop-off
    assert records.is_item_used(CatalogList.FIRING_TYPES, ItemId("raku"))  # by a load
    assert not records.is_item_used(CatalogList.FIRING_TYPES, ItemId("pit"))
    assert records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("house-dip"))
    assert not records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("commercial"))
    assert records.is_item_used(CatalogList.REASONS, ItemId("cracked"))  # a closed drop-off's
    assert not records.is_item_used(CatalogList.REASONS, ItemId("other"))


def test_records_keep_the_studio_and_submissions() -> None:
    records = MemoryRecords()
    assert records.studio() is None
    studio, change = starting_studio(a_sending_address(), NOW)
    records.commit([Put(studio), Put(change), Put(a_submission())])
    stored = records.studio()
    assert stored is not None
    assert stored.version == 1
    with pytest.raises(Conflict) as refused:
        records.commit([Put(studio)])
    assert refused.value.ids == ()
    records.commit([Update(replace(stored, pickup_window_days=10))])
    assert records.submission(TOKEN_HASH) == a_submission()
    assert records.submission("another-hash") is None
    with pytest.raises(Conflict):
        records.commit([Put(a_submission(2))])  # one drop-off per submission token


def test_fakes_refuse_a_naive_time() -> None:
    with pytest.raises(ValueError, match="aware"):
        MemoryPhotoStore().upload_slots(1, NAIVE)
    with pytest.raises(ValueError, match="aware"):
        MemoryRateLimiter().hit("device-a", DEVICE_LIMIT, NAIVE)
    with pytest.raises(ValueError, match="aware"):
        FixedClock(NAIVE)
    records = MemoryRecords()
    with pytest.raises(ValueError, match="aware"):
        records.drop_offs_created_between(NAIVE, NOW)
    with pytest.raises(ValueError, match="aware"):
        records.drop_offs_rejected_between(NOW, NAIVE)
    with pytest.raises(ValueError, match="aware"):
        records.history(10, before=NAIVE)


# IdNumbers


def test_ids_never_repeat() -> None:
    ids = MemoryIdNumbers()
    drop_offs = [ids.next_drop_off_id() for _ in range(50)]
    assert len(set(drop_offs)) == 50
    assert drop_offs == sorted(drop_offs)
    assert [str(ids.next_load_id()), str(ids.next_load_id())] == ["L-1", "L-2"]
    ids.fail_with = IdsUnavailable("ProvisionedThroughputExceededException")
    with pytest.raises(IdsUnavailable):
        ids.next_drop_off_id()
    with pytest.raises(IdsUnavailable):
        ids.next_load_id()


def test_ids_skip_leaves_a_gap() -> None:
    ids = MemoryIdNumbers()
    assert str(ids.next_drop_off_id()) == "AC-1"
    ids.skip(3)
    assert str(ids.next_drop_off_id()) == "AC-5"
    for n in [0, -1]:
        with pytest.raises(ValueError, match="at least 1"):
            ids.skip(n)
    assert str(ids.next_drop_off_id()) == "AC-6"


# PhotoStore and PhotoInspector


def test_photo_store_slots_expire_after_15_minutes() -> None:
    store = MemoryPhotoStore()
    slots = store.upload_slots(3, NOW)
    assert len(slots) == 3
    assert len({slot.slot_id for slot in slots}) == 3
    assert all(len(slot.slot_id) >= 22 for slot in slots)
    assert all(slot.expires_at == NOW + UPLOAD_SLOT_LIFETIME == NOW + timedelta(minutes=15) for slot in slots)
    with pytest.raises(ValueError, match="aware"):
        store.upload_slots(1, NAIVE)
    with pytest.raises(ValueError, match="slots"):
        store.upload_slots(7, NOW)


def test_photo_store_read_upload_of_an_unknown_slot_raises() -> None:
    store = MemoryPhotoStore()
    (slot,) = store.upload_slots(1, NOW)
    with pytest.raises(UploadMissing):
        store.read_upload(slot.slot_id)  # issued, never sent
    with pytest.raises(UploadMissing):
        store.read_upload("never-issued-slot-handle")
    with pytest.raises(ValueError, match="issued"):
        store.put_upload("never-issued-slot-handle", PHOTO)
    store.put_upload(slot.slot_id, PHOTO)
    assert store.read_upload(slot.slot_id) == PHOTO


def test_photo_store_refuses_an_upload_over_10_mb() -> None:
    store = MemoryPhotoStore()
    big, exact = store.upload_slots(2, NOW)
    store.put_upload(big.slot_id, b"x" * (PHOTO_MAX_BYTES + 1))
    with pytest.raises(UploadMissing):
        store.read_upload(big.slot_id)
    store.put_upload(exact.slot_id, b"x" * PHOTO_MAX_BYTES)
    assert len(store.read_upload(exact.slot_id)) == PHOTO_MAX_BYTES


def test_photo_store_refuses_an_empty_upload() -> None:
    store = MemoryPhotoStore()
    (slot,) = store.upload_slots(1, NOW)
    store.put_upload(slot.slot_id, PHOTO)
    store.put_upload(slot.slot_id, b"")  # content-length-range starts at 1 byte
    with pytest.raises(UploadMissing):
        store.read_upload(slot.slot_id)
    assert store.upload_count() == 0


def test_photo_store_records_each_read_upload() -> None:
    store = MemoryPhotoStore()
    (slot,) = store.upload_slots(1, NOW)
    store.put_upload(slot.slot_id, PHOTO)
    store.read_upload(slot.slot_id)
    with pytest.raises(UploadMissing):
        store.read_upload("never-issued-slot-handle")
    assert store.read_uploads == [slot.slot_id, "never-issued-slot-handle"]


def test_photo_store_discard_uses_the_slots_up() -> None:
    store = MemoryPhotoStore()
    first, second, other = store.upload_slots(3, NOW)
    for slot in (first, second, other):
        store.put_upload(slot.slot_id, PHOTO)
    store.keep(DropOffId(1), [MemoryPhotoInspector().inspect(store.read_upload(first.slot_id))])
    assert store.read_upload(first.slot_id) == PHOTO  # keep leaves the uploads alone
    store.discard_uploads([first.slot_id, second.slot_id, "never-issued-slot-handle"])
    store.discard_uploads([first.slot_id])  # idempotent
    assert store.upload_count() == 1
    for slot in (first, second):
        with pytest.raises(UploadMissing):
            store.read_upload(slot.slot_id)
    # The browser can post again until the slot expires, as S3 allows; it is still used up.
    store.put_upload(first.slot_id, PHOTO)
    with pytest.raises(UploadMissing):
        store.read_upload(first.slot_id)
    assert store.read_upload(other.slot_id) == PHOTO
    assert store.read(PhotoRef(DropOffId(1), 1), PhotoSize.FULL) == PHOTO
    with pytest.raises(TypeError, match="sequence"):
        store.discard_uploads(other.slot_id)
    assert store.read_upload(other.slot_id) == PHOTO


def test_photo_store_keep_never_overwrites() -> None:
    store = MemoryPhotoStore()
    ac1 = DropOffId(1)
    store.keep(
        ac1, [CheckedPhoto(full=b"full-1", thumb=b"thumb-1"), CheckedPhoto(full=b"full-2", thumb=b"t2")]
    )
    with pytest.raises(PhotosAlreadyKept) as refused:
        store.keep(ac1, [CheckedPhoto(full=b"other", thumb=b"other")])
    assert refused.value.drop_off_id == ac1
    assert str(refused.value) == "photos already kept for AC-1"
    assert store.kept_count(ac1) == 4
    assert store.read(PhotoRef(ac1, 1), PhotoSize.FULL) == b"full-1"
    assert store.read(PhotoRef(ac1, 2), PhotoSize.FULL) == b"full-2"
    store.delete_drop_off(ac1)
    assert store.keep(ac1, [CheckedPhoto(full=b"again", thumb=b"again")]) == (PhotoRef(ac1, 1),)


def test_photo_store_keep_then_read_both_sizes() -> None:
    store = MemoryPhotoStore()
    ac1 = DropOffId(1)
    photos = [CheckedPhoto(full=b"full-1", thumb=b"thumb-1"), CheckedPhoto(full=b"full-2", thumb=b"thumb-2")]
    refs = store.keep(ac1, photos)
    assert refs == (PhotoRef(ac1, 1), PhotoRef(ac1, 2))
    assert store.read(refs[1], PhotoSize.FULL) == b"full-2"
    assert store.read(refs[1], PhotoSize.THUMB) == b"thumb-2"
    with pytest.raises(UploadMissing):
        store.read(PhotoRef(DropOffId(2), 1), PhotoSize.FULL)
    with pytest.raises(ValueError, match="photos"):
        store.keep(ac1, [])
    with pytest.raises(ValueError, match="photos"):
        store.keep(ac1, photos * 4)


def test_photo_store_delete_is_idempotent() -> None:
    store = MemoryPhotoStore()
    ac1, ac2 = DropOffId(1), DropOffId(2)
    store.keep(ac1, [CheckedPhoto(full=b"a", thumb=b"b")])
    store.keep(ac2, [CheckedPhoto(full=b"c", thumb=b"d")])
    store.delete_drop_off(ac1)
    store.delete_drop_off(ac1)
    assert store.kept_count(ac1) == 0
    assert store.kept_count(ac2) == 2
    for size in PhotoSize:
        with pytest.raises(UploadMissing):
            store.read(PhotoRef(ac1, 1), size)


def test_photo_store_failure_switch() -> None:
    store = MemoryPhotoStore()
    (slot,) = store.upload_slots(1, NOW)
    store.put_upload(slot.slot_id, PHOTO)
    store.fail_with = PhotosUnavailable("SlowDown")
    with pytest.raises(PhotosUnavailable):
        store.upload_slots(1, NOW)
    with pytest.raises(PhotosUnavailable):
        store.read_upload(slot.slot_id)
    with pytest.raises(PhotosUnavailable):
        store.discard_uploads([slot.slot_id])
    with pytest.raises(PhotosUnavailable):
        store.keep(DropOffId(1), [CheckedPhoto(full=b"a", thumb=b"b")])
    with pytest.raises(PhotosUnavailable):
        store.read(PhotoRef(DropOffId(1), 1), PhotoSize.FULL)
    with pytest.raises(PhotosUnavailable):
        store.delete_drop_off(DropOffId(1))
    store.fail_with = None
    assert store.read_upload(slot.slot_id) == PHOTO  # a failed discard kept the upload


@pytest.mark.parametrize(
    ("marker", "kind"),
    [
        (NOT_IMAGE, PhotoRefusal.NOT_IMAGE),
        (TOO_LARGE, PhotoRefusal.TOO_LARGE),
        (TOO_MANY_PIXELS, PhotoRefusal.TOO_MANY_PIXELS),
    ],
)
def test_inspector_refuses_each_marker(marker: bytes, kind: PhotoRefusal) -> None:
    with pytest.raises(PhotoRefused) as refused:
        MemoryPhotoInspector().inspect(marker + PHOTO)
    assert refused.value.kind is kind
    assert str(refused.value) == f"photo refused: {kind}"


def test_inspector_passes_other_data() -> None:
    checked = MemoryPhotoInspector().inspect(PHOTO)
    assert checked == CheckedPhoto(full=PHOTO, thumb=PHOTO[:16])


# Mailer


def test_mailer_keeps_what_it_sent() -> None:
    mailer = MemoryMailer()
    mailer.send(an_email())
    assert mailer.sent == [an_email()]


def test_mailer_failure_raises_send_failed_with_the_code() -> None:
    mailer = MemoryMailer()
    mailer.fail_with = "MessageRejected"
    with pytest.raises(SendFailed) as failed:
        mailer.send(an_email())
    assert failed.value.code == "MessageRejected"
    assert mailer.sent == []


def test_mailer_refuses_a_from_outside_asmbly_org() -> None:
    mailer = MemoryMailer()
    for sender in [an_address("ceramics"), an_address("ceramics", "asmbly.org.example.org"), "asmbly.org"]:
        with pytest.raises(ValueError, match=r"asmbly\.org"):
            mailer.send(an_email(from_address=sender))
    for sender in [an_address("ceramics", "ASMBLY.ORG"), " " + a_sending_address()]:
        with pytest.raises(ValueError, match=r"asmbly\.org"):
            mailer.send(an_email(from_address=sender))  # not as the studio stores it
    assert mailer.sent == []


def test_an_outgoing_email_repr_holds_no_address() -> None:
    text = repr(an_email())
    for secret in [TEST_EMAIL, TEST_NAME, a_sending_address(), "received your drop-off", "MADE-UP-PIXELS"]:
        assert secret not in text


def test_reprs_hold_no_bytes_token_or_address() -> None:
    image = repr(InlineImage("photo-1", "AC-1-1.jpg", PHOTO))
    assert "MADE-UP-PIXELS" not in image
    assert "AC-1-1.jpg" in image
    member = repr(StaffMember(STAFF, TEST_EMAIL))
    assert TEST_EMAIL not in member
    assert STAFF in member
    submission = repr(a_submission())
    assert TOKEN_HASH not in submission
    assert "drop_off_id=DropOffId(number=1)" in submission


def test_port_errors_keep_a_code_never_a_message() -> None:
    errors: list[SendFailed | Unavailable] = [
        SendFailed(AWS_TEXT),
        RecordsUnavailable(AWS_TEXT),
        Unavailable(""),
    ]
    for error in errors:
        assert error.code == "unknown"
        assert TEST_EMAIL not in str(error)
    assert SendFailed("Throttling").code == "Throttling"
    assert str(SignInUnavailable("timeout")) == "unavailable: timeout"
    assert str(SecretMissing(SecretName.HASH_KEY)) == "secret hash-key is not set"
    assert str(SecretMissing(AWS_TEXT)) == "secret unknown is not set"
    assert str(Conflict()) == "changed by someone else first: unknown"


def test_every_port_error_has_safe_text() -> None:
    # One of each port error class, built as an adapter would; none may carry what was sent.
    errors: list[PortError] = [
        Unavailable(AWS_TEXT),
        RecordsUnavailable(AWS_TEXT),
        IdsUnavailable(AWS_TEXT),
        PhotosUnavailable(AWS_TEXT),
        SignInUnavailable(AWS_TEXT),
        SecretsUnavailable(AWS_TEXT),
        SecretMissing(AWS_TEXT),
        SendFailed(AWS_TEXT),
        Conflict(["AC-1"]),
        UploadMissing(),
        PhotosAlreadyKept(DropOffId(1)),
        PhotoRefused(PhotoRefusal.NOT_IMAGE),
        NotSignedIn(),
        NotAllowed(STAFF),
    ]
    for error in errors:
        assert TEST_EMAIL not in str(error)
        assert "not verified" not in str(error)


# StaffTokens


def test_staff_tokens_not_allowed_and_not_signed_in() -> None:
    tokens = MemoryStaffTokens()
    member = StaffMember(STAFF, TEST_EMAIL)
    tokens.members["member-token"] = member
    tokens.outsiders["outsider-token"] = "woodshop-lead"
    assert tokens.verify("member-token") == member
    with pytest.raises(NotAllowed) as refused:
        tokens.verify("outsider-token")
    assert refused.value.username == "woodshop-lead"
    with pytest.raises(NotSignedIn):
        tokens.verify("forged-token")
    tokens.fail_with = SignInUnavailable("timeout")
    with pytest.raises(SignInUnavailable):
        tokens.verify("member-token")


VERIFIER = "made-up-code-verifier-of-forty-three-chars-x"
CALLBACK = "https://ceramics.example.org/console/auth/callback"


def test_s256_is_the_pkce_challenge() -> None:
    # RFC 7636, appendix B's example.
    assert (
        s256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_staff_tokens_exchange_returns_the_token_once() -> None:
    tokens = MemoryStaffTokens()
    with pytest.raises(ValueError, match="started"):
        tokens.approve("sign-in-code", "member-token")
    tokens.sign_in_url(state="s", code_challenge=s256(VERIFIER), redirect_uri=CALLBACK)
    tokens.approve("sign-in-code", "member-token")
    assert (
        tokens.exchange(code="sign-in-code", code_verifier=VERIFIER, redirect_uri=CALLBACK) == "member-token"
    )
    with pytest.raises(NotSignedIn):  # used
        tokens.exchange(code="sign-in-code", code_verifier=VERIFIER, redirect_uri=CALLBACK)
    with pytest.raises(NotSignedIn):
        tokens.exchange(code="made-up-code", code_verifier=VERIFIER, redirect_uri=CALLBACK)


@pytest.mark.parametrize(
    ("verifier", "redirect_uri"),
    [
        ("another-made-up-verifier-of-forty-three-chr", CALLBACK),
        (s256(VERIFIER), CALLBACK),  # the challenge itself is not the verifier
        (VERIFIER, "https://elsewhere.example.org/console/auth/callback"),
    ],
)
def test_staff_tokens_exchange_refuses_a_wrong_verifier_or_redirect(verifier: str, redirect_uri: str) -> None:
    tokens = MemoryStaffTokens()
    tokens.sign_in_url(state="s", code_challenge=s256(VERIFIER), redirect_uri=CALLBACK)
    tokens.approve("sign-in-code", "member-token")
    with pytest.raises(NotSignedIn):
        tokens.exchange(code="sign-in-code", code_verifier=verifier, redirect_uri=redirect_uri)
    with pytest.raises(NotSignedIn):  # a failed try uses the code up too
        tokens.exchange(code="sign-in-code", code_verifier=VERIFIER, redirect_uri=CALLBACK)


def test_staff_tokens_urls_and_failures() -> None:
    tokens = MemoryStaffTokens()
    callback = CALLBACK
    tokens.sign_in_url(state="s", code_challenge=s256(VERIFIER), redirect_uri=callback)
    tokens.approve("sign-in-code", "member-token")

    sign_in = urlsplit(tokens.sign_in_url(state="s 1", code_challenge="c&2", redirect_uri=callback))
    assert (sign_in.scheme, sign_in.netloc) == ("https", "sign-in.example.org")
    assert parse_qs(sign_in.query) == {
        "state": ["s 1"],
        "code_challenge": ["c&2"],
        "redirect_uri": [callback],
    }
    sign_out = urlsplit(tokens.sign_out_url(redirect_uri=callback))
    assert parse_qs(sign_out.query) == {"redirect_uri": [callback]}

    tokens.fail_with = SignInUnavailable("timeout")
    with pytest.raises(SignInUnavailable):
        tokens.exchange(code="sign-in-code", code_verifier=VERIFIER, redirect_uri=callback)
    with pytest.raises(SignInUnavailable):
        tokens.sign_in_url(state="s", code_challenge="c", redirect_uri=callback)
    with pytest.raises(SignInUnavailable):
        tokens.sign_out_url(redirect_uri=callback)
    tokens.fail_with = None
    # An unreachable endpoint doesn't use the code up.
    assert (
        tokens.exchange(code="sign-in-code", code_verifier=VERIFIER, redirect_uri=callback) == "member-token"
    )


# RateLimiter, Clock, Secrets


def test_rate_limiter_allows_10_then_refuses_within_the_window_and_allows_after() -> None:
    limiter = MemoryRateLimiter()
    seconds = [NOW + timedelta(seconds=n) for n in range(11)]
    assert [limiter.hit("device-a", DEVICE_LIMIT, at) for at in seconds] == [True] * 10 + [False]
    assert limiter.hit("device-b", DEVICE_LIMIT, seconds[10])  # keys are counted apart
    # A refused hit still counts, so retrying inside the window stays refused.
    assert not limiter.hit("device-a", DEVICE_LIMIT, NOW + timedelta(minutes=9, seconds=59))
    # The window is (now - 10 minutes, now]: the hits at 0 and 1 seconds have left it.
    assert not limiter.hit("device-a", DEVICE_LIMIT, NOW + timedelta(minutes=10, seconds=1))
    later = NOW + timedelta(minutes=20)
    assert limiter.hit("device-a", DEVICE_LIMIT, later)
    limiter.fail_with = RecordsUnavailable("ThrottlingException")
    with pytest.raises(RecordsUnavailable):
        limiter.hit("device-a", DEVICE_LIMIT, later)
    with pytest.raises(ValueError, match="aware"):
        limiter.hit("device-a", DEVICE_LIMIT, NAIVE)


def test_rate_limiter_window_is_rolling_across_a_fixed_boundary() -> None:
    # 10 hits just before a 10-minute boundary, then one just after: a fixed window
    # floored to 10 minutes would allow it (up to 20 in 10 minutes); the port refuses.
    limiter = MemoryRateLimiter()
    boundary = datetime(2026, 11, 13, 12, 10, tzinfo=UTC)
    before = [boundary - timedelta(seconds=10 - n) for n in range(10)]
    assert all(limiter.hit("device-a", DEVICE_LIMIT, at) for at in before)
    assert not limiter.hit("device-a", DEVICE_LIMIT, boundary + timedelta(seconds=1))
    assert not limiter.hit("device-a", DEVICE_LIMIT, boundary + timedelta(minutes=9, seconds=49))
    # Once the window has passed every hit, it is allowed again.
    assert limiter.hit("device-a", DEVICE_LIMIT, boundary + timedelta(minutes=20))


def test_rate_limiter_shows_the_keys_it_counted() -> None:
    limiter = MemoryRateLimiter()
    limiter.hit("device#made-up-hash", DEVICE_LIMIT, NOW)
    limiter.hit("address#made-up-hash", DEVICE_LIMIT, NOW)
    limiter.fail_with = RecordsUnavailable("ThrottlingException")
    with pytest.raises(RecordsUnavailable):
        limiter.hit("device#another-hash", DEVICE_LIMIT, NOW)
    assert limiter.keys_hit == ["device#made-up-hash", "address#made-up-hash"]


def test_clock_advances_and_refuses_a_naive_time() -> None:
    clock = FixedClock(NOW)
    assert clock.now() == NOW
    clock.advance(timedelta(minutes=5))
    assert clock.now() == NOW + timedelta(minutes=5)
    assert clock.now().tzinfo is UTC
    austin = FixedClock(datetime(2026, 11, 13, 23, 30, tzinfo=STUDIO_TZ))
    assert austin.now() == datetime(2026, 11, 14, 5, 30, tzinfo=UTC)
    assert austin.now().tzinfo is UTC
    with pytest.raises(ValueError, match="aware"):
        FixedClock(NAIVE)


def test_secrets_get_and_missing() -> None:
    secrets = MemorySecrets()
    values = {name: secrets.get(name) for name in SecretName}
    assert all(len(value) == 32 for value in values.values())
    assert len(set(values.values())) == len(SecretName)
    secrets.remove(SecretName.FORM_KEY)
    with pytest.raises(SecretMissing) as missing:
        secrets.get(SecretName.FORM_KEY)
    assert missing.value.name == SecretName.FORM_KEY
    secrets.fail_with = SecretsUnavailable("ParameterNotFound")
    with pytest.raises(SecretsUnavailable):
        secrets.get(SecretName.HASH_KEY)


def test_each_fake_satisfies_its_port() -> None:
    # Typed as the ports, so mypy checks each fake keeps its protocol's signatures.
    records: Records = MemoryRecords()
    ids: IdNumbers = MemoryIdNumbers()
    photos: PhotoStore = MemoryPhotoStore()
    inspector: PhotoInspector = MemoryPhotoInspector()
    mailer: Mailer = MemoryMailer()
    tokens: StaffTokens = MemoryStaffTokens()
    limiter: RateLimiter = MemoryRateLimiter()
    clock: Clock = FixedClock(NOW)
    secrets: Secrets = MemorySecrets()
    changes: list[Change] = []
    records.commit(changes)
    assert isinstance(records, MemoryRecords)
    assert records.commits == []  # an empty commit is a no-op
    assert all(
        port is not None
        for port in [records, ids, photos, inspector, mailer, tokens, limiter, clock, secrets]
    )


def test_the_fakes_log_and_print_nothing(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    records = MemoryRecords()
    records.commit([Put(a_drop_off(1))])
    with pytest.raises(Conflict):
        records.commit([Put(a_drop_off(1))])
    mailer = MemoryMailer()
    mailer.send(an_email())
    mailer.fail_with = "MessageRejected"
    with pytest.raises(SendFailed):
        mailer.send(an_email())
    tokens = MemoryStaffTokens()
    with pytest.raises(NotSignedIn):
        tokens.verify("forged-token")
    assert caplog.records == []
    assert capsys.readouterr() == ("", "")
