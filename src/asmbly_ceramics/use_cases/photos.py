"""One kept photo of a drop-off, for the console (#3): the full-size copy or its
thumbnail. A read: nothing is logged.

The console's waiting list shows a thumbnail per row, each its own request, so this reads
only the drop-off's record and the photo, not the whole drop-off page (`ViewDropOff`).
"""

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.errors import NotFound
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.photos import PhotoSize
from asmbly_ceramics.ports.photos import PhotoStore, UploadMissing
from asmbly_ceramics.ports.records import Records


class ViewPhoto:
    def __init__(self, records: Records, photos: PhotoStore) -> None:
        self._records = records
        self._photos = photos

    def __call__(self, id: DropOffId, index: int, size: PhotoSize) -> bytes:
        """The photo's JPEG bytes. `NotFound` when there is no such drop-off, it is closed
        (its photos were deleted), it has no photo `index`, or the photo is gone;
        `RecordsUnavailable`, `PhotosUnavailable`."""
        drop_off = self._records.drop_off(id)
        if drop_off is None or drop_off.state is DropOffState.CLOSED:
            raise NotFound(id)
        ref = next((ref for ref in drop_off.photos if ref.index == index), None)
        if ref is None:
            raise NotFound(id)
        try:
            return self._photos.read(ref, size)
        except UploadMissing:
            raise NotFound(id) from None
