from datetime import datetime
from typing import Protocol

from asmbly_ceramics.domain.limits import RateLimit


class RateLimiter(Protocol):
    def hit(self, key: str, limit: RateLimit, now: datetime) -> bool:
        """Counts this hit; False when over the limit."""
        ...
