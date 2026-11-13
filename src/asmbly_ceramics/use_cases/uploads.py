"""Upload slots for the form's photos (#2): 1 to 6 at a time, rate limited, failing closed."""

import logging
from dataclasses import dataclass, field

from asmbly_ceramics.domain.errors import InvalidDetails, TooManySubmissions
from asmbly_ceramics.domain.limits import SLOT_ADDRESS_LIMIT, SLOT_DEVICE_LIMIT
from asmbly_ceramics.domain.photos import PHOTO_COUNT_KEY, UploadSlot, is_photo_count
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.photos import PhotoStore
from asmbly_ceramics.ports.rate_limit import RateLimiter
from asmbly_ceramics.use_cases.keys import KeyHasher, is_form_token
from asmbly_ceramics.use_cases.log import log_event


@dataclass(frozen=True, slots=True)
class SlotRequest:
    count: int  # `is_photo_count`: PHOTOS_MIN to PHOTOS_MAX
    device: str = field(repr=False)  # the raw device cookie: hashed, never stored or logged
    source_address: str = field(repr=False)  # the last X-Forwarded-For value


class RequestUploadSlots:
    def __init__(self, photos: PhotoStore, limiter: RateLimiter, hasher: KeyHasher, clock: Clock) -> None:
        self._photos = photos
        self._limiter = limiter
        self._hasher = hasher
        self._clock = clock

    def __call__(self, request: SlotRequest) -> list[UploadSlot]:
        count = request.count
        if not is_photo_count(count):
            _refused("invalid_details")
            raise InvalidDetails({"photos": PHOTO_COUNT_KEY})
        if not is_form_token(request.device):
            # Checked before counting, so callers without a cookie never share one bucket.
            _refused("form_expired")
            raise InvalidDetails({"form": "form.expired"})
        now = self._clock.now()
        # Hashed before counting: a key that can't be read goes up with nothing counted.
        device_key = self._hasher.slots_device(request.device)
        address_key = self._hasher.slots_address(request.source_address)
        try:
            # The device first. A device already over its limit is refused without
            # counting against the address, so one phone retrying can't fill the bucket
            # everyone on the studio's wifi shares; a new cookie is counted by both.
            device_ok = self._limiter.hit(device_key, SLOT_DEVICE_LIMIT, now)
            address_ok = device_ok and self._limiter.hit(address_key, SLOT_ADDRESS_LIMIT, now)
        except RecordsUnavailable as error:
            # Fails closed: no slot without a count.
            log_event(
                "upload_slots_refused",
                level=logging.WARNING,
                reason="limiter_unavailable",
                error_code=error.code,
            )
            raise
        if not device_ok:
            _refused("device_limit")
            raise TooManySubmissions()
        if not address_ok:
            _refused("address_limit")
            raise TooManySubmissions()
        slots = self._photos.upload_slots(count, now)
        log_event("upload_slots", count=count)
        return slots


def _refused(reason: str) -> None:
    log_event("upload_slots_refused", reason=reason)
