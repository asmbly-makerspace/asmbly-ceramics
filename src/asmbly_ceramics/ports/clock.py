"""The time, so tests choose it."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Aware, UTC."""
        ...
