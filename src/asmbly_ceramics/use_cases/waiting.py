"""The console's waiting list and its search box (#3).

Reads only: neither use case logs, because a search's text may be a person's name.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.search import matches, parse_query
from asmbly_ceramics.domain.studio import CatalogItem, CatalogList, ItemStatus, Studio
from asmbly_ceramics.domain.waiting import (
    WaitingTotals,
    days_waiting,
    is_overdue,
    oldest_first,
    totals,
    waiting_order,
)
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.records import Records
from asmbly_ceramics.use_cases.studio import CurrentStudio, item_name

SEARCH_MAX = 50
"""The most rows a text search returns, oldest first."""

# A text search covers every drop-off that still has a name: closed ones have none.
_SEARCHED = frozenset({DropOffState.WAITING, DropOffState.IN_LOAD, DropOffState.FIRED, DropOffState.REJECTED})


@dataclass(frozen=True, slots=True)
class WaitingRow:
    drop_off: DropOff
    days_waiting: int  # domain.waiting.days_waiting
    overdue: bool  # domain.waiting.is_overdue: False for a drop-off that isn't waiting
    firing_type: str  # the item's name
    glaze_type: str | None


@dataclass(frozen=True, slots=True)
class WaitingView:
    rows: tuple[WaitingRow, ...]
    totals: WaitingTotals  # over every waiting drop-off, whatever the filter
    firing_types: tuple[CatalogItem, ...]  # for the filter
    # Names for `totals.pieces_by_glaze`, which the filter doesn't narrow: active glaze
    # types, and retired ones a waiting drop-off still has, in the studio's order.
    glaze_types: tuple[CatalogItem, ...]


def _row(drop_off: DropOff, studio: Studio, now: datetime) -> WaitingRow:
    return WaitingRow(
        drop_off=drop_off,
        days_waiting=days_waiting(drop_off, now),
        overdue=is_overdue(drop_off, now),
        firing_type=item_name(studio, CatalogList.FIRING_TYPES, drop_off.firing_type),
        glaze_type=(
            None
            if drop_off.glaze_type is None
            else item_name(studio, CatalogList.GLAZE_TYPES, drop_off.glaze_type)
        ),
    )


def _in_use_or_active(
    items: tuple[CatalogItem, ...], in_use: Iterable[ItemId | None]
) -> tuple[CatalogItem, ...]:
    """Active items, and retired ones a waiting drop-off still has, in the studio's order."""
    used = set(in_use)
    return tuple(item for item in items if item.status is ItemStatus.ACTIVE or item.id in used)


class WaitingList:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def __call__(self, firing_type: ItemId | None = None) -> WaitingView:
        studio = self._studio()
        now = self._clock.now()
        waiting = waiting_order(self._records.drop_offs_in({DropOffState.WAITING}))
        shown = waiting if firing_type is None else [d for d in waiting if d.firing_type == firing_type]
        return WaitingView(
            rows=tuple(_row(drop_off, studio, now) for drop_off in shown),
            totals=totals(waiting, now),
            firing_types=_in_use_or_active(studio.firing_types, (d.firing_type for d in waiting)),
            glaze_types=_in_use_or_active(studio.glaze_types, (d.glaze_type for d in waiting)),
        )


@dataclass(frozen=True, slots=True)
class Found:
    rows: tuple[WaitingRow, ...]
    truncated: bool  # more matched than `SEARCH_MAX`: the page says to type more


class FindDropOffs:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def __call__(self, raw_query: str, *, waiting_only: bool = False) -> Found:
        """By ID (any state, closed included; waiting only with `waiting_only`), or by part
        of a name: oldest first, at most `SEARCH_MAX`. An empty query finds nothing."""
        query = parse_query(raw_query)
        found: list[DropOff]
        if query.id is not None:
            drop_off = self._records.drop_off(query.id)
            if drop_off is None or (waiting_only and drop_off.state is not DropOffState.WAITING):
                return _NOTHING
            found = [drop_off]
        elif not query.text:
            return _NOTHING
        else:
            states = {DropOffState.WAITING} if waiting_only else _SEARCHED
            candidates = self._records.drop_offs_in(states)
            found = oldest_first(d for d in candidates if matches(d, query))
        studio = self._studio()
        now = self._clock.now()
        return Found(
            rows=tuple(_row(drop_off, studio, now) for drop_off in found[:SEARCH_MAX]),
            truncated=len(found) > SEARCH_MAX,
        )


_NOTHING = Found(rows=(), truncated=False)
