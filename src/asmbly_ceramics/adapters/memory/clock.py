"""`Clock` for tests: a fixed, aware time that moves only when told, in UTC as the port says."""

from datetime import UTC, datetime, timedelta


class FixedClock:
    def __init__(self, at: datetime) -> None:
        if at.utcoffset() is None:
            raise ValueError("the clock's time is aware")
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at

    def advance(self, by: timedelta) -> None:
        self._at += by
