from datetime import UTC, datetime, timedelta


class FixedClock:
    def __init__(self, at: datetime | None = None) -> None:
        self._now = at or datetime(2026, 11, 13, 15, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, by: timedelta) -> None:
        self._now += by
