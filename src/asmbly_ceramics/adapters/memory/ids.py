from asmbly_ceramics.domain.ids import DropOffId, LoadId


class MemoryIdNumbers:
    def __init__(self) -> None:
        self._drop_off = 0
        self._load = 0

    def next_drop_off_id(self) -> DropOffId:
        self._drop_off += 1
        return DropOffId(self._drop_off)

    def next_load_id(self) -> LoadId:
        self._load += 1
        return LoadId(self._load)

    def skip(self, n: int) -> None:
        """Burn `n` numbers of each kind, as a failed commit would: gaps are fine."""
        self._drop_off += n
        self._load += n
