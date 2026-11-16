"""`IdNumbers` in memory: one counter per kind."""

from asmbly_ceramics.domain.ids import DropOffId, LoadId, NoteId


class MemoryIdNumbers:
    def __init__(self) -> None:
        self._drop_off = 0
        self._load = 0
        self._note = 0
        self.fail_with: Exception | None = None

    def next_drop_off_id(self) -> DropOffId:
        self._fail()
        self._drop_off += 1
        return DropOffId(self._drop_off)

    def next_load_id(self) -> LoadId:
        self._fail()
        self._load += 1
        return LoadId(self._load)

    def next_note_id(self) -> NoteId:
        self._fail()
        self._note += 1
        return NoteId(self._note)

    def skip(self, n: int) -> None:
        """Leave a gap of `n` numbers in every counter, as a lost write would."""
        if n < 1:
            raise ValueError("a gap is at least 1 number")
        self._drop_off += n
        self._load += n
        self._note += n

    def _fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with
