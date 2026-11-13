"""Numbering drop-offs and loads (#2: no two drop-offs share an ID)."""

from typing import Protocol

from asmbly_ceramics.domain.ids import DropOffId, LoadId


class IdNumbers(Protocol):
    def next_drop_off_id(self) -> DropOffId:
        """Never the same number twice, even under concurrency; gaps are allowed.
        `IdsUnavailable`."""
        ...

    def next_load_id(self) -> LoadId:
        """As `next_drop_off_id`, from its own counter. `IdsUnavailable`."""
        ...
