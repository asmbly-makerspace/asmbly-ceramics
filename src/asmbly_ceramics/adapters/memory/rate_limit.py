from collections import defaultdict
from datetime import datetime

from asmbly_ceramics.domain.limits import RateLimit


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[datetime]] = defaultdict(list)

    def hit(self, key: str, limit: RateLimit, now: datetime) -> bool:
        self._hits[key].append(now)
        recent = [t for t in self._hits[key] if now - limit.window < t <= now]
        return len(recent) <= limit.limit
