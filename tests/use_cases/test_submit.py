"""`SubmitDropOff`: the token, the rate limit, every field and photo, one commit, and cleanup.

Asserts on what was stored, kept, counted and logged, not only on what was returned. The
person is made up (`tests/domain/builders.py`).
"""

import contextlib
import dataclasses
import logging
from collections.abc import Callable, Sequence

import pytest

from asmbly_ceramics.adapters.memory.images import NOT_IMAGE, TOO_LARGE, TOO_MANY_PIXELS
from asmbly_ceramics.adapters.memory.photos import MemoryPhotoStore
from asmbly_ceramics.adapters.memory.records import MemoryRecords
from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus
from asmbly_ceramics.domain.errors import InvalidDetails, TooManySubmissions
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import ADDRESS_LIMIT, DEVICE_LIMIT, PHOTO_MAX_BYTES, SUBMISSION_LIFETIME
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRef, PhotoSize
from asmbly_ceramics.ports.errors import (
    IdsUnavailable,
    PhotosUnavailable,
    RecordsUnavailable,
    SecretsUnavailable,
)
from asmbly_ceramics.ports.photos import PhotosAlreadyKept, UploadMissing
from asmbly_ceramics.ports.records import Change, Conflict, Put, Submission
from asmbly_ceramics.use_cases.received import ReceivedView
from asmbly_ceramics.use_cases.studio import CurrentStudio
from asmbly_ceramics.use_cases.submit import SubmitDropOff, SubmitRequest, Submitted
from tests.domain.builders import (
    NOW,
    TEST_EMAIL,
    TEST_NAME,
    TEST_PHONE,
    TEST_PHONE_DIGITS,
    a_drop_off,
    a_sending_address,
)
from tests.use_cases.conftest import DEVICE, SOURCE_ADDRESS, World

TOKEN = "made-up-submission-token-0000000001"  # `is_form_token`'s shape
PHOTO = b"made-up-photo-bytes-one"
PHOTO_2 = b"made-up-photo-bytes-two"


def a_token(number: int) -> str:
    return f"made-up-submission-token-{number:010d}"


def a_device(number: int) -> str:
    return f"made-up-device-cookie-{number:010d}"


def a_request(
    world: World,
    slots: tuple[str, ...] | None = None,
    *,
    token: str = TOKEN,
    device: str = DEVICE,
    source_address: str = SOURCE_ADDRESS,
    name: str = TEST_NAME,
    email: str = TEST_EMAIL,
    phone: str = TEST_PHONE,
    pieces: str = "3",
    firing_type: str = "bisque",
    glaze_type: str | None = None,
) -> SubmitRequest:
    return SubmitRequest(
        name=name,
        email=email,
        phone=phone,
        pieces=pieces,
        firing_type=firing_type,
        glaze_type=glaze_type,
        upload_slots=world.uploaded(PHOTO, PHOTO_2) if slots is None else slots,
        submission_token=token,
        device=device,
        source_address=source_address,
    )


def rebuilt(
    world: World, *, records: MemoryRecords | None = None, photos: MemoryPhotoStore | None = None
) -> None:
    """Swaps a fake for a wrapper and rebuilds `world.submit` on it."""
    world.records = records or world.records
    world.photos = photos or world.photos
    world.studio = CurrentStudio(world.records, world.clock, a_sending_address())
    world.submit = SubmitDropOff(
        world.records,
        world.ids,
        world.photos,
        world.inspector,
        world.limiter,
        world.hasher,
        world.clock,
        world.studio,
    )


def submission_commits(world: World) -> list[tuple[Change, ...]]:
    """The commits that stored a submission (the studio's seeding is another commit)."""
    return [c for c in world.records.commits if any(isinstance(ch.item, Submission) for ch in c)]


def refused(world: World, request: SubmitRequest) -> dict[str, str]:
    with pytest.raises(InvalidDetails) as raised:
        world.submit(request)
    return dict(raised.value.errors)


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, object]]:
    return [vars(r) for r in caplog.records if r.getMessage() == name]


def assert_nothing_stored(world: World) -> None:
    assert submission_commits(world) == []
    assert world.photos.kept_count(DropOffId(1)) == 0
    assert world.ids.next_drop_off_id() == DropOffId(1)  # no number was taken


# Accepted


