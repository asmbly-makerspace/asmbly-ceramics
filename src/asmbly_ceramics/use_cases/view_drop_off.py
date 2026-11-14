"""One drop-off's console page (#3, #5): its details, its load, its emails, and whether
its rejection can still be undone. A read: nothing is logged.
"""

from dataclasses import dataclass
from datetime import datetime

from asmbly_ceramics.domain.dropoff import DropOff, undo_rejection
from asmbly_ceramics.domain.email import Email, is_history, needs_attention
from asmbly_ceramics.domain.errors import NotFound, NotRejected, UndoTooLate
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.load import Load
from asmbly_ceramics.domain.studio import CatalogItem, CatalogList
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.records import Records
from asmbly_ceramics.use_cases.studio import CurrentStudio, active_items, item_name


@dataclass(frozen=True, slots=True)
class DropOffView:
    drop_off: DropOff
    firing_type: str
    glaze_type: str | None
    rejection_reason: str | None  # the reason's name, retired or not, while rejected
    load: Load | None
    emails: tuple[Email, ...]
    emails_needing_attention: tuple[Email, ...]
    can_undo_rejection: bool
    reasons: tuple[CatalogItem, ...]  # active ones, for the reject form


class ViewDropOff:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def __call__(self, id: DropOffId) -> DropOffView:
        """`NotFound` when no drop-off has this ID."""
        drop_off = self._records.drop_off(id)
        if drop_off is None:
            raise NotFound(id)
        studio = self._studio()
        now = self._clock.now()
        load = None if drop_off.load_id is None else self._records.load(drop_off.load_id)
        emails = tuple(self._records.emails_for(id))
        return DropOffView(
            drop_off=drop_off,
            firing_type=item_name(studio, CatalogList.FIRING_TYPES, drop_off.firing_type),
            glaze_type=(
                None
                if drop_off.glaze_type is None
                else item_name(studio, CatalogList.GLAZE_TYPES, drop_off.glaze_type)
            ),
            rejection_reason=(
                None
                if drop_off.rejection is None
                else item_name(studio, CatalogList.REASONS, drop_off.rejection.reason)
            ),
            load=load,
            emails=emails,
            emails_needing_attention=tuple(
                email for email in emails if needs_attention(email, now) and not is_history(drop_off, email)
            ),
            can_undo_rejection=_can_undo(drop_off, now),
            reasons=active_items(studio.reasons),
        )


def _can_undo(drop_off: DropOff, now: datetime) -> bool:
    """`undo_rejection`'s own rule (rejected, the same Austin day), asked of the domain so
    it stays in one place."""
    try:
        undo_rejection(drop_off, now)
    except NotRejected, UndoTooLate:
        return False
    return True
