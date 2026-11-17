"""The studio's settings and lists (story #6): data staff manage, not code.

Every change returns the new `Studio` and the `SettingChange` the history records, with
the staff username and the time. The caller stores both in one commit.
"""

import re
import unicodedata
from collections.abc import Mapping
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
from asmbly_ceramics.domain.firing import Program, Speed, read_program
from asmbly_ceramics.domain.ids import ItemId, new_item_id
from asmbly_ceramics.domain.limits import (
    EMAIL_MAX,
    FIRING_NUMBER_MAX,
    HOURS_TEXT_MAX,
    ITEM_NAME_MAX,
    PICKUP_WINDOW_MAX,
    PICKUP_WINDOW_MIN,
    RECEIVED_EMAILS_PER_DAY_MAX,
    RECEIVED_EMAILS_PER_DAY_MIN,
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
    CONES = "cones"
    CLAY_BODIES = "clay_bodies"


_KIND = {
    CatalogList.KILNS: "kiln",
    CatalogList.FIRING_TYPES: "firing type",
    CatalogList.GLAZE_TYPES: "glaze type",
    CatalogList.REASONS: "reason",
    CatalogList.CONES: "cone",
    CatalogList.CLAY_BODIES: "clay body",
}
_KINDS = {CatalogList.CLAY_BODIES: "clay bodies"}


def kind_name(which: CatalogList) -> str:
    """What one item of the list is called in a message: "glaze type", "clay body"."""
    return _KIND[which]


def kinds_name(which: CatalogList) -> str:
    """The plural: "glaze types", "clay bodies"."""
    return _KINDS.get(which, f"{_KIND[which]}s")


class ItemStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class KilnCounts:
    """A kiln's firing counts as staff typed them (#42), as of a time: the firings since its
    last new elements and all time. `suggest_numbers` counts on from them."""

    since_elements: int
    all_time: int
    as_of: datetime  # aware


@dataclass(frozen=True, slots=True)
class CatalogItem:
    id: ItemId
    name: str
    status: ItemStatus = ItemStatus.ACTIVE
    needs_glaze_type: bool = False  # firing types only
    needs_message: bool = False  # reasons only
    default_program: Program | None = None  # firing types only: fills a new load's record
    counts: KilnCounts | None = None  # kilns only

    @property
    def retired(self) -> bool:
        return self.status is ItemStatus.RETIRED


def _catalog(*names: str) -> tuple[CatalogItem, ...]:
    items: list[CatalogItem] = []
    for name in names:
        items.append(CatalogItem(new_item_id(name, [item.id for item in items]), name))
    return tuple(items)


# The lists #42 and #17 add, as the studio's workbook has them. A studio stored before
# them reads with these.
STARTING_CONES = _catalog("^06", "^5", "^6")
STARTING_CLAY_BODIES = _catalog("Buffalo Wallow", "Cinco Blanco", "Cone 5 Porcelain")
STARTING_RECEIVED_EMAILS_PER_DAY = 300  # decision 0008


@dataclass(frozen=True, slots=True)
class Studio:
    sending_address: str
    pickup_window_days: int
    pickup_hours_text: str
    kilns: tuple[CatalogItem, ...]
    firing_types: tuple[CatalogItem, ...]
    glaze_types: tuple[CatalogItem, ...]
    reasons: tuple[CatalogItem, ...]
    cones: tuple[CatalogItem, ...] = STARTING_CONES
    clay_bodies: tuple[CatalogItem, ...] = STARTING_CLAY_BODIES
    received_emails_per_day: int = STARTING_RECEIVED_EMAILS_PER_DAY
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
            case CatalogList.CONES:
                return self.cones
            case CatalogList.CLAY_BODIES:
                return self.clay_bodies

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
    # "Pickup window: 10 → 14 days", "Added kiln Helios", "Changed the sending address":
    # never an address or the hours text, since the history is kept for good.
    what: str


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
            CatalogItem(ItemId("bisque"), "Bisque", default_program=_program_for("^06", 8, Speed.SLOW, 0)),
            CatalogItem(
                ItemId("glaze"),
                "Glaze",
                needs_glaze_type=True,
                default_program=_program_for("^6", 0, Speed.MEDIUM, 7),
            ),
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
    received_emails_per_day: str,
    by: str,
    at: datetime,
) -> tuple[Studio, list[SettingChange]]:
    """Check all four values, then record one change per value that changed."""
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
    cap = _received_emails_per_day(received_emails_per_day)

    changes: list[SettingChange] = []
    if address != studio.sending_address:
        # No address in the history: it is kept for good, and an address is personal data.
        changes.append(SettingChange(at, by, "Changed the sending address"))
    if window != studio.pickup_window_days:
        changes.append(SettingChange(at, by, f"Pickup window: {studio.pickup_window_days} → {window} days"))
    if hours != studio.pickup_hours_text:
        changes.append(SettingChange(at, by, "Changed the pickup hours text"))
    if cap != studio.received_emails_per_day:
        changes.append(
            SettingChange(at, by, f"Received emails a day, at most: {studio.received_emails_per_day} → {cap}")
        )
    if not changes:
        return studio, []
    return replace(
        studio,
        sending_address=address,
        pickup_window_days=window,
        pickup_hours_text=hours,
        received_emails_per_day=cap,
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
    """Delete a retired item no drop-off, load or default program names (#6).

    Only a retired item can be deleted. A cone a firing type's default program names
    (`names_cone`) is in use whatever `used` says: the studio itself is checked here.

    Retiring is what stops new use: a submit or a new load checks the studio's item is
    active, so once the retire is committed nothing new can name the item, and `used`
    (from `Records.is_item_used`, read after the retire) can't be made stale by a commit
    that names it. An active item would race: the delete could read `used` as false
    while a drop-off or load naming it is committed. An item anything names is kept
    retired.
    """
    _check_change(by, at)
    item = studio.item(which, id)
    if not item.retired:
        raise InvalidSetting("status", f"Retire {item.name} before deleting it.")
    if used or (which is CatalogList.CONES and names_cone(studio, id)):
        raise ItemInUse(item.name)
    items = tuple(other for other in studio.items(which) if other.id != id)
    return _with_items(studio, which, items), SettingChange(at, by, f"Deleted {_KIND[which]} {item.name}")


def set_default_program(
    studio: Studio, firing_type: ItemId, values: Mapping[str, str], by: str, at: datetime
) -> tuple[Studio, SettingChange | None]:
    """The firing type's default program from the page's preheat_hours, cone, speed and
    hold_minutes (`firing.read_program`), which fills each new load's record (#42).

    The cone is one of the studio's active cones, or the cone the program already names
    (so a program whose cone was retired can still have its hold changed). All four blank
    clears it. `UnknownItem`; `InvalidRecord` for a refused field. A retired firing type
    can still be changed. No change (None) when the program is the same.
    """
    _check_change(by, at)
    item = studio.item(CatalogList.FIRING_TYPES, firing_type)
    named = None if item.default_program is None else item.default_program.cone
    program: Program | None = read_program(values, nameable_cone_ids(studio, named))
    if program == Program():
        program = None
    if program == item.default_program:
        return studio, None
    studio = _replace_item(studio, CatalogList.FIRING_TYPES, replace(item, default_program=program))
    if program is None:
        return studio, SettingChange(at, by, f"Cleared the default program for {item.name}")
    shown = describe_program(studio, program)
    return studio, SettingChange(at, by, f"Default program for {item.name}: {shown}")


def nameable_cones(studio: Studio, named: ItemId | None) -> tuple[CatalogItem, ...]:
    """The cones a program (a firing type's default or a load's record) may name, in the
    studio's order: the active ones, and `named`, the one it already names, retired or
    not, so a program whose cone was retired can still have its other fields changed.
    The one rule `set_default_program`, the firing record and their forms all follow."""
    return tuple(cone for cone in studio.cones if not cone.retired or cone.id == named)


def nameable_cone_ids(studio: Studio, named: ItemId | None) -> frozenset[ItemId]:
    """The IDs of `nameable_cones`, as `firing.read_program` takes them, with `named` even
    when the studio no longer lists it (a cone deleted after a load's record named it)."""
    ids = {cone.id for cone in nameable_cones(studio, named)}
    if named is not None:
        ids.add(named)
    return frozenset(ids)


def describe_program(studio: Studio, program: Program) -> str:
    """ "^6, medium, preheat 0 h, hold 7 min": the parts that are set, in that order."""
    parts: list[str] = []
    if program.cone is not None:
        parts.append(_cone_name(studio, program.cone))
    if program.speed is not None:
        parts.append(program.speed.value)
    if program.preheat_hours is not None:
        parts.append(f"preheat {program.preheat_hours} h")
    if program.hold_minutes is not None:
        parts.append(f"hold {program.hold_minutes} min")
    return ", ".join(parts)


def set_kiln_counts(
    studio: Studio, kiln: ItemId, since_elements: str, all_time: str, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    """The kiln's firing counts as staff typed them, as of `at` (#42): whole numbers from
    0 to `FIRING_NUMBER_MAX`, the count since elements no more than the all-time count,
    else `InvalidSetting(field, message)`. `UnknownItem`. A retired kiln can still be
    changed."""
    _check_change(by, at)
    item = studio.item(CatalogList.KILNS, kiln)
    since = _count("since_elements", since_elements)
    total = _count("all_time", all_time)
    if since > total:
        raise InvalidSetting(
            "since_elements", "The firings since new elements can't be more than the firings all time."
        )
    studio = _replace_item(studio, CatalogList.KILNS, replace(item, counts=KilnCounts(since, total, at)))
    return studio, SettingChange(at, by, f"{item.name} counts: {since:,} since elements, {total:,} all time")


def record_new_elements(
    studio: Studio, kiln: ItemId, all_time_so_far: int, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    """New elements in the kiln (#42): its counts become 0 since elements and
    `all_time_so_far` all time, as of `at`, so the next firing's number is 1.
    `UnknownItem`. A retired kiln can still be changed."""
    _check_change(by, at)
    if not 0 <= all_time_so_far <= FIRING_NUMBER_MAX:
        raise ValueError("the all-time count is a whole number from 0 to FIRING_NUMBER_MAX")
    item = studio.item(CatalogList.KILNS, kiln)
    counts = KilnCounts(since_elements=0, all_time=all_time_so_far, as_of=at)
    studio = _replace_item(studio, CatalogList.KILNS, replace(item, counts=counts))
    return studio, SettingChange(at, by, f"New elements in {item.name}")


def names_cone(studio: Studio, cone: ItemId) -> bool:
    """A firing type's default program names `cone`, so it counts as used (`is_item_used`)."""
    return any(
        item.default_program is not None and item.default_program.cone == cone for item in studio.firing_types
    )


def can_delete_item(item: CatalogItem, *, used: bool) -> bool:
    """`delete_item` accepts `item`: it is retired and nothing names it."""
    return item.retired and not used


def _program_for(cone: str, preheat_hours: int, speed: Speed, hold_minutes: int) -> Program:
    """A starting default program, its cone named as in `STARTING_CONES`."""
    (cone_id,) = (item.id for item in STARTING_CONES if item.name == cone)
    return Program(preheat_hours=preheat_hours, cone=cone_id, speed=speed, hold_minutes=hold_minutes)


def _cone_name(studio: Studio, cone: ItemId) -> str:
    for item in studio.cones:
        if item.id == cone:
            return item.name
    return str(cone)  # a deleted cone: never, while a program names it (`is_item_used`)


def _count(field: str, text: str) -> int:
    text = text.strip()
    # The length check comes first: int() refuses a string of over 4,300 digits with a ValueError.
    if len(text) <= len(str(FIRING_NUMBER_MAX)) and _WHOLE_NUMBER.fullmatch(text):
        number = int(text)
        if number <= FIRING_NUMBER_MAX:
            return number
    raise InvalidSetting(field, f"Enter a whole number from 0 to {FIRING_NUMBER_MAX:,}.")


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


def _received_emails_per_day(text: str) -> int:
    text = text.strip()
    # The length check comes first, as for the pickup window.
    if len(text) <= len(str(RECEIVED_EMAILS_PER_DAY_MAX)) + 1 and _WHOLE_NUMBER.fullmatch(text):
        cap = int(text)
        if RECEIVED_EMAILS_PER_DAY_MIN <= cap <= RECEIVED_EMAILS_PER_DAY_MAX:
            return cap
    raise InvalidSetting(
        "received_emails_per_day",
        f"Enter a number from {RECEIVED_EMAILS_PER_DAY_MIN:,} to {RECEIVED_EMAILS_PER_DAY_MAX:,}.",
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
        case CatalogList.CONES:
            return replace(studio, cones=items)
        case CatalogList.CLAY_BODIES:
            return replace(studio, clay_bodies=items)
