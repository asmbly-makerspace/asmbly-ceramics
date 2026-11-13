"""The fixed numbers the stories state.

These are rules, not settings: what story #6 calls a setting (the kilns, the lists, the
pickup window and hours, the sending address) lives in `Studio`, as data.
"""

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

PIECES_MIN, PIECES_MAX = 1, 50
PHOTOS_MIN, PHOTOS_MAX = 1, 6
PHOTO_MAX_BYTES = 10 * 1024 * 1024
PHOTO_FULL_LONG_SIDE = 2048  # pixels, the copy kept and emailed
PHOTO_THUMB_LONG_SIDE = 320
NAME_MAX = 100
EMAIL_MAX = 254
PHONE_DIGITS_MIN, PHONE_DIGITS_MAX = 10, 15
MESSAGE_MAX = 1000
HOURS_TEXT_MAX = 2000
PICKUP_WINDOW_MIN, PICKUP_WINDOW_MAX = 1, 90  # days
ITEM_NAME_MAX = 60


@dataclass(frozen=True, slots=True)
class RateLimit:
    limit: int
    window: timedelta


DEVICE_LIMIT = RateLimit(limit=10, window=timedelta(minutes=10))
ADDRESS_LIMIT = RateLimit(limit=30, window=timedelta(minutes=10))
SLOT_DEVICE_LIMIT = RateLimit(limit=20, window=timedelta(minutes=10))  # requests for upload slots
SLOT_ADDRESS_LIMIT = RateLimit(limit=60, window=timedelta(minutes=10))
UPLOAD_SLOT_LIFETIME = timedelta(minutes=15)
SUBMISSION_LIFETIME = timedelta(days=1)
OVERDUE_AFTER = timedelta(days=60)
LOAD_CAPACITY = 48
STALE_SENDING_AFTER = timedelta(minutes=15)
STUDIO_TZ = ZoneInfo("America/Chicago")
SENDING_DOMAIN = "asmbly.org"
