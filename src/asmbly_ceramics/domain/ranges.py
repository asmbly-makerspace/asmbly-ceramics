"""The date range a staff page reads by (#42, #17): the firing log's and the notes search's.

One rule for both, beside `LOG_RANGE_MAX`: a range ends on or after its start, spans at
most `LOG_RANGE_MAX`, and its read's half-open end (the day after `end`) is a real date.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from asmbly_ceramics.domain.errors import InvalidLogRange
from asmbly_ceramics.domain.limits import LOG_RANGE_MAX

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date  # inclusive, as the page shows it
    read_end: date  # the read's half-open end


def log_range(
    start: date | None,
    end: date | None,
    today: date,
    default: timedelta,
    ahead: timedelta = timedelta(0),
) -> DateRange:
    """`start..end` with the defaults filled in: no `end` is `today`, and then the read
    also reaches `ahead` past it (a load dated ahead may already be fired); no `start` is
    `default` before `end`. `InvalidLogRange` for a range ending before it starts, longer
    than `LOG_RANGE_MAX`, or so near the calendar's edge that its read's end doesn't
    exist (an `end` of `date.max`)."""
    if end is None:
        end = today
    else:
        ahead = timedelta(0)
    try:
        if start is None:
            start = end - default
        read_end = end + _ONE_DAY + ahead
    except OverflowError:  # a range at the calendar's edge
        raise InvalidLogRange() from None
    if end < start or end - start > LOG_RANGE_MAX:
        raise InvalidLogRange()
    return DateRange(start, end, read_end)
