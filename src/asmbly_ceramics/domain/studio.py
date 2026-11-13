"""The studio's settings and lists (story #6): data staff manage, not code.

Every change returns the new `Studio` and the `SettingChange` the history records, with
the staff username and the time. The caller stores both in one commit.
"""

import re
import unicodedata
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
    EMAIL_MAX,
    HOURS_TEXT_MAX,
    ITEM_NAME_MAX,
    PICKUP_WINDOW_MAX,
    PICKUP_WINDOW_MIN,
    SENDING_DOMAIN,
)

SYSTEM = "system"
_DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", flags=re.ASCII)
_WHOLE_NUMBER = re.compile(r"[0-9]+", flags=re.ASCII)
# RFC 5322's dot-atom in ASCII (SES takes addresses in 7-bit ASCII only): no spaces, no
# quotes, commas, brackets or angle brackets, no leading, trailing or doubled dot.
_ATEXT = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
_LOCAL_PART = re.compile(rf"{_ATEXT}(?:\.{_ATEXT})*", flags=re.ASCII)
_LOCAL_PART_MAX = 64  # RFC 5321 section 4.5.3.1.1
_DOMAIN_LABEL_MAX = 63  # RFC 1035 section 2.3.4
_HOURS_ALLOWED_CONTROLS = frozenset("\n\t")


class CatalogList(StrEnum):
    KILNS = "kilns"
    FIRING_TYPES = "firing_types"
    GLAZE_TYPES = "glaze_types"
    REASONS = "reasons"


_KIND = {
    CatalogList.KILNS: "kiln",
    CatalogList.FIRING_TYPES: "firing type",
    CatalogList.GLAZE_TYPES: "glaze type",
    CatalogList.REASONS: "reason",
}


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
        match which:
            case CatalogList.KILNS:
                return self.kilns
            case CatalogList.FIRING_TYPES:
                return self.firing_types
            case CatalogList.GLAZE_TYPES:
                return self.glaze_types
            case CatalogList.REASONS:
                return self.reasons

    def item(self, which: CatalogList, id: ItemId) -> CatalogItem:
        for item in self.items(which):
            if item.id == id:
                return item
        raise UnknownItem(_KIND[which])

    def active_item(self, which: CatalogList, id: ItemId) -> CatalogItem:
        item = self.item(which, id)
        if item.status is not ItemStatus.ACTIVE:
            raise ItemRetired(item.name)
        return item


@dataclass(frozen=True, slots=True)
class SettingChange:
    at: datetime
    by: str  # staff username, or "system" for the starting values
    what: str  # "Pickup window: 10 → 14 days", "Added kiln Helios", "Changed the pickup hours text"


def is_valid_email(address: str) -> bool:
    """A plausible address: one `@`, an ASCII dot-atom local part of at most 64 characters, a
    dotted domain of labels of at most 63. No DNS lookup."""
    if len(address) > EMAIL_MAX or address.count("@") != 1:
        return False
    local, domain = address.split("@")
    if len(local) > _LOCAL_PART_MAX or not _LOCAL_PART.fullmatch(local):
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and all(
        len(label) <= _DOMAIN_LABEL_MAX and _DOMAIN_LABEL.fullmatch(label) for label in labels
    )


def check_sending_address(address: str) -> str:
    """The address, stripped and with its domain lowercased, if it is exactly at `asmbly.org`."""
    address = address.strip()
    if not is_valid_email(address):
        raise SendingAddressOutsideAsmbly(SENDING_DOMAIN)
    local, domain = address.split("@")
    if domain.lower() != SENDING_DOMAIN:
        raise SendingAddressOutsideAsmbly(SENDING_DOMAIN)
    return f"{local}@{SENDING_DOMAIN}"


_STARTING_PICKUP_HOURS = (
    "Members: during Asmbly's open hours, 7 days a week, 5am to 2am.\n"
    "Class students: during the Steward on Duty (SOD) shifts, listed on the events "
    "calendar at https://asmbly.org/events/."
)


def starting_studio(sending_address: str, at: datetime) -> tuple[Studio, SettingChange]:
    """The settings epic #1 decided, with the sending address composition passes in."""
    _check_change(SYSTEM, at)
    studio = Studio(
        sending_address=check_sending_address(sending_address),
        pickup_window_days=14,
        pickup_hours_text=_STARTING_PICKUP_HOURS,
        kilns=_catalog("Athena", "Helios", "Vulcan"),
        firing_types=(
            CatalogItem(ItemId("bisque"), "Bisque"),
            CatalogItem(ItemId("glaze"), "Glaze", needs_glaze_type=True),
        ),
        glaze_types=_catalog("House dip glaze", "Commercial glaze"),
        reasons=(
            *_catalog("Has glaze issues", "Needs more time to dry"),
            CatalogItem(ItemId("other"), "Other", needs_message=True),
        ),
    )
    return studio, SettingChange(at, SYSTEM, "Starting settings")


