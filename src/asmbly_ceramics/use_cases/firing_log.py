"""The firing log (#42): a kiln's fired loads in a date range, as its workbook tab listed them.

It reads fired loads by their date from the index (`Records.loads_dated_between`), a
range of at most `LOG_RANGE_MAX` (`domain.ranges.log_range`), so its cost doesn't grow
with the years kept. The page shows the rows and the CSV downloads them, each with the
load's note counts from `use_cases.notes.NoteCounts`. Rows
hold staff usernames, studio items and record values, never a person's details. A read: it logs nothing.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import LOG_DEFAULT_AHEAD, LOG_DEFAULT_RANGE, STUDIO_TZ
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.ranges import log_range
from asmbly_ceramics.domain.studio import CatalogList, KilnCounts, Studio
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.records import Records
from asmbly_ceramics.use_cases.studio import CurrentStudio, item_name

_NEVER = datetime.min.replace(tzinfo=UTC)  # sorts a fired load with no `fired_at` last


class FiringKind(StrEnum):
    ALL = "all"
    TESTS = "tests"
    REGULAR = "regular"


@dataclass(frozen=True, slots=True)
class FiringLogRow:
    load: Load
    kiln: str
    firing_type: str
    cone: str | None  # the program's cone, by name
    started_by: str
    firing_started_by: str | None  # None on a load made before #42
    fired_by: str | None


@dataclass(frozen=True, slots=True)
class FiringLogView:
    rows: tuple[FiringLogRow, ...]  # newest fired first
    kiln: ItemId | None
    start: date
    end: date  # inclusive, as the page shows it
    kind: FiringKind
    counts: KilnCounts | None  # for "Firing # counts from …", when one kiln is chosen


class FiringLog:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def __call__(
        self, kiln: ItemId | None, start: date | None, end: date | None, kind: FiringKind
    ) -> FiringLogView:
        """Fired loads dated `start..end` inclusive (defaults: the last 12 weeks to today,
        Austin; with no `end`, the read also takes loads dated up to `LOG_DEFAULT_AHEAD`
        after today, as one dated ahead may already be fired, and `end` shows today), of
        `kiln` (or every kiln), of `kind`. `UnknownItem` for a kiln the studio
        doesn't have. A range longer than `LOG_RANGE_MAX` or ending before it
        starts is `InvalidLogRange`; so is an `end` of `date.max` (the read's half-open
        end is `end + 1 day`), by `domain.ranges.log_range`. Reads `loads_dated_between`
        only. A read: logs nothing."""
        studio = self._studio()
        counts = None if kiln is None else studio.item(CatalogList.KILNS, kiln).counts
        today = self._clock.now().astimezone(STUDIO_TZ).date()
        span = log_range(start, end, today, LOG_DEFAULT_RANGE, LOG_DEFAULT_AHEAD)
        dated = self._records.loads_dated_between({LoadStatus.FIRED}, span.start, span.read_end)
        loads = [
            load
            for load in dated
            if (kiln is None or load.kiln == kiln)
            and (
                kind is FiringKind.ALL
                or (kind is FiringKind.TESTS and load.test)
                or (kind is FiringKind.REGULAR and not load.test)
            )
        ]
        loads.sort(key=lambda load: (load.fired_at or _NEVER, load.id), reverse=True)
        return FiringLogView(
            rows=tuple(_row(studio, load) for load in loads),
            kiln=kiln,
            start=span.start,
            end=span.end,
            kind=kind,
            counts=counts,
        )


def _row(studio: Studio, load: Load) -> FiringLogRow:
    cone = load.record.program.cone
    return FiringLogRow(
        load=load,
        kiln=item_name(studio, CatalogList.KILNS, load.kiln),
        firing_type=item_name(studio, CatalogList.FIRING_TYPES, load.firing_type),
        cone=None if cone is None else item_name(studio, CatalogList.CONES, cone),
        started_by=load.started_by,
        firing_started_by=load.firing_started_by,
        fired_by=load.fired_by,
    )
