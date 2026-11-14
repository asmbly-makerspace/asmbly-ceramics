"""`Clock` on the system clock, in UTC. The domain turns it into Austin time where a rule
needs the Austin day (`domain.limits.STUDIO_TZ`, with `tzdata` installed for Lambda)."""

from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
