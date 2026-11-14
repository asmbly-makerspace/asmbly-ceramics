"""The weekly counts page (#7): Monday to Sunday, Austin time, and the overdue drop-offs.

A read: logs nothing.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from asmbly_ceramics.domain.counts import WeekCounts, count_week, week_containing
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.load import LoadStatus
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.records import Records
from asmbly_ceramics.use_cases.studio import CurrentStudio
from asmbly_ceramics.use_cases.waiting import WaitingList, WaitingRow


@dataclass(frozen=True, slots=True)
class CountsView:
    counts: WeekCounts
    names: Mapping[
        tuple[CatalogList, ItemId], str
    ]  # item names, retired ones included (IDs are unique per list)
    overdue: tuple[WaitingRow, ...]  # waiting 60 days or more, oldest first


class WeeklyCounts:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio
        self._waiting = WaitingList(records, clock, studio)

    def __call__(self, day: date | None = None) -> CountsView:
        """The week holding `day` (an Austin date); this week by default."""
        studio = self._studio()
        if day is None:
            day = self._clock.now().astimezone(STUDIO_TZ).date()
        week = week_containing(day)
        start, end = week.utc_bounds()
        counts = count_week(
            week,
            self._records.drop_offs_created_between(start, end),
            # By when each load was fired, not its date: a load dated Sunday and fired on
            # Monday counts in Monday's week. `count_week` keeps only this week's.
            self._records.loads_in({LoadStatus.FIRED}),
            self._records.drop_offs_rejected_between(start, end),
        )
        names = {(which, item.id): item.name for which in CatalogList for item in studio.items(which)}
        overdue = tuple(row for row in self._waiting().rows if row.overdue)
        return CountsView(counts, MappingProxyType(names), overdue)
