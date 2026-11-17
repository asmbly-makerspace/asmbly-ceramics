"""The date range the firing log and the notes search read by: one rule for both."""

from datetime import date, timedelta

import pytest

from asmbly_ceramics.domain.errors import InvalidLogRange
from asmbly_ceramics.domain.limits import LOG_RANGE_MAX
from asmbly_ceramics.domain.ranges import DateRange, log_range

TODAY = date(2026, 11, 13)
WEEK = timedelta(weeks=1)
AHEAD = timedelta(days=60)
DAY = timedelta(days=1)


def test_defaults_end_today_and_reach_ahead() -> None:
    assert log_range(None, None, TODAY, WEEK, AHEAD) == DateRange(TODAY - WEEK, TODAY, TODAY + DAY + AHEAD)


def test_a_chosen_end_reads_nothing_ahead() -> None:
    end = TODAY - DAY
    assert log_range(None, end, TODAY, WEEK, AHEAD) == DateRange(end - WEEK, end, end + DAY)


def test_chosen_range_kept() -> None:
    start = TODAY - LOG_RANGE_MAX
    assert log_range(start, TODAY, TODAY, WEEK) == DateRange(start, TODAY, TODAY + DAY)
    assert log_range(TODAY, TODAY, TODAY, WEEK) == DateRange(TODAY, TODAY, TODAY + DAY)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (TODAY - LOG_RANGE_MAX - DAY, TODAY),  # too long
        (TODAY, TODAY - DAY),  # backwards
        (None, date.max),  # no day after the end
        (None, date.min),  # no default start
    ],
)
def test_refused(start: date | None, end: date) -> None:
    with pytest.raises(InvalidLogRange):
        log_range(start, end, TODAY, WEEK)
