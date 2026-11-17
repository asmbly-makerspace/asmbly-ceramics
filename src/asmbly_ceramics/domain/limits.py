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
# The studio's daily cap on received emails (#30, decision 0008): the setting's bounds.
RECEIVED_EMAILS_PER_DAY_MIN, RECEIVED_EMAILS_PER_DAY_MAX = 1, 2000
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
# A corrected step time (#42) before this year is a typo ("1926" for "2026"), refused.
STEP_TIME_YEAR_MIN = 2000
# A firing note (#17): its text, and the glaze types or clay bodies it is tagged with, each.
NOTE_TEXT_MAX = 2000
NOTE_TAGS_MAX = 20


@dataclass(frozen=True, slots=True)
class RateLimit:
    limit: int
    window: timedelta


DEVICE_LIMIT = RateLimit(limit=10, window=timedelta(minutes=10))
ADDRESS_LIMIT = RateLimit(limit=30, window=timedelta(minutes=10))
RECIPIENT_LIMIT = RateLimit(limit=3, window=timedelta(days=1))  # drop-offs per recipient address (#18)
SLOT_DEVICE_LIMIT = RateLimit(limit=20, window=timedelta(minutes=10))  # requests for upload slots
SLOT_ADDRESS_LIMIT = RateLimit(limit=60, window=timedelta(minutes=10))
UPLOAD_SLOT_LIFETIME = timedelta(minutes=15)
SUBMISSION_LIFETIME = timedelta(days=1)
RECEIVED_CAP_WINDOW = timedelta(days=1)  # the daily cap's rolling window (decision 0008)
OVERDUE_AFTER = timedelta(days=60)
LOAD_CAPACITY = 48
STALE_SENDING_AFTER = timedelta(minutes=15)  # an email sending, or pending, this long is stuck
UNSENT_EMAIL_CLOSE_AFTER = timedelta(days=30)  # fired or rejected, its email never went (#20)
STUDIO_TZ = ZoneInfo("America/Chicago")
# How far back a kiln looks for its latest numbered firing and for the unnumbered firings
# counted after it (#42), counts or not: its fired loads are read by date, so the read
# stays the same size as the years go by.
NUMBERS_LOOKBACK = timedelta(days=400)
# How long before a kiln's counts' day it still looks for a load fired after the counts
# (#42): a load's date is the day staff chose, which can come well before its firing.
NUMBERS_DATE_MARGIN = timedelta(days=60)
# How far after the day being numbered it reads load dates (#42): a load dated ahead may
# already be fired.
NUMBERS_READ_AHEAD = timedelta(days=60)
# The firing log (#42): the longest date range one page reads, and the range it opens with.
LOG_RANGE_MAX_YEARS = 5
LOG_RANGE_MAX = timedelta(days=LOG_RANGE_MAX_YEARS * 366)
# `domain.ranges.log_range` checks a range against `LOG_RANGE_MAX`, for the log and the
# notes search alike.
LOG_DEFAULT_RANGE = timedelta(weeks=12)
# With no end chosen, the log also reads load dates this far after today: a load dated
# ahead may already be fired, and the range it opens with ends today.
LOG_DEFAULT_AHEAD = timedelta(days=60)
# Firing notes (#17): how far back the notes search looks when the page gives no start.
NOTES_DEFAULT_RANGE = timedelta(days=365)
# How far a note's `written_at` is expected to be from its load's date: a note is written
# after the firing, or while loading, before the load's date. The notes search reads the
# loads dated this much around its range in one go (any other load it needs, it reads by
# its ID), and the firing log's note counts read from this much before the earliest of
# its loads was started (a started time corrected later than the real one).
NOTE_LOAD_SLACK = timedelta(days=30)
SENDING_DOMAIN = "asmbly.org"
