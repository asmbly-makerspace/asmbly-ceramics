"""The studio's settings and lists, their history, and the test email (#6).

Each change reads the studio, applies the domain's function, checks the version the page
showed, and commits the new studio with one `SettingChange` per change, recording the
staff username and the time. Logs carry the username and item IDs, never an address, the
hours text or an item's name.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType

from asmbly_ceramics.domain.errors import NoStaffEmail, TestEmailFailed
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.studio import (
    CatalogList,
    ItemStatus,
    SettingChange,
    Studio,
    add_item,
    change_email_settings,
    check_sending_address,
    delete_item,
    restore_item,
    retire_item,
)
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.composer import Composer, outgoing
from asmbly_ceramics.ports.mailer import Mailer, SendFailed
from asmbly_ceramics.ports.records import Change, Conflict, Put, Records, Update
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.use_cases.studio import CurrentStudio

HISTORY_PAGE = 20
BAD_RECIPIENT = "bad_recipient"  # the signed-in staff member's address isn't an address


@dataclass(frozen=True, slots=True)
class StudioView:
    studio: Studio
    history: tuple[SettingChange, ...]  # newest first
    used: Mapping[tuple[CatalogList, ItemId], bool]  # a used item can only be retired
    older: str | None  # the next page's cursor (`HistoryPage.older`); None at the end


class ViewStudio:
    def __init__(self, records: Records, studio: CurrentStudio) -> None:
        self._records = records
        self._studio = studio

    def __call__(self, before: str | None = None, limit: int = HISTORY_PAGE) -> StudioView:
        """The settings, which items are used, and a page of history. `BadCursor` for a
        `before` no page gave (the page shows the first page instead)."""
        studio = self._studio()
        page = self._records.history(limit, before)
        used = {
            (which, item.id): self._records.is_item_used(which, item.id)
            for which in CatalogList
            for item in studio.items(which)
        }
        return StudioView(studio, page.changes, MappingProxyType(used), page.older)


def _save(
    records: Records,
    current: Studio,
    version: int,
    new: Studio,
    changes: list[SettingChange],
    staff: StaffMember,
    item: tuple[CatalogList, ItemId] | None = None,
) -> Studio:
    """Commits the new studio and its history, or nothing when nothing changed. `Conflict`
    when the studio isn't at the version the page showed."""
    if current.version != version:
        raise Conflict()
    if not changes:
        return current
    commit: list[Change] = [Update(new), *(Put(change) for change in changes)]
    records.commit(commit)
    if item is None:
        log_event("settings_changed", user=staff.username)
    else:
        log_event("settings_changed", user=staff.username, list=item[0].value, item=str(item[1]))
    return replace(new, version=new.version + 1)


class _StudioChange:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def _now(self) -> datetime:
        return self._clock.now()


class ChangeEmailSettings(_StudioChange):
    def __call__(
        self,
        *,
        sending_address: str,
        pickup_window_days: str,
        pickup_hours_text: str,
        version: int,
        staff: StaffMember,
    ) -> Studio:
        """`SendingAddressOutsideAsmbly`, `InvalidSetting`, `Conflict`. Saving the same
        values commits and logs nothing."""
        current = self._studio()
        new, changes = change_email_settings(
            current,
            sending_address=sending_address,
            pickup_window_days=pickup_window_days,
            pickup_hours_text=pickup_hours_text,
            by=staff.username,
            at=self._now(),
        )
        return _save(self._records, current, version, new, changes, staff)


class AddCatalogItem(_StudioChange):
    def __call__(
        self,
        which: CatalogList,
        name: str,
        *,
        needs_glaze_type: bool,
        needs_message: bool,
        version: int,
        staff: StaffMember,
    ) -> Studio:
        """`InvalidSetting`, `DuplicateItem`, `Conflict`."""
        current = self._studio()
        new, change = add_item(
            current,
            which,
            name,
            staff.username,
            self._now(),
            needs_glaze_type=needs_glaze_type,
            needs_message=needs_message,
        )
        added = new.items(which)[-1]
        return _save(self._records, current, version, new, [change], staff, (which, added.id))


class RetireCatalogItem(_StudioChange):
    def __call__(self, which: CatalogList, id: ItemId, version: int, staff: StaffMember) -> Studio:
        """`UnknownItem`, `InvalidSetting` (already retired, or the last active one), `Conflict`."""
        current = self._studio()
        new, change = retire_item(current, which, id, staff.username, self._now())
        return _save(self._records, current, version, new, [change], staff, (which, id))


class RestoreCatalogItem(_StudioChange):
    def __call__(self, which: CatalogList, id: ItemId, version: int, staff: StaffMember) -> Studio:
        """`UnknownItem`, `InvalidSetting` (already active), `Conflict`."""
        current = self._studio()
        new, change = restore_item(current, which, id, staff.username, self._now())
        return _save(self._records, current, version, new, [change], staff, (which, id))


class DeleteCatalogItem(_StudioChange):
    def __call__(self, which: CatalogList, id: ItemId, version: int, staff: StaffMember) -> Studio:
        """Only a retired item nothing uses (#6). `UnknownItem`, `InvalidSetting` (still
        active: retire it first), `ItemInUse`, `Conflict`."""
        current = self._studio()
        item = current.item(which, id)
        # Use is asked only of a retired item: retiring stops new use. A request that read
        # the studio before the retire and commits after the delete can still name it
        # (no commit checks the studio's version): an accepted, narrow race, noted in
        # the phase 3 document.
        used = item.status is ItemStatus.RETIRED and self._records.is_item_used(which, id)
        new, change = delete_item(current, which, id, used=used, by=staff.username, at=self._now())
        return _save(self._records, current, version, new, [change], staff, (which, id))


class SendTestEmail:
    def __init__(self, mailer: Mailer, studio: CurrentStudio, composer: Composer) -> None:
        self._mailer = mailer
        self._studio = studio
        self._composer = composer

    def __call__(self, *, sending_address: str, staff: StaffMember) -> None:
        """Sends the test email now, from the new (unsaved) address, to the signed-in staff
        member's own address from their verified token, and to no one else. Saves and
        queues nothing. `SendingAddressOutsideAsmbly`, `NoStaffEmail`, `TestEmailFailed`."""
        address = check_sending_address(sending_address)
        if staff.email is None:
            raise NoStaffEmail()
        composed = self._composer.test(replace(self._studio(), sending_address=address))
        try:
            message = outgoing(composed, to=staff.email, sending_address=address, photos=())
        except ValueError:
            self._failed(staff, BAD_RECIPIENT)
            raise TestEmailFailed(BAD_RECIPIENT) from None
        try:
            self._mailer.send(message)
        except SendFailed as failed:
            self._failed(staff, failed.code)
            raise TestEmailFailed(failed.code) from None
        log_event("test_email", user=staff.username, outcome="sent")

    def _failed(self, staff: StaffMember, code: str) -> None:
        log_event("test_email", level=logging.WARNING, user=staff.username, outcome="failed", error_code=code)
