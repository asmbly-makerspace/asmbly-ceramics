"""`RequestUploadSlots`: 1 to 6 slots, limited per device and per address, failing closed."""

import logging
from collections.abc import Callable
from datetime import timedelta

import pytest

from asmbly_ceramics.domain.errors import InvalidDetails, TooManySubmissions
from asmbly_ceramics.domain.limits import SLOT_ADDRESS_LIMIT, SLOT_DEVICE_LIMIT, UPLOAD_SLOT_LIFETIME
from asmbly_ceramics.domain.photos import is_slot_id
from asmbly_ceramics.ports.errors import (
    PhotosUnavailable,
    RecordsUnavailable,
    SecretMissing,
    SecretsUnavailable,
)
from asmbly_ceramics.ports.secrets import SecretName
from asmbly_ceramics.use_cases.uploads import SlotRequest
from tests.domain.builders import NOW
from tests.use_cases.conftest import DEVICE, SOURCE_ADDRESS, World


def a_request(count: int = 3, device: str = DEVICE, source_address: str = SOURCE_ADDRESS) -> SlotRequest:
    return SlotRequest(count=count, device=device, source_address=source_address)


def a_device(number: int) -> str:
    return f"made-up-device-cookie-{number:010d}"


def refusals(caplog: pytest.LogCaptureFixture) -> list[object]:
    return [vars(r).get("reason") for r in caplog.records if r.getMessage() == "upload_slots_refused"]