def test_submit_stores_the_drop_off_its_received_email_and_the_submission_together(world: World) -> None:
    result = world.submit(a_request(world))
    ac1 = DropOffId(1)
    assert result == Submitted(
        ReceivedView(ac1, 3, "Bisque", None, NOW), world.hasher.submission(TOKEN), False
    )
    [commit] = submission_commits(world)
    assert len(commit) == 3
    assert all(isinstance(change, Put) for change in commit)
    drop_off = world.records.drop_off(ac1)
    assert drop_off is not None
    assert drop_off.state is DropOffState.WAITING
    assert drop_off.photos == (PhotoRef(ac1, 1), PhotoRef(ac1, 2))
    assert drop_off.contact is not None
    assert (drop_off.contact.name, drop_off.contact.email, drop_off.contact.phone) == (
        TEST_NAME,
        TEST_EMAIL,
        TEST_PHONE_DIGITS,
    )
    email = world.records.email(ac1, EmailKind.RECEIVED)
    assert email is not None
    assert email.status is EmailStatus.PENDING
    submission = world.records.submission(result.token_hash)
    assert submission is not None
    assert submission.expires_at == NOW + SUBMISSION_LIFETIME
    assert world.photos.kept_count(ac1) == 4  # two photos, two sizes each


def test_a_glaze_drop_off_keeps_the_glaze_types_name(world: World) -> None:
    result = world.submit(a_request(world, firing_type="glaze", glaze_type="house-dip-glaze"))
    assert (result.view.firing_type, result.view.glaze_type) == ("Glaze", "House dip glaze")


def test_submit_issues_increasing_ids(world: World) -> None:
    world.ids.skip(4)  # AC-4 was the last issued
    assert world.submit(a_request(world)).view.id == DropOffId(5)
    assert world.submit(a_request(world, token=a_token(2))).view.id == DropOffId(6)


def test_two_submissions_in_a_row_get_their_own_ids(world: World) -> None:
    first = world.submit(a_request(world))
    second = world.submit(a_request(world, token=a_token(2)))
    assert (first.view.id, second.view.id) == (DropOffId(1), DropOffId(2))
    assert not first.repeated
    assert not second.repeated
    assert len(submission_commits(world)) == 2


def test_submit_discards_the_uploads_once_committed(world: World) -> None:
    slots = world.uploaded(PHOTO, PHOTO_2)
    world.submit(a_request(world, slots))
    assert world.photos.upload_count() == 0
    for slot in slots:
        with pytest.raises(UploadMissing):
            world.photos.read_upload(slot)


def test_a_slot_cannot_make_a_second_drop_off(world: World) -> None:
    slots = world.uploaded(PHOTO, PHOTO_2)
    world.submit(a_request(world, slots))
    errors = refused(world, a_request(world, slots, token=a_token(2)))
    assert errors == {"photo.1": "photo.missing", "photo.2": "photo.missing"}
    assert len(submission_commits(world)) == 1


def test_a_duplicated_slot_counts_once(world: World) -> None:
    first, second = world.uploaded(PHOTO, PHOTO_2)
    result = world.submit(a_request(world, (first, first, second)))
    drop_off = world.records.drop_off(result.view.id)
    assert drop_off is not None
    assert len(drop_off.photos) == 2
    assert world.photos.read(PhotoRef(result.view.id, 1), PhotoSize.FULL) == PHOTO
    assert world.photos.read(PhotoRef(result.view.id, 2), PhotoSize.FULL) == PHOTO_2


# The token


