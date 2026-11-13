"""Upload slots for the form's photos (#2): 1 to 6 at a time, rate limited, failing closed."""

from dataclasses import dataclass, field

from asmbly_ceramics.domain.errors import FORM_EXPIRED_KEY, InvalidDetails
from asmbly_ceramics.domain.limits import SLOT_ADDRESS_LIMIT, SLOT_DEVICE_LIMIT
from asmbly_ceramics.domain.photos import PHOTO_COUNT_KEY, UploadSlot, is_photo_count
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.photos import PhotoStore
from asmbly_ceramics.ports.rate_limit import RateLimiter
from asmbly_ceramics.use_cases.keys import KeyHasher, is_form_token
from asmbly_ceramics.use_cases.limits import check_limits
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
            raise InvalidDetails({"form": FORM_EXPIRED_KEY})
        now = self._clock.now()
        # Hashed before counting: a key that can't be read goes up with nothing counted.
        device_key = self._hasher.slots_device(request.device)
        address_key = self._hasher.slots_address(request.source_address)
        check_limits(
            self._limiter,
            device_key=device_key,
            device_limit=SLOT_DEVICE_LIMIT,
            address_key=address_key,
            address_limit=SLOT_ADDRESS_LIMIT,
            now=now,
            refused_event="upload_slots_refused",
        )
        slots = self._photos.upload_slots(count, now)
        log_event("upload_slots", count=count)
        return slots


def _refused(reason: str) -> None:
    log_event("upload_slots_refused", reason=reason)
