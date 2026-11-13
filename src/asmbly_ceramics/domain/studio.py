"""The studio's settings and lists: data staff manage, not code."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from asmbly_ceramics.domain.errors import (
    DuplicateItem,
    InvalidSetting,
    ItemInUse,
    ItemRetired,
    SendingAddressOutsideAsmbly,
    UnknownItem,
)
from asmbly_ceramics.domain.ids import ItemId, new_item_id
from asmbly_ceramics.domain.limits import (
    HOURS_TEXT_MAX,
    ITEM_NAME_MAX,
    PICKUP_WINDOW_MAX,
    PICKUP_WINDOW_MIN,
    SENDING_DOMAIN,
)
from asmbly_ceramics.domain.text import is_valid_email


class CatalogList(StrEnum):
    KILNS = "kilns"
    FIRING_TYPES = "firing_types"
    GLAZE_TYPES = "glaze_types"
    REASONS = "reasons"


class ItemStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class CatalogItem:
    id: ItemId
    name: str
    status: ItemStatus = ItemStatus.ACTIVE
    needs_glaze_type: bool = False  # firing types only
    needs_message: bool = False  # reasons only


@dataclass(frozen=True, slots=True)
class Studio:
    sending_address: str
    pickup_window_days: int
    pickup_hours_text: str
    kilns: tuple[CatalogItem, ...]
    firing_types: tuple[CatalogItem, ...]
    glaze_types: tuple[CatalogItem, ...]
    reasons: tuple[CatalogItem, ...]
    version: int = 0

    def items(self, which: CatalogList) -> tuple[CatalogItem, ...]:
        return getattr(self, which.value)  # type: ignore[no-any-return]

    def item(self, which: CatalogList, id: ItemId) -> CatalogItem:
        for item in self.items(which):
            if item.id == id:
                return item
        raise UnknownItem(f"That {_SINGULAR[which]} doesn't exist.")

    def active_item(self, which: CatalogList, id: ItemId) -> CatalogItem:
        item = self.item(which, id)
        if item.status is ItemStatus.RETIRED:
            raise ItemRetired(f"{item.name} is retired and can't be picked.")
        return item


@dataclass(frozen=True, slots=True)
class SettingChange:
    at: datetime
    by: str  # staff username, or "system" for the starting values
    what: str  # "Pickup window: 10 → 14 days", "Added kiln Helios", "Changed the pickup hours text"


_SINGULAR = {
    CatalogList.KILNS: "kiln",
    CatalogList.FIRING_TYPES: "firing type",
    CatalogList.GLAZE_TYPES: "glaze type",
    CatalogList.REASONS: "rejection reason",
}

STARTING_HOURS_TEXT = (
    "Members can pick up during Asmbly's open hours, 7 days a week, 5am to 2am. "
    "Class students can pick up during the Steward on Duty shifts, listed on the events "
    "calendar on asmbly.org."
)


def check_sending_address(address: str) -> str:
    cleaned = address.strip()
    local, _, domain = cleaned.rpartition("@")
    if not is_valid_email(cleaned) or domain.casefold() != SENDING_DOMAIN:
        raise SendingAddressOutsideAsmbly(f"Use an address at {SENDING_DOMAIN}.")
    return f"{local}@{SENDING_DOMAIN}"


def starting_studio(sending_address: str, at: datetime) -> tuple[Studio, SettingChange]:
    def item(
        id: str, name: str, *, needs_glaze_type: bool = False, needs_message: bool = False
    ) -> CatalogItem:
        return CatalogItem(ItemId(id), name, needs_glaze_type=needs_glaze_type, needs_message=needs_message)

    studio = Studio(
        sending_address=check_sending_address(sending_address),
        pickup_window_days=14,
        pickup_hours_text=STARTING_HOURS_TEXT,
        kilns=(item("athena", "Athena"), item("helios", "Helios"), item("vulcan", "Vulcan")),
        firing_types=(item("bisque", "Bisque"), item("glaze", "Glaze", needs_glaze_type=True)),
        glaze_types=(
            item("house-dip-glaze", "House dip glaze"),
            item("commercial-glaze", "Commercial glaze"),
        ),
        reasons=(
            item("has-glaze-issues", "Has glaze issues"),
            item("needs-more-time-to-dry", "Needs more time to dry"),
            item("other", "Other", needs_message=True),
        ),
    )
    return studio, SettingChange(at, "system", "Starting settings")


def change_email_settings(
    studio: Studio,
    *,
    sending_address: str,
    pickup_window_days: str,
    pickup_hours_text: str,
    by: str,
    at: datetime,
) -> tuple[Studio, list[SettingChange]]:
    address = check_sending_address(sending_address)
    days_text = pickup_window_days.strip()
    window_error = InvalidSetting(
        "pickup_window_days", f"Enter a number of days from {PICKUP_WINDOW_MIN} to {PICKUP_WINDOW_MAX}."
    )
    if not (days_text.isascii() and days_text.isdigit()):
        raise window_error
    days = int(days_text)
    if not PICKUP_WINDOW_MIN <= days <= PICKUP_WINDOW_MAX:
        raise window_error
    hours = pickup_hours_text.strip()
    if not 1 <= len(hours) <= HOURS_TEXT_MAX:
        raise InvalidSetting("pickup_hours_text", f"Write 1 to {HOURS_TEXT_MAX} characters of pickup hours.")

    changes: list[SettingChange] = []
    if address != studio.sending_address:
        changes.append(SettingChange(at, by, f"Sending address: {studio.sending_address} → {address}"))
    if days != studio.pickup_window_days:
        changes.append(SettingChange(at, by, f"Pickup window: {studio.pickup_window_days} → {days} days"))
    if hours != studio.pickup_hours_text:
        changes.append(SettingChange(at, by, "Changed the pickup hours text"))
    if not changes:
        return studio, []
    return (
        replace(studio, sending_address=address, pickup_window_days=days, pickup_hours_text=hours),
        changes,
    )


def _with_items(studio: Studio, which: CatalogList, items: tuple[CatalogItem, ...]) -> Studio:
    match which:
        case CatalogList.KILNS:
            return replace(studio, kilns=items)
        case CatalogList.FIRING_TYPES:
            return replace(studio, firing_types=items)
        case CatalogList.GLAZE_TYPES:
            return replace(studio, glaze_types=items)
        case CatalogList.REASONS:
            return replace(studio, reasons=items)


def add_item(
    studio: Studio,
    which: CatalogList,
    name: str,
    by: str,
    at: datetime,
    *,
    needs_glaze_type: bool = False,
    needs_message: bool = False,
) -> tuple[Studio, SettingChange]:
    cleaned = name.strip()
    if not 1 <= len(cleaned) <= ITEM_NAME_MAX:
        raise InvalidSetting("name", f"Enter a name of 1 to {ITEM_NAME_MAX} characters.")
    existing = studio.items(which)
    if any(i.name.casefold() == cleaned.casefold() for i in existing):
        raise DuplicateItem(f"There is already a {_SINGULAR[which]} called {cleaned}.")
    item = CatalogItem(
        new_item_id(cleaned, {i.id for i in existing}),
        cleaned,
        needs_glaze_type=needs_glaze_type and which is CatalogList.FIRING_TYPES,
        needs_message=needs_message and which is CatalogList.REASONS,
    )
    return (
        _with_items(studio, which, (*existing, item)),
        SettingChange(at, by, f"Added {_SINGULAR[which]} {cleaned}"),
    )


def _replace_item(studio: Studio, which: CatalogList, new: CatalogItem) -> Studio:
    return _with_items(studio, which, tuple(new if i.id == new.id else i for i in studio.items(which)))


def retire_item(
    studio: Studio, which: CatalogList, id: ItemId, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    item = studio.item(which, id)
    if item.status is ItemStatus.RETIRED:
        return studio, SettingChange(at, by, f"Retired {_SINGULAR[which]} {item.name}")
    active = [i for i in studio.items(which) if i.status is ItemStatus.ACTIVE]
    if which is not CatalogList.GLAZE_TYPES and len(active) <= 1:
        raise InvalidSetting(
            "status", f"{item.name} is the last active {_SINGULAR[which]}: add another first."
        )
    return (
        _replace_item(studio, which, replace(item, status=ItemStatus.RETIRED)),
        SettingChange(at, by, f"Retired {_SINGULAR[which]} {item.name}"),
    )


def restore_item(
    studio: Studio, which: CatalogList, id: ItemId, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    item = studio.item(which, id)
    return (
        _replace_item(studio, which, replace(item, status=ItemStatus.ACTIVE)),
        SettingChange(at, by, f"Restored {_SINGULAR[which]} {item.name}"),
    )


def delete_item(
    studio: Studio, which: CatalogList, id: ItemId, *, used: bool, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    item = studio.item(which, id)
    if used:
        raise ItemInUse(f"{item.name} is used: retire it instead.")
    remaining = tuple(i for i in studio.items(which) if i.id != id)
    if (
        which is not CatalogList.GLAZE_TYPES
        and item.status is ItemStatus.ACTIVE
        and not any(i.status is ItemStatus.ACTIVE for i in remaining)
    ):
        raise InvalidSetting(
            "status", f"{item.name} is the last active {_SINGULAR[which]}: add another first."
        )
    return (
        _with_items(studio, which, remaining),
        SettingChange(at, by, f"Deleted {_SINGULAR[which]} {item.name}"),
    )