def test_the_same_token_twice_returns_the_same_id_and_stores_nothing_more(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    request = a_request(world)
    first = world.submit(request)
    hits = len(world.limiter.keys_hit)
    again = world.submit(request)
    assert again == dataclasses.replace(first, repeated=True)
    assert len(submission_commits(world)) == 1
    assert len(world.limiter.keys_hit) == hits
    assert world.ids.next_drop_off_id() == DropOffId(2)
    [repeat] = events(caplog, "drop_off_repeated")
    assert repeat["drop_off_id"] == "AC-1"


@pytest.mark.parametrize("token", ["a" * 21, "a" * 65, "made-up/submission-token-0001", "", TOKEN + "\n"])
def test_an_expired_or_missing_token_is_refused(
    world: World, token: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    assert refused(world, a_request(world, token=token)) == {"form": "form.expired"}
    assert world.limiter.keys_hit == []
    assert world.records.reads == []
    assert [e["reason"] for e in events(caplog, "drop_off_refused")] == ["form_expired"]


@pytest.mark.parametrize("device", ["", "short", "made-up device cookie 0123456789", "x" * 65])
def test_a_missing_or_malformed_device_is_refused_before_counting(world: World, device: str) -> None:
    assert refused(world, a_request(world, device=device)) == {"form": "form.expired"}
    assert world.limiter.keys_hit == []
    assert world.records.reads == []


def test_an_expired_stored_token_is_refused_before_counting(world: World) -> None:
    world.submit(a_request(world))
    world.clock.advance(SUBMISSION_LIFETIME)  # exactly expires_at; the TTL hasn't deleted it
    hits = len(world.limiter.keys_hit)
    assert refused(world, a_request(world)) == {"form": "form.expired"}
    assert len(world.limiter.keys_hit) == hits
    assert len(submission_commits(world)) == 1


# The rate limit (#2)


def test_the_eleventh_submission_from_a_device_in_10_minutes_is_refused(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    for number in range(DEVICE_LIMIT.limit):
        world.submit(a_request(world, token=a_token(number)))
    request = a_request(world, token=a_token(99))
    reads = list(world.photos.read_uploads)
    with pytest.raises(TooManySubmissions):
        world.submit(request)
    assert len(submission_commits(world)) == DEVICE_LIMIT.limit
    assert [e["reason"] for e in events(caplog, "drop_off_refused")] == ["device_limit"]
    # The limit comes before any photo is read or any number is taken.
    assert world.photos.read_uploads == reads
    assert world.ids.next_drop_off_id() == DropOffId(DEVICE_LIMIT.limit + 1)


def test_it_is_allowed_again_after_10_minutes(world: World) -> None:
    for number in range(DEVICE_LIMIT.limit):
        world.submit(a_request(world, token=a_token(number)))
    world.clock.advance(DEVICE_LIMIT.window)
    assert world.submit(a_request(world, token=a_token(99))).view.id == DropOffId(11)


def test_a_device_over_its_limit_isnt_counted_against_the_address(world: World) -> None:
    for number in range(DEVICE_LIMIT.limit + 5):
        with contextlib.suppress(TooManySubmissions):
            world.submit(a_request(world, token=a_token(number)))
    address_key = world.hasher.address(SOURCE_ADDRESS)
    assert world.limiter.keys_hit.count(address_key) == DEVICE_LIMIT.limit


def test_the_thirty_first_from_one_address_is_refused_across_devices(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    for number in range(ADDRESS_LIMIT.limit):
        world.submit(a_request(world, token=a_token(number), device=a_device(number)))
    with pytest.raises(TooManySubmissions):
        world.submit(a_request(world, token=a_token(99), device=a_device(99)))
    assert [e["reason"] for e in events(caplog, "drop_off_refused")] == ["address_limit"]


def test_submit_fails_closed_when_the_limiter_is_unavailable(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    request = a_request(world)
    world.limiter.fail_with = RecordsUnavailable("ProvisionedThroughputExceededException")
    with pytest.raises(RecordsUnavailable):
        world.submit(request)
    assert world.photos.read_uploads == []  # nothing read before the limit
    assert_nothing_stored(world)  # and no number taken
    [event] = events(caplog, "drop_off_refused")
    assert (event["reason"], event["error_code"]) == (
        "limiter_unavailable",
        "ProvisionedThroughputExceededException",
    )
    assert event["levelno"] == logging.WARNING


def test_no_raw_cookie_address_or_token_reaches_the_records_or_the_limiter(world: World) -> None:
    world.submit(a_request(world))
    assert world.limiter.keys_hit
    assert all(key.startswith(("device#", "address#")) for key in world.limiter.keys_hit)
    stored = repr([dataclasses.asdict(change.item) for commit in world.records.commits for change in commit])
    for raw in (TOKEN, DEVICE, SOURCE_ADDRESS):
        assert raw not in stored
        assert all(raw not in key for key in world.limiter.keys_hit)
    [submission] = [c.item for c in submission_commits(world)[0] if isinstance(c.item, Submission)]
    assert submission.token_hash.startswith("submission#")


# Fields and photos


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"name": "  "}, {"name": "name.required"}),
        ({"name": "x" * 101}, {"name": "name.too_long"}),
        ({"email": ""}, {"email": "email.required"}),
        ({"phone": ""}, {"phone": "phone.required"}),
        ({"email": "not-an-address"}, {"email": "email.invalid"}),
        ({"phone": "12"}, {"phone": "phone.invalid"}),
        ({"pieces": "0"}, {"pieces": "pieces.invalid"}),
        ({"pieces": "51"}, {"pieces": "pieces.invalid"}),
        ({"firing_type": "raku"}, {"firing_type": "firing_type.unknown"}),
        ({"firing_type": ""}, {"firing_type": "firing_type.required"}),
        ({"glaze_type": "house-dip-glaze"}, {"glaze_type": "glaze_type.not_allowed"}),
        ({"firing_type": "glaze"}, {"glaze_type": "glaze_type.required"}),
        ({"firing_type": "glaze", "glaze_type": "lustre"}, {"glaze_type": "glaze_type.unknown"}),
    ],
)
def test_each_bad_field_is_refused_and_nothing_is_stored(
    world: World, overrides: dict[str, str], expected: dict[str, str]
) -> None:
    slots = world.uploaded(PHOTO, PHOTO_2)
    assert refused(world, a_request(world, slots, **overrides)) == expected
    assert_nothing_stored(world)
    assert world.photos.upload_count() == 2  # kept for a retry


def test_no_photo_is_refused(world: World) -> None:
    assert refused(world, a_request(world, ())) == {"photos": "photos.count"}
    assert_nothing_stored(world)


@pytest.mark.parametrize(
    ("data", "key"),
    [
        (NOT_IMAGE, "photo.not_image"),
        (TOO_LARGE, "photo.too_large"),
        (TOO_MANY_PIXELS, "photo.too_many_pixels"),
    ],
)
def test_a_refused_photo_is_refused_next_to_it(world: World, data: bytes, key: str) -> None:
    slots = world.uploaded(PHOTO, data + b"-made-up")
    assert refused(world, a_request(world, slots)) == {"photo.2": key}
    assert_nothing_stored(world)


def test_a_photo_that_isnt_an_image_is_refused_next_to_it(world: World) -> None:
    slots = world.uploaded(PHOTO, NOT_IMAGE)
    assert refused(world, a_request(world, slots)) == {"photo.2": "photo.not_image"}


def test_a_photo_with_too_many_pixels_is_refused(world: World) -> None:
    slots = world.uploaded(TOO_MANY_PIXELS)
    assert refused(world, a_request(world, slots)) == {"photo.1": "photo.too_many_pixels"}
    assert_nothing_stored(world)


def test_a_photo_over_10_mb_is_refused(world: World) -> None:
    # The store refuses an upload over 10 MB (S3's content-length-range), so none is kept.
    slots = world.uploaded(PHOTO, b"x" * (PHOTO_MAX_BYTES + 1))
    assert refused(world, a_request(world, slots)) == {"photo.2": "photo.missing"}
    slots = world.uploaded(TOO_LARGE)
    assert refused(world, a_request(world, slots)) == {"photo.1": "photo.too_large"}


def test_a_missing_upload_is_refused(world: World) -> None:
    [slot] = world.photos.upload_slots(1, NOW)
    assert refused(world, a_request(world, (slot.slot_id,))) == {"photo.1": "photo.missing"}
    assert_nothing_stored(world)


def test_field_and_photo_errors_are_reported_together(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    slots = world.uploaded(NOT_IMAGE, PHOTO)
    errors = refused(world, a_request(world, slots, email="nope", pieces="x"))
    assert errors == {"email": "email.invalid", "pieces": "pieces.invalid", "photo.1": "photo.not_image"}
    [event] = events(caplog, "drop_off_refused")
    assert (event["reason"], event["fields"]) == ("invalid_details", "email,photo.1,pieces")


@pytest.mark.parametrize(
    "bad",
    ["a" * 21, "a" * 23, "a" * 21 + "/", "a" * 21 + ".", "../uploads/xx-made-up-x"],
)
def test_a_malformed_slot_is_refused_before_any_read(world: World, bad: str) -> None:
    [good] = world.uploaded(PHOTO)
    assert refused(world, a_request(world, (good, bad))) == {"photos": "photos.count"}
    assert world.photos.read_uploads == []
    assert_nothing_stored(world)


def test_a_seventh_slot_is_refused_before_any_read(world: World) -> None:
    slots = world.uploaded(*[PHOTO] * 6) + world.uploaded(PHOTO)
    assert refused(world, a_request(world, slots)) == {"photos": "photos.count"}
    assert world.photos.read_uploads == []


def test_six_photos_are_accepted(world: World) -> None:
    result = world.submit(a_request(world, world.uploaded(*[PHOTO] * 6)))
    drop_off = world.records.drop_off(result.view.id)
    assert drop_off is not None
    assert len(drop_off.photos) == 6


def test_a_refused_submit_keeps_the_uploads_for_a_retry(world: World) -> None:
    slots = world.uploaded(PHOTO, PHOTO_2)
    refused(world, a_request(world, slots, email="nope"))
    assert world.photos.upload_count() == 2
    assert world.submit(a_request(world, slots)).view.id == DropOffId(1)


# Races, taken numbers and failures


class RaceRecords(MemoryRecords):
    """Another request with the same token commits AC-99 just before this one."""

    def commit(self, changes: Sequence[Change]) -> None:
        mine = [c.item for c in changes if isinstance(c.item, Submission)]
        if mine and self.submission(mine[0].token_hash) is None:
            winner = dataclasses.replace(mine[0], drop_off_id=DropOffId(99))
            super().commit([Put(winner)])
        super().commit(changes)


def test_a_race_on_the_same_token_returns_the_first_and_deletes_the_kept_photos(world: World) -> None:
    rebuilt(world, records=RaceRecords())
    result = world.submit(a_request(world))
    assert (result.view.id, result.repeated) == (DropOffId(99), True)
    assert world.photos.kept_count(DropOffId(1)) == 0
    assert world.records.drop_off(DropOffId(1)) is None
    assert world.photos.upload_count() == 0  # the winner's drop-off used them


class UnreadableAfterConflict(MemoryRecords):
    """The drop-off's key is taken, and the table can't be read right after."""

    def commit(self, changes: Sequence[Change]) -> None:
        try:
            super().commit(changes)
        except Conflict:
            self.fail_reads_with = RecordsUnavailable("InternalServerError")
            raise


def test_an_unreadable_winner_after_a_conflict_raises_unavailable_with_photos_deleted(world: World) -> None:
    rebuilt(world, records=UnreadableAfterConflict())
    world.records.commit([Put(a_drop_off(1))])
    with pytest.raises(RecordsUnavailable):
        world.submit(a_request(world))
    assert world.photos.kept_count(DropOffId(1)) == 0
    assert world.photos.upload_count() == 2


class LandedThenConflict(MemoryRecords):
    """An adapter that raises `Conflict` although its own transaction landed."""

    def commit(self, changes: Sequence[Change]) -> None:
        super().commit(changes)
        if any(isinstance(c.item, Submission) for c in changes):
            raise Conflict()


def test_a_conflict_whose_own_commit_landed_keeps_its_photos(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    rebuilt(world, records=LandedThenConflict())
    result = world.submit(a_request(world))
    assert (result.view.id, result.repeated) == (DropOffId(1), False)
    assert world.records.drop_off(DropOffId(1)) is not None
    assert world.photos.kept_count(DropOffId(1)) == 4
    assert world.photos.upload_count() == 0
    assert events(caplog, "photos_not_deleted") == []
    assert events(caplog, "drop_off_id_skipped") == []
    [submitted] = events(caplog, "drop_off_submitted")
    assert submitted["drop_off_id"] == "AC-1"


class LateWinnerRecords(MemoryRecords):
    """The first commit meets a transaction in flight (`Conflict`, nothing written, no
    winner visible yet); by the second try the same token's other request has landed."""

    def __init__(self) -> None:
        super().__init__()
        self.tries = 0

    def commit(self, changes: Sequence[Change]) -> None:
        mine = [c.item for c in changes if isinstance(c.item, Submission)]
        if mine:
            self.tries += 1
            if self.tries == 1:
                raise Conflict()
            if self.submission(mine[0].token_hash) is None:
                super().commit([Put(dataclasses.replace(mine[0], drop_off_id=DropOffId(99)))])
        super().commit(changes)


def test_a_winner_seen_on_the_second_try_is_returned(world: World) -> None:
    rebuilt(world, records=LateWinnerRecords())
    result = world.submit(a_request(world))
    assert (result.view.id, result.repeated) == (DropOffId(99), True)
    assert world.photos.kept_count(DropOffId(1)) == 0
    assert world.photos.kept_count(DropOffId(2)) == 0


def test_a_taken_drop_off_key_takes_the_next_number(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    world.records.commit([Put(a_drop_off(1))])  # a counter that went backwards
    result = world.submit(a_request(world))
    assert result.view.id == DropOffId(2)
    assert world.photos.kept_count(DropOffId(1)) == 0
    [skipped] = events(caplog, "drop_off_id_skipped")
    assert (skipped["drop_off_id"], skipped["reason"]) == ("AC-1", "conflict")


def test_three_conflicts_raise_the_last(world: World) -> None:
    world.records.commit([Put(a_drop_off(n)) for n in (1, 2, 3)])
    with pytest.raises(Conflict):
        world.submit(a_request(world))
    assert submission_commits(world) == []
    assert all(world.photos.kept_count(DropOffId(n)) == 0 for n in (1, 2, 3))
    assert world.photos.upload_count() == 2


def a_kept_photo() -> CheckedPhoto:
    return CheckedPhoto(full=b"made-up-full", thumb=b"made-up-thumb")


def test_photos_already_kept_takes_the_next_number(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    world.photos.keep(DropOffId(1), [a_kept_photo()])
    result = world.submit(a_request(world))
    assert result.view.id == DropOffId(2)
    assert (
        world.photos.read(PhotoRef(DropOffId(1), 1), PhotoSize.FULL) == b"made-up-full"
    )  # never overwritten
    [skipped] = events(caplog, "drop_off_id_skipped")
    assert (skipped["drop_off_id"], skipped["reason"]) == ("AC-1", "photos_already_kept")


def test_photos_already_kept_three_times_raises(world: World) -> None:
    for n in (1, 2, 3):
        world.photos.keep(DropOffId(n), [a_kept_photo()])
    with pytest.raises(PhotosAlreadyKept):
        world.submit(a_request(world))
    assert submission_commits(world) == []
    assert world.photos.upload_count() == 2


def arm(world: World, error: Exception) -> None:
    """Fails the drop-off's commit (the studio is seeded first, by its own commit)."""
    world.studio()
    world.records.fail_next_commit_with = error


@pytest.mark.parametrize("error", [RecordsUnavailable("InternalServerError"), RuntimeError("made-up")])
def test_a_failed_commit_deletes_the_kept_photos_and_raises(world: World, error: Exception) -> None:
    arm(world, error)
    with pytest.raises(type(error)):
        world.submit(a_request(world))
    assert world.photos.kept_count(DropOffId(1)) == 0
    assert submission_commits(world) == []
    assert world.photos.upload_count() == 2  # the same submit can be sent again
    assert world.submit(a_request(world)).view.id == DropOffId(2)


class FailingDelete(MemoryPhotoStore):
    def delete_drop_off(self, drop_off_id: DropOffId) -> None:
        raise PhotosUnavailable("SlowDown")


def test_a_failed_cleanup_logs_and_raises_the_commit_error(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    rebuilt(world, photos=FailingDelete())
    arm(world, RecordsUnavailable("InternalServerError"))
    with pytest.raises(RecordsUnavailable) as raised:
        world.submit(a_request(world))
    assert raised.value.code == "InternalServerError"
    assert world.photos.kept_count(DropOffId(1)) == 4  # left for the backstop
    [event] = events(caplog, "photos_not_deleted")
    assert (event["drop_off_id"], event["error_code"], event["levelno"]) == (
        "AC-1",
        "SlowDown",
        logging.ERROR,
    )


def test_a_failed_cleanup_after_a_conflict_raises_the_conflict(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    rebuilt(world, photos=FailingDelete())
    world.records.commit([Put(a_drop_off(1))])
    with pytest.raises(Conflict):
        world.submit(a_request(world))
    [event] = events(caplog, "photos_not_deleted")
    assert (event["drop_off_id"], event["error_code"]) == ("AC-1", "SlowDown")
    assert events(caplog, "drop_off_id_skipped") == []  # no second number tried


def test_a_race_with_a_failed_cleanup_still_returns_the_first(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    rebuilt(world, records=RaceRecords(), photos=FailingDelete())
    result = world.submit(a_request(world))
    assert (result.view.id, result.repeated) == (DropOffId(99), True)
    [event] = events(caplog, "photos_not_deleted")
    assert event["drop_off_id"] == "AC-1"


class FailingKeep(MemoryPhotoStore):
    def keep(self, drop_off_id: DropOffId, photos: Sequence[CheckedPhoto]) -> tuple[PhotoRef, ...]:
        raise PhotosUnavailable("SlowDown")


def test_photos_unavailable_while_keeping_goes_up_and_nothing_is_stored(world: World) -> None:
    rebuilt(world, photos=FailingKeep())
    with pytest.raises(PhotosUnavailable):
        world.submit(a_request(world))
    assert submission_commits(world) == []
    assert world.photos.upload_count() == 2
    assert world.ids.next_drop_off_id() == DropOffId(2)  # AC-1 is skipped, as the ID contract allows


class TimedOutRecords(MemoryRecords):
    """The drop-off's commit raises a timeout; it `lands` or not, and afterwards the table
    can be `unreadable`."""

    def __init__(self, *, lands: bool, unreadable: bool = False) -> None:
        super().__init__()
        self.lands = lands
        self.unreadable = unreadable

    def commit(self, changes: Sequence[Change]) -> None:
        if not any(isinstance(c.item, Submission) for c in changes):
            super().commit(changes)
            return
        if self.lands:
            super().commit(changes)
        if self.unreadable:
            self.fail_reads_with = RecordsUnavailable("InternalServerError")
        raise RecordsUnavailable("RequestTimeout")


def test_a_commit_that_timed_out_but_landed_keeps_its_photos(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    rebuilt(world, records=TimedOutRecords(lands=True))
    result = world.submit(a_request(world))
    assert (result.view.id, result.repeated) == (DropOffId(1), False)
    assert world.photos.kept_count(DropOffId(1)) == 4
    assert world.photos.upload_count() == 0
    assert events(caplog, "drop_off_submitted")


def test_a_commit_that_timed_out_and_didnt_land_deletes_the_photos(world: World) -> None:
    rebuilt(world, records=TimedOutRecords(lands=False))
    with pytest.raises(RecordsUnavailable):
        world.submit(a_request(world))
    assert world.photos.kept_count(DropOffId(1)) == 0


class LostToTheSameToken(TimedOutRecords):
    """The drop-off's commit times out without landing, and meanwhile the same token's
    other request committed AC-99."""

    def commit(self, changes: Sequence[Change]) -> None:
        mine = [c.item for c in changes if isinstance(c.item, Submission)]
        if mine and self.submission(mine[0].token_hash) is None:
            MemoryRecords.commit(self, [Put(dataclasses.replace(mine[0], drop_off_id=DropOffId(99)))])
        super().commit(changes)


def test_a_timed_out_commit_that_lost_to_the_same_token_deletes_its_photos(world: World) -> None:
    rebuilt(world, records=LostToTheSameToken(lands=False))
    with pytest.raises(RecordsUnavailable):
        world.submit(a_request(world))
    assert world.photos.kept_count(DropOffId(1)) == 0
    assert world.photos.upload_count() == 2


def test_an_unreadable_outcome_leaves_the_photos_and_raises(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    rebuilt(world, records=TimedOutRecords(lands=False, unreadable=True))
    with pytest.raises(RecordsUnavailable) as raised:
        world.submit(a_request(world))
    assert raised.value.code == "RequestTimeout"
    assert world.photos.kept_count(DropOffId(1)) == 4
    [event] = events(caplog, "photos_not_deleted")
    assert (event["drop_off_id"], event["error_code"]) == ("AC-1", "InternalServerError")


class FailingDiscard(MemoryPhotoStore):
    def discard_uploads(self, slot_ids: Sequence[str]) -> None:
        raise PhotosUnavailable("SlowDown")


def test_a_failed_discard_still_returns_the_drop_off(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    rebuilt(world, photos=FailingDiscard())
    assert world.submit(a_request(world)).view.id == DropOffId(1)
    [event] = events(caplog, "uploads_not_discarded")
    assert (event["drop_off_id"], event["error_code"], event["levelno"]) == (
        "AC-1",
        "SlowDown",
        logging.WARNING,
    )


class BrokenDiscard(MemoryPhotoStore):
    def discard_uploads(self, slot_ids: Sequence[str]) -> None:
        raise RuntimeError("made-up")


def test_any_failed_discard_still_returns_the_stored_drop_off(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    rebuilt(world, photos=BrokenDiscard())
    result = world.submit(a_request(world))
    assert (result.view.id, result.repeated) == (DropOffId(1), False)
    assert world.records.drop_off(DropOffId(1)) is not None
    [event] = events(caplog, "uploads_not_discarded")
    assert (event["drop_off_id"], event["error_code"], event["levelno"]) == (
        "AC-1",
        "RuntimeError",
        logging.WARNING,
    )


class DoubleTapPhotos(MemoryPhotoStore):
    """The other request of a double tap commits and uses the uploads up while this one
    reads them."""

    def __init__(self) -> None:
        super().__init__()
        self.on_first_read: Callable[[], None] | None = None

    def read_upload(self, slot_id: str) -> bytes:
        if self.on_first_read is not None:
            hook, self.on_first_read = self.on_first_read, None
            hook()
        return super().read_upload(slot_id)


def test_a_double_tap_that_lost_the_uploads_returns_the_winner(world: World) -> None:
    photos = DoubleTapPhotos()
    rebuilt(world, photos=photos)
    request = a_request(world)

    def other_request_wins() -> None:
        token_hash = world.hasher.submission(TOKEN)
        winner = Submission(token_hash, DropOffId(7), 3, "Bisque", None, NOW, NOW + SUBMISSION_LIFETIME)
        world.records.commit([Put(winner)])
        photos.discard_uploads(request.upload_slots)

    photos.on_first_read = other_request_wins
    result = world.submit(request)
    assert (result.view.id, result.repeated) == (DropOffId(7), True)
    assert world.ids.next_drop_off_id() == DropOffId(1)


@pytest.mark.parametrize(
    ("break_it", "error"),
    [
        (
            lambda w: setattr(w.secrets, "fail_with", SecretsUnavailable("ThrottlingException")),
            SecretsUnavailable,
        ),
        (lambda w: setattr(w.ids, "fail_with", IdsUnavailable("InternalServerError")), IdsUnavailable),
        (
            lambda w: setattr(w.records, "fail_reads_with", RecordsUnavailable("InternalServerError")),
            RecordsUnavailable,
        ),
    ],
)
def test_an_unavailable_port_goes_up_and_nothing_is_kept(
    world: World, break_it: Callable[[World], None], error: type[Exception]
) -> None:
    request = a_request(world)
    break_it(world)
    with pytest.raises(error):
        world.submit(request)
    world.ids.fail_with = None
    world.records.fail_reads_with = None
    assert world.photos.kept_count(DropOffId(1)) == 0
    assert submission_commits(world) == []
    assert world.photos.upload_count() == 2


def test_photos_unavailable_while_reading_goes_up(world: World) -> None:
    request = a_request(world)
    world.photos.fail_with = PhotosUnavailable("SlowDown")
    with pytest.raises(PhotosUnavailable):
        world.submit(request)
    assert submission_commits(world) == []


# Personal details


def test_the_request_repr_holds_no_personal_detail(world: World) -> None:
    request = a_request(world, pieces="made-up-pieces-text", firing_type="made-up-firing-text")
    text = repr(request)
    assert "made-up-pieces-text" not in text
    assert "made-up-firing-text" not in text
    request = a_request(world)
    text = repr(request)
    for value in (TEST_NAME, TEST_EMAIL, TEST_PHONE, TOKEN, DEVICE, SOURCE_ADDRESS, *request.upload_slots):
        assert value not in text
    result = world.submit(request)
    assert result.token_hash not in repr(result)


def test_nothing_logged_by_submit_holds_personal_details(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    world.submit(a_request(world))  # accepted
    world.submit(a_request(world))  # repeated
    refused(world, a_request(world, token=a_token(2), email="nope"))  # a field
    arm(world, RecordsUnavailable("InternalServerError"))
    with pytest.raises(RecordsUnavailable):  # failed at commit
        world.submit(a_request(world, token=a_token(3)))
    for number in range(DEVICE_LIMIT.limit):  # the limit
        try:
            world.submit(a_request(world, token=a_token(10 + number)))
        except TooManySubmissions:
            break
    else:
        pytest.fail("the device limit was never reached")
    # Every token used shares this prefix, and every device cookie the default's.
    raw = (
        TEST_NAME,
        TEST_EMAIL,
        TEST_PHONE,
        TEST_PHONE_DIGITS,
        "made-up-submission-token-",
        DEVICE,
        SOURCE_ADDRESS,
    )
    assert caplog.records
    for record in caplog.records:
        assert record.getMessage() == record.__dict__["event"]
        text = record.getMessage() + repr(vars(record))
        for value in raw:
            assert value not in text
        assert "submission#" not in text
        assert "device#" not in text
