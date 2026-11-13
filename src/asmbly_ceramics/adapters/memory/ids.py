"""`IdNumbers` in memory: two counters."""

from asmbly_ceramics.domain.ids import DropOffId, LoadId


class MemoryIdNumbers:
    def __init__(self) -> None:
        self._drop_off = 0
        self._load = 0
        self.fail_with: Exception | None = None

    def next_drop_off_id(self) -> DropOffId:
        self._fail()
        self._drop_off += 1
        return DropOffId(self._drop_off)

    def next_load_id(self) -> LoadId:
        self._fail()
        self._load += 1
        return LoadId(self._load)

    def skip(self, n: int) -> None:
        """Leave a gap of `n` numbers in both counters, as a lost write would."""
        if n < 1:
            raise ValueError("a gap is at least 1 number")
        self._drop_off += n
        self._load += n

    def _fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with
