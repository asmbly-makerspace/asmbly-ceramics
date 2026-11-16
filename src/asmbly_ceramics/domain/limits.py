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
# A photo's pixels, checked before decoding: a 48-megapixel phone photo fits, and one
# inspection stays within the form function's memory (phase 7).
PHOTO_MAX_PIXELS = 50_000_000
NAME_MAX = 100
EMAIL_MAX = 254
PHONE_DIGITS_MIN, PHONE_DIGITS_MAX = 10, 15
MESSAGE_MAX = 1000
HOURS_TEXT_MAX = 2000
PICKUP_WINDOW_MIN, PICKUP_WINDOW_MAX = 1, 90  # days
ITEM_NAME_MAX = 60
# A load's firing record (#42): checks the story states, as read from the kiln's controller.
PERCENT_MIN, PERCENT_MAX = 0, 100  # % full, and how far each witness cone bent
TEMP_F_MIN, TEMP_F_MAX = 0, 2500  # max temperature
BOARD_TEMP_F_MIN, BOARD_TEMP_F_MAX = 0, 400
COST_CENTS_MAX = 10_000  # $100.00
PREHEAT_HOURS_MAX = 48  # whole hours
HOLD_MINUTES_MAX = 600
FIRING_MINUTES_MAX = 72 * 60  # "72:00"
FIRING_NUMBER_MIN, FIRING_NUMBER_MAX = 1, 100_000
# A firing note (#17): its text, and the glaze types or clay bodies it is tagged with, each.
NOTE_TEXT_MAX = 2000
NOTE_TAGS_MAX = 20


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
STALE_SENDING_AFTER = timedelta(minutes=15)  # an email sending, or pending, this long is stuck
UNSENT_EMAIL_CLOSE_AFTER = timedelta(days=30)  # fired or rejected, its email never went (#20)
STUDIO_TZ = ZoneInfo("America/Chicago")
# How far back a kiln with no counts looks for its latest numbered firing (#42): its
# fired loads are read by date, so the read stays the same size as the years go by.
NUMBERS_LOOKBACK = timedelta(days=400)
# How long before a kiln's counts' day it still looks for a load fired after the counts
# (#42): a load's date is the day staff chose, which can come well before its firing.
NUMBERS_DATE_MARGIN = timedelta(days=60)
SENDING_DOMAIN = "asmbly.org"