def test_upload_slots_are_issued(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    slots = world.upload_slots(a_request(6))
    assert len(slots) == 6
    assert world.photos.slot_count() == 6
    assert all(is_slot_id(slot.slot_id) for slot in slots)
    assert all(slot.expires_at == NOW + UPLOAD_SLOT_LIFETIME for slot in slots)
    [record] = caplog.records
    assert record.getMessage() == "upload_slots"
    assert vars(record)["count"] == 6


@pytest.mark.parametrize("count", [0, 7, True, -1, "3", 2.0])
def test_upload_slots_count_must_be_1_to_6(
    world: World, count: object, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    with pytest.raises(InvalidDetails) as raised:
        world.upload_slots(a_request(count))  # type: ignore[arg-type]  # the page may pass a non-int
    assert dict(raised.value.errors) == {"photos": "photos.count"}
    assert world.limiter.keys_hit == []  # refused before counting
    assert world.photos.slot_count() == 0
    assert refusals(caplog) == ["invalid_details"]


@pytest.mark.parametrize("device", ["", "short", DEVICE + "\n", "x" * 65, "a cookie with spaces in it"])
def test_a_missing_or_malformed_device_is_refused_before_counting(
    world: World, device: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    with pytest.raises(InvalidDetails) as raised:
        world.upload_slots(a_request(device=device))
    assert dict(raised.value.errors) == {"form": "form.expired"}
    assert world.limiter.keys_hit == []
    assert world.photos.slot_count() == 0
    assert refusals(caplog) == ["form_expired"]


def test_upload_slot_requests_are_limited(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    for _ in range(SLOT_DEVICE_LIMIT.limit):
        world.upload_slots(a_request(1))
    with pytest.raises(TooManySubmissions):
        world.upload_slots(a_request(1))  # the 21st from one device
    assert refusals(caplog) == ["device_limit"]

    # The address: 60 within 10 minutes, from fresh devices, then the 61st is refused.
    caplog.clear()
    world.clock.advance(SLOT_DEVICE_LIMIT.window)
    for number in range(SLOT_ADDRESS_LIMIT.limit):
        world.upload_slots(a_request(1, device=a_device(number)))
    with pytest.raises(TooManySubmissions):
        world.upload_slots(a_request(1, device=a_device(999)))
    assert refusals(caplog) == ["address_limit"]

    # Another address isn't affected; the window rolls on.
    assert len(world.upload_slots(a_request(1, device=a_device(1000), source_address="203.0.113.8"))) == 1
    world.clock.advance(SLOT_ADDRESS_LIMIT.window + timedelta(seconds=1))
    assert len(world.upload_slots(a_request(1, device=a_device(1001)))) == 1


def test_both_limits_count_an_allowed_device(world: World) -> None:
    world.upload_slots(a_request(1))
    assert world.limiter.keys_hit == [
        world.hasher.slots_device(DEVICE),
        world.hasher.slots_address(SOURCE_ADDRESS),
    ]


def test_a_device_over_its_limit_doesnt_count_against_the_address(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    for _ in range(SLOT_DEVICE_LIMIT.limit):
        world.upload_slots(a_request(1))
    world.limiter.keys_hit.clear()
    for _ in range(SLOT_ADDRESS_LIMIT.limit):  # one phone retrying
        with pytest.raises(TooManySubmissions):
            world.upload_slots(a_request(1))
    assert set(world.limiter.keys_hit) == {world.hasher.slots_device(DEVICE)}
    assert set(refusals(caplog)) == {"device_limit"}
    # Everyone else on the same wifi still gets slots.
    assert len(world.upload_slots(a_request(1, device=a_device(1)))) == 1


@pytest.mark.parametrize(
    ("fail", "error", "match"),
    [
        (
            lambda world: setattr(world.secrets, "fail_with", SecretsUnavailable("ThrottlingException")),
            SecretsUnavailable,
            "ThrottlingException",
        ),
        (lambda world: world.secrets.remove(SecretName.HASH_KEY), SecretMissing, "hash-key"),
        (lambda world: world.secrets.set(SecretName.HASH_KEY, b"short"), ValueError, "hash-key is too short"),
    ],
)
def test_upload_slots_fail_closed_when_the_hash_key_cant_be_read(
    world: World, fail: Callable[[World], None], error: type[Exception], match: str
) -> None:
    fail(world)
    with pytest.raises(error, match=match):
        world.upload_slots(a_request(1))
    assert world.limiter.keys_hit == []
    assert world.photos.slot_count() == 0


def test_upload_slots_fail_closed_when_the_limiter_is_unavailable(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    world.limiter.fail_with = RecordsUnavailable("ProvisionedThroughputExceededException")
    with pytest.raises(RecordsUnavailable):
        world.upload_slots(a_request(2))
    assert world.photos.slot_count() == 0
    [record] = caplog.records
    assert record.getMessage() == "upload_slots_refused"
    assert record.levelno == logging.WARNING
    assert vars(record)["reason"] == "limiter_unavailable"
    assert vars(record)["error_code"] == "ProvisionedThroughputExceededException"


def test_photos_unavailable_goes_up(world: World) -> None:
    world.photos.fail_with = PhotosUnavailable("SlowDown")
    with pytest.raises(PhotosUnavailable):
        world.upload_slots(a_request(1))


def test_upload_slot_keys_are_hashes(world: World) -> None:
    world.upload_slots(a_request(1))
    assert len(world.limiter.keys_hit) == 2
    device_key, address_key = world.limiter.keys_hit
    assert device_key == world.hasher.slots_device(DEVICE)
    assert address_key == world.hasher.slots_address(SOURCE_ADDRESS)
    for key in world.limiter.keys_hit:
        assert key.startswith(("slots-device#", "slots-address#"))
        assert DEVICE not in key
        assert SOURCE_ADDRESS not in key


def test_upload_slot_refusals_log_which_limit_and_no_raw_value(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="asmbly_ceramics")
    for _ in range(SLOT_DEVICE_LIMIT.limit):
        world.upload_slots(a_request(1))
    with pytest.raises(TooManySubmissions):
        world.upload_slots(a_request(1))
    with pytest.raises(InvalidDetails):
        world.upload_slots(a_request(device="short"))
    assert refusals(caplog) == ["device_limit", "form_expired"]
    for record in caplog.records:
        text = str(vars(record))
        assert DEVICE not in text
        assert SOURCE_ADDRESS not in text
        assert "short" not in record.getMessage()


def test_the_request_prints_no_raw_value() -> None:
    assert DEVICE not in repr(a_request())
    assert SOURCE_ADDRESS not in repr(a_request())
