"""The daily close (#7): finished drop-offs lose their personal details and photos.

A fired drop-off closes once the pickup window its ready email gave has passed (the end
of the Austin day the email named, counted with the window kept with that email, so a
shorter window set later never closes one early); a rejected one once the studio's
window has passed since the rejection. A fired drop-off whose ready email never sent
stays open: the console shows its failed email. Photos are deleted before the record is
closed, so a failure between the two leaves a drop-off the next run closes again, never a
closed drop-off whose photos remain. Logs carry drop-off IDs and codes only.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from asmbly_ceramics.domain.closing import close, is_due_to_close
from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import EmailKind
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.studio import Studio
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.errors import Unavailable
from asmbly_ceramics.ports.photos import PhotoStore
from asmbly_ceramics.ports.records import Conflict, Records, Update
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.use_cases.studio import CurrentStudio


@dataclass(frozen=True, slots=True)
class CloseReport:
    closed: tuple[DropOffId, ...]
    failed: int


class CloseFinished:
    def __init__(self, records: Records, photos: PhotoStore, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._photos = photos
        self._clock = clock
        self._studio = studio

    def __call__(self) -> CloseReport:
        """Closes every closable drop-off; a failure on one is logged and the run goes on.
        Running it again at once closes nothing more."""
        now = self._clock.now()
        studio = self._studio()
        closed: list[DropOffId] = []
        failed = 0
        for listed in self._records.drop_offs_in({DropOffState.FIRED, DropOffState.REJECTED}):
            drop_off = listed  # until the strongly consistent read below replaces it
            try:
                # The list may be stale; nothing is deleted on its word. Read the drop-off
                # itself, and decide, delete and close on that copy's version.
                current = self._records.drop_off(listed.id)
                if current is None:
                    continue
                drop_off = current
                if not self._closable(drop_off, studio, now):
                    continue
                self._photos.delete_drop_off(drop_off.id)
                self._records.commit([Update(close(drop_off, now))])
            except Conflict:
                if self._closed_elsewhere(drop_off):
                    continue  # an overlapping run closed it first
                failed += 1
                self._failed(drop_off, error_code="Conflict")
            except Exception as error:  # one drop-off's failure doesn't stop the run
                failed += 1
                if isinstance(error, Unavailable):
                    self._failed(drop_off, error_code=error.code)
                else:
                    self._failed(drop_off, error_code=type(error).__name__, reason="unexpected")
            else:
                closed.append(drop_off.id)
                log_event("drop_off_closed", drop_off_id=str(drop_off.id))
        log_event("close_run", count=len(closed))
        return CloseReport(tuple(closed), failed)

    def _closable(self, drop_off: DropOff, studio: Studio, now: datetime) -> bool:
        ready = (
            self._records.email(drop_off.id, EmailKind.READY)
            if drop_off.state is DropOffState.FIRED
            else None
        )
        return is_due_to_close(drop_off, ready, studio.pickup_window_days, now)

    def _closed_elsewhere(self, drop_off: DropOff) -> bool:
        try:
            again = self._records.drop_off(drop_off.id)
        except Unavailable:
            return False
        return again is not None and again.state is DropOffState.CLOSED

    def _failed(self, drop_off: DropOff, **fields: str) -> None:
        log_event("close_failed", level=logging.ERROR, drop_off_id=str(drop_off.id), **fields)
