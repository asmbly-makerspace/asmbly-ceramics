"""A load's history (#42): who moved it, changed it or corrected it, and when.

`LoadEvent` is `SettingChange`'s twin for a load. Each use case that changes a load
writes its events in the same commit and decides their wording; the domain only builds
and checks them.
"""

from dataclasses import dataclass, field
from datetime import datetime

from asmbly_ceramics.domain.ids import LoadId


@dataclass(frozen=True, slots=True)
class LoadEvent:
    """One line of a load's history: who did what, and when. `what` names load IDs,
    studio items, steps, times and record values; never a person's details (it is shown
    to staff and kept with the load)."""

    load_id: LoadId
    at: datetime  # aware
    by: str  # staff username
    what: str = field(repr=False)  # "Started firing", "Fired", "Max temp: 2,236 °F", ...


def event(load_id: LoadId, by: str, at: datetime, what: str) -> LoadEvent:
    """A line of `load_id`'s history. `ValueError` for an empty `by` or `what`, or a naive `at`."""
    if not by:
        raise ValueError("a load event needs the staff username")
    if not what:
        raise ValueError("a load event needs what happened")
    if at.utcoffset() is None:
        raise ValueError("a load event needs an aware time")
    return LoadEvent(load_id=load_id, at=at, by=by, what=what)
