"""The waiting list and its totals."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import OVERDUE_AFTER


@dataclass(frozen=True, slots=True)
class WaitingTotals:
    drop_offs: Mapping[ItemId, int]  # per firing type
    pieces: Mapping[ItemId, int]  # per firing type
    pieces_by_glaze: Mapping[ItemId, int]  # per glaze type
    overdue: int


def waiting_order(drop_offs: Iterable[DropOff]) -> list[DropOff]:
    return sorted(
        (d for d in drop_offs if d.state is DropOffState.WAITING), key=lambda d: (d.created_at, d.id)
    )


def is_overdue(drop_off: DropOff, now: datetime) -> bool:
    return drop_off.state is DropOffState.WAITING and now - drop_off.created_at >= OVERDUE_AFTER


def totals(drop_offs: Iterable[DropOff], now: datetime) -> WaitingTotals:
    count: Counter[ItemId] = Counter()
    pieces: Counter[ItemId] = Counter()
    glaze: Counter[ItemId] = Counter()
    overdue = 0
    for d in waiting_order(drop_offs):
        count[d.firing_type] += 1
        pieces[d.firing_type] += d.pieces
        if d.glaze_type is not None:
            glaze[d.glaze_type] += d.pieces
        overdue += is_overdue(d, now)
    return WaitingTotals(dict(count), dict(pieces), dict(glaze), overdue)