def change_email_settings(
    studio: Studio,
    *,
    sending_address: str,
    pickup_window_days: str,
    pickup_hours_text: str,
    by: str,
    at: datetime,
) -> tuple[Studio, list[SettingChange]]:
    """Check all three values, then record one change per value that changed."""
    _check_change(by, at)
    address = check_sending_address(sending_address)
    window = _pickup_window(pickup_window_days)
    # A browser's textarea posts CRLF; the stored text holds LF only.
    hours = pickup_hours_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not hours:
        raise InvalidSetting("pickup_hours_text", "Enter the pickup hours.")
    if any(unicodedata.category(c) == "Cc" and c not in _HOURS_ALLOWED_CONTROLS for c in hours):
        raise InvalidSetting("pickup_hours_text", "Enter the pickup hours as plain text.")
    if len(hours) > HOURS_TEXT_MAX:
        raise InvalidSetting(
            "pickup_hours_text", f"The pickup hours are longer than {HOURS_TEXT_MAX:,} characters."
        )

    changes: list[SettingChange] = []
    if address != studio.sending_address:
        changes.append(SettingChange(at, by, f"Sending address: {studio.sending_address} → {address}"))
    if window != studio.pickup_window_days:
        changes.append(SettingChange(at, by, f"Pickup window: {studio.pickup_window_days} → {window} days"))
    if hours != studio.pickup_hours_text:
        changes.append(SettingChange(at, by, "Changed the pickup hours text"))
    if not changes:
        return studio, []
    return replace(
        studio, sending_address=address, pickup_window_days=window, pickup_hours_text=hours
    ), changes


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
    _check_change(by, at)
    if needs_glaze_type and which is not CatalogList.FIRING_TYPES:
        raise ValueError("only a firing type can need a glaze type")
    if needs_message and which is not CatalogList.REASONS:
        raise ValueError("only a reason can need a message")
    name = unicodedata.normalize("NFC", name.strip())
    if not name:
        raise InvalidSetting("name", "Enter a name.")
    if len(name) > ITEM_NAME_MAX or not name.isprintable():
        raise InvalidSetting("name", f"Enter a name of at most {ITEM_NAME_MAX} characters, on one line.")
    items = studio.items(which)
    if any(item.name.casefold() == name.casefold() for item in items):
        raise DuplicateItem(_KIND[which], name)
    item = CatalogItem(
        new_item_id(name, [item.id for item in items]),
        name,
        needs_glaze_type=needs_glaze_type,
        needs_message=needs_message,
    )
    return _with_items(studio, which, (*items, item)), SettingChange(at, by, f"Added {_KIND[which]} {name}")


def retire_item(
    studio: Studio, which: CatalogList, id: ItemId, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    _check_change(by, at)
    item = studio.item(which, id)
    if item.status is ItemStatus.RETIRED:
        raise InvalidSetting("status", f"{item.name} is already retired.")
    _refuse_last_active(studio, which, item)
    studio = _replace_item(studio, which, replace(item, status=ItemStatus.RETIRED))
    return studio, SettingChange(at, by, f"Retired {_KIND[which]} {item.name}")


def restore_item(
    studio: Studio, which: CatalogList, id: ItemId, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    _check_change(by, at)
    item = studio.item(which, id)
    if item.status is ItemStatus.ACTIVE:
        raise InvalidSetting("status", f"{item.name} is already active.")
    studio = _replace_item(studio, which, replace(item, status=ItemStatus.ACTIVE))
    return studio, SettingChange(at, by, f"Restored {_KIND[which]} {item.name}")


def delete_item(
    studio: Studio, which: CatalogList, id: ItemId, *, used: bool, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    """`used` comes from `Records.is_item_used`: an item any drop-off or load names is retired instead."""
    _check_change(by, at)
    item = studio.item(which, id)
    if used:
        raise ItemInUse(item.name)
    if item.status is ItemStatus.ACTIVE:
        _refuse_last_active(studio, which, item)
    items = tuple(other for other in studio.items(which) if other.id != id)
    return _with_items(studio, which, items), SettingChange(at, by, f"Deleted {_KIND[which]} {item.name}")


def _catalog(*names: str) -> tuple[CatalogItem, ...]:
    items: list[CatalogItem] = []
    for name in names:
        items.append(CatalogItem(new_item_id(name, [item.id for item in items]), name))
    return tuple(items)


def _check_change(by: str, at: datetime) -> None:
    if not by:
        raise ValueError("a setting change needs the staff username")
    if at.utcoffset() is None:
        raise ValueError("a setting change needs an aware time")


def _pickup_window(text: str) -> int:
    text = text.strip()
    # The length check comes first: int() refuses a string of over 4,300 digits with a ValueError.
    if len(text) <= len(str(PICKUP_WINDOW_MAX)) + 1 and _WHOLE_NUMBER.fullmatch(text):
        days = int(text)
        if PICKUP_WINDOW_MIN <= days <= PICKUP_WINDOW_MAX:
            return days
    raise InvalidSetting(
        "pickup_window_days", f"Enter a number of days from {PICKUP_WINDOW_MIN} to {PICKUP_WINDOW_MAX}."
    )


def _refuse_last_active(studio: Studio, which: CatalogList, item: CatalogItem) -> None:
    others = [
        other for other in studio.items(which) if other.id != item.id and other.status is ItemStatus.ACTIVE
    ]
    if not others:
        raise InvalidSetting(
            "status", f"{item.name} is the last active {_KIND[which]}: add or restore another first."
        )


def _replace_item(studio: Studio, which: CatalogList, new: CatalogItem) -> Studio:
    return _with_items(
        studio, which, tuple(new if item.id == new.id else item for item in studio.items(which))
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
