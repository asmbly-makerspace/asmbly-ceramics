from typing import Protocol

from asmbly_ceramics.domain.ids import DropOffId, LoadId


class IdNumbers(Protocol):
    def next_drop_off_id(self) -> DropOffId:
        """Never the same number twice, even under concurrency; gaps allowed."""
        ...

    def next_load_id(self) -> LoadId: ...
