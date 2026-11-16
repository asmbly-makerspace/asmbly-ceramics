"""Deleting a waiting drop-off made by mistake or as a test: its personal details and
photos go at once, and no email is sent.

Photos are deleted before the record is committed, as the daily close does (#7): a
failure between the two leaves a waiting drop-off without photos, which staff delete
again, never a deleted drop-off whose photos remain. The version the page showed is
checked before anything is deleted. Logs carry the drop-off's ID and the staff username.
"""

from dataclasses import replace

from asmbly_ceramics.domain.dropoff import DropOff, delete_drop_off
from asmbly_ceramics.domain.email import EmailStatus, mark_cancelled
from asmbly_ceramics.domain.errors import NotFound
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.photos import PhotoStore
from asmbly_ceramics.ports.records import Change, Conflict, Records, Update
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.log import log_event


class DeleteDropOff:
    def __init__(self, records: Records, photos: PhotoStore, clock: Clock) -> None:
        self._records = records
        self._photos = photos
        self._clock = clock

    def __call__(self, id: DropOffId, version: int, staff: StaffMember) -> DropOff:
        """A waiting drop-off, deleted: name, email, phone and photos gone, an email not yet
        sent cancelled, in one commit. `NotFound` (deleted already), `DropOffNotDeletable`,
        `Conflict`, `PhotosUnavailable` (nothing was committed), `RecordsUnavailable`."""
        drop_off = self._records.drop_off(id)
        if drop_off is None:
            raise NotFound(id)
        deleted = delete_drop_off(drop_off, staff.username, self._clock.now())
        if drop_off.version != version:
            raise Conflict([str(id)])
        changes: list[Change] = [Update(deleted)]
        changes.extend(
            Update(mark_cancelled(email))
            for email in self._records.emails_for(id)
            if email.status in (EmailStatus.PENDING, EmailStatus.SENDING)
        )
        self._photos.delete_drop_off(id)
        self._records.commit(changes)
        log_event("drop_off_deleted", drop_off_id=str(id), user=staff.username)
        return replace(deleted, version=deleted.version + 1)
