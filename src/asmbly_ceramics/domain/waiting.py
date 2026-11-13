"""The waiting list (story #3) and the overdue rule (#7).

Only `WAITING` drop-offs are on the list, oldest first. Days waiting are whole Austin
days: the studio's calendar days from the day it was made to today. Overdue is not a
state: a drop-off still waiting 60 (`OVERDUE_AFTER`) or more days waiting is shown as
overdue, never deleted.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import OVERDUE_AFTER, STUDIO_TZ


@dataclass(frozen=True, slots=True)
class WaitingTotals:
    drop_offs: Mapping[ItemId, int]  # per firing type
    pieces: Mapping[ItemId, int]  # per firing type
    pieces_by_glaze: Mapping[ItemId, int]  # per glaze type
    overdue: int


def oldest_first(drop_offs: Iterable[DropOff]) -> list[DropOff]:
    """Any drop-offs, oldest `created_at` first, then by ID: the waiting list's order, and
    the order for any other list of drop-offs (search results, the overdue ones)."""
    return sorted(drop_offs, key=lambda drop_off: (drop_off.created_at, drop_off.id))


def waiting_order(drop_offs: Iterable[DropOff]) -> list[DropOff]:
    """The waiting drop-offs, `oldest_first`."""
    return oldest_first(drop_off for drop_off in drop_offs if drop_off.state is DropOffState.WAITING)


def totals(drop_offs: Iterable[DropOff], now: datetime) -> WaitingTotals:
    """Drop-offs and pieces per firing type, pieces per glaze type, and how many are overdue,
    over the waiting drop-offs only."""
    _check_aware(now)
    count: Counter[ItemId] = Counter()
    pieces: Counter[ItemId] = Counter()
    by_glaze: Counter[ItemId] = Counter()
    overdue = 0
    for drop_off in drop_offs:
        if drop_off.state is not DropOffState.WAITING:
            continue
        count[drop_off.firing_type] += 1
        pieces[drop_off.firing_type] += drop_off.pieces
        if drop_off.glaze_type is not None:
            by_glaze[drop_off.glaze_type] += drop_off.pieces
        if is_overdue(drop_off, now):
            overdue += 1
    return WaitingTotals(
        drop_offs=MappingProxyType(dict(count)),
        pieces=MappingProxyType(dict(pieces)),
        pieces_by_glaze=MappingProxyType(dict(by_glaze)),
        overdue=overdue,
    )


def days_waiting(drop_off: DropOff, now: datetime) -> int:
    """Whole Austin days since the drop-off was made: 0 on the day it was made, 1 from the
    next midnight in Austin, whatever the hour, and a day is a calendar day across a
    daylight-saving change."""
    _check_aware(now)
    made_on = drop_off.created_at.astimezone(STUDIO_TZ).date()
    return (now.astimezone(STUDIO_TZ).date() - made_on).days


def is_overdue(drop_off: DropOff, now: datetime) -> bool:
    """Still waiting with `days_waiting` 60 (`OVERDUE_AFTER`) or more."""
    _check_aware(now)
    return drop_off.state is DropOffState.WAITING and days_waiting(drop_off, now) >= OVERDUE_AFTER.days


def _check_aware(now: datetime) -> None:
    if now.utcoffset() is None:
        raise ValueError("the waiting list needs an aware time")
