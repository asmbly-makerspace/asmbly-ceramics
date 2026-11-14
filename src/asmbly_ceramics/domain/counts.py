"""The weekly counts staff see (story #7): Monday to Sunday, Austin time (epic #1).

A closed drop-off still counts: closing keeps its dates, firing type, pieces and
reason. An undone rejection has no rejection and doesn't count.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType

from asmbly_ceramics.domain.dropoff import DropOff
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.load import Load

_WEEK = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class Week:
    monday: date  # an Austin date

    def __post_init__(self) -> None:
        if self.monday.weekday() != 0:
            raise ValueError("a week starts on a Monday")

    def sunday(self) -> date:
        return self.monday + timedelta(days=6)

    def utc_bounds(self) -> tuple[datetime, datetime]:
        """[Monday 00:00, the next Monday 00:00) in Austin, as UTC times. (Midnight is never
        skipped or repeated in Austin: the clocks change at 2 AM.)"""
        start = datetime.combine(self.monday, time(0), tzinfo=STUDIO_TZ)
        end = datetime.combine(self.monday + _WEEK, time(0), tzinfo=STUDIO_TZ)
        return start.astimezone(UTC), end.astimezone(UTC)

    def holds(self, at: datetime) -> bool:
        """Whether `at` (aware) falls in this week, Austin time."""
        if at.utcoffset() is None:
            raise ValueError("a week's times are aware")
        start, end = self.utc_bounds()
        return start <= at < end


def week_containing(day: date) -> Week:
    """The Monday-to-Sunday week that holds `day` (an Austin date)."""
    return Week(day - timedelta(days=day.weekday()))


@dataclass(frozen=True, slots=True)
class WeekCounts:
    week: Week
    drop_offs: Mapping[ItemId, int]  # created this week, per firing type
    pieces: Mapping[ItemId, int]  # of the drop-offs created this week, per firing type
    loads: Mapping[ItemId, int]  # fired this week (`fired_at`), per kiln
    rejections: Mapping[ItemId, int]  # rejected this week (`rejection.at`), per reason


def count_week(
    week: Week, created: Iterable[DropOff], fired_loads: Iterable[Load], rejected: Iterable[DropOff]
) -> WeekCounts:
    """Counts what falls in `week`; anything outside it, a load not fired, or a drop-off
    without a rejection (an undone one) is left out, whatever the caller passed."""
    drop_offs: Counter[ItemId] = Counter()
    pieces: Counter[ItemId] = Counter()
    for drop_off in created:
        if week.holds(drop_off.created_at):
            drop_offs[drop_off.firing_type] += 1
            pieces[drop_off.firing_type] += drop_off.pieces
    loads: Counter[ItemId] = Counter(
        load.kiln for load in fired_loads if load.fired_at is not None and week.holds(load.fired_at)
    )
    rejections: Counter[ItemId] = Counter(
        drop_off.rejection.reason
        for drop_off in rejected
        if drop_off.rejection is not None and week.holds(drop_off.rejection.at)
    )
    return WeekCounts(
        week=week,
        drop_offs=MappingProxyType(dict(drop_offs)),
        pieces=MappingProxyType(dict(pieces)),
        loads=MappingProxyType(dict(loads)),
        rejections=MappingProxyType(dict(rejections)),
    )
