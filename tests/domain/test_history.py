from datetime import datetime

import pytest

from asmbly_ceramics.domain.history import LoadEvent, event
from asmbly_ceramics.domain.ids import LoadId
from tests.domain.builders import NOW, STAFF, an_event

L4 = LoadId(4)


def test_event_records_who_did_what_and_when() -> None:
    assert event(L4, STAFF, NOW, "Started firing") == LoadEvent(L4, NOW, STAFF, "Started firing")
    assert an_event(4) == LoadEvent(L4, NOW, STAFF, "Started firing")


@pytest.mark.parametrize(("by", "what"), [("", "Fired"), (STAFF, ""), ("", "")])
def test_event_needs_by_and_what(by: str, what: str) -> None:
    with pytest.raises(ValueError, match="a load event needs"):
        event(L4, by, NOW, what)


def test_event_needs_aware_time() -> None:
    naive = datetime(2026, 11, 13, 18, 30)  # noqa: DTZ001 - the naive time the check refuses
    with pytest.raises(ValueError, match="aware time"):
        event(L4, STAFF, naive, "Fired")


def test_event_wording_not_in_repr() -> None:
    assert "Unmistakable" not in repr(an_event(4, "Unmistakable words"))
