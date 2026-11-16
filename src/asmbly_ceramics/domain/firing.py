"""A load's firing record (#42): how it was fired, how it went and what it cost.

Every field is optional: a load can be fired with none filled in, and staff can fill them
in or correct them at any stage. The record holds numbers and studio items only, never a
person's details. `read_firing_record` checks what the console's form sends against the
limits the story states (`domain.limits`) and reports every refused field at once, by
name and with fixed text, never quoting the value sent.
"""

import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum

from asmbly_ceramics.domain.errors import InvalidRecord
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import (
    BOARD_TEMP_F_MAX,
    BOARD_TEMP_F_MIN,
    COST_CENTS_MAX,
    FIRING_MINUTES_MAX,
    FIRING_NUMBER_MAX,
    FIRING_NUMBER_MIN,
    HOLD_MINUTES_MAX,
    PERCENT_MAX,
    PERCENT_MIN,
    PREHEAT_HOURS_MAX,
    TEMP_F_MAX,
    TEMP_F_MIN,
)


class Speed(StrEnum):
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"


class NoCone(StrEnum):
    NO_CONE = "none"  # "no cone at this spot", not "not recorded" (that is None)


NO_CONE = NoCone.NO_CONE

ConeReading = int | NoCone
"""How far a witness cone bent, a whole % from 0 to 100 (100 is fully down), or `NO_CONE`."""


@dataclass(frozen=True, slots=True)
class Program:
    preheat_hours: int | None = None
    cone: ItemId | None = None  # a cone from the studio's list
    speed: Speed | None = None
    hold_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class FiringRecord:
    percent_full: int | None = None
    firing_number: int | None = None  # since the kiln's last elements
    all_time_number: int | None = None
    program: Program = Program()
    firing_minutes: int | None = None
    max_temp_f: int | None = None
    board_temp_f: int | None = None
    cost_cents: int | None = None
    cone_top: ConeReading | None = None
    cone_center: ConeReading | None = None
    cone_bottom: ConeReading | None = None


EMPTY_RECORD = FiringRecord()

RECORD_FIELDS: tuple[str, ...] = (
    "percent_full",
    "firing_number",
    "all_time_number",
    "preheat_hours",
    "cone",
    "speed",
    "hold_minutes",
    "firing_time",
    "max_temp_f",
    "board_temp_f",
    "cost",
    "cone_top",
    "cone_center",
    "cone_bottom",
)
"""The form's field names, in the order the page shows them."""

_LABELS = {
    "percent_full": "% full",
    "firing_number": "Firing number",
    "all_time_number": "All-time number",
    "preheat_hours": "Preheat",
    "cone": "Cone",
    "speed": "Speed",
    "hold_minutes": "Hold",
    "firing_time": "Firing time",
    "max_temp_f": "Max temp",
    "board_temp_f": "Board temp",
    "cost": "Cost",
    "cone_top": "Top cone",
    "cone_center": "Center cone",
    "cone_bottom": "Bottom cone",
}

_WHOLE_NUMBER = re.compile(r"[0-9]+", flags=re.ASCII)
_DURATION = re.compile(r"([0-9]{1,2}):([0-5][0-9])", flags=re.ASCII)
_DOLLARS = re.compile(r"\$?([0-9]{1,3})(?:\.([0-9]{1,2}))?", flags=re.ASCII)
_FIRING_TIME_MAX_TEXT = f"{FIRING_MINUTES_MAX // 60}:{FIRING_MINUTES_MAX % 60:02d}"  # "72:00"
_COST_MAX_TEXT = f"${COST_CENTS_MAX // 100}.{COST_CENTS_MAX % 100:02d}"  # "$100.00"
_DURATION_TEXT_MAX = len(_FIRING_TIME_MAX_TEXT)
_DOLLARS_TEXT_MAX = len(_COST_MAX_TEXT)

_WHOLE_RANGES = {
    "percent_full": (PERCENT_MIN, PERCENT_MAX),
    "firing_number": (FIRING_NUMBER_MIN, FIRING_NUMBER_MAX),
    "all_time_number": (FIRING_NUMBER_MIN, FIRING_NUMBER_MAX),
    "preheat_hours": (0, PREHEAT_HOURS_MAX),
    "hold_minutes": (0, HOLD_MINUTES_MAX),
    "max_temp_f": (TEMP_F_MIN, TEMP_F_MAX),
    "board_temp_f": (BOARD_TEMP_F_MIN, BOARD_TEMP_F_MAX),
}

_FIRING_TIME_MESSAGE = (
    f"Enter the firing time as hours and minutes, like 11:38, up to {_FIRING_TIME_MAX_TEXT}."
)
_COST_MESSAGE = f"Enter the cost in dollars, like 8.19, up to {_COST_MAX_TEXT}."
_CONE_MESSAGE = "Pick a cone from the list."
_SPEED_MESSAGE = "Pick slow, medium or fast."
_CONE_READING_MESSAGE = f"Enter a whole % from {PERCENT_MIN} to {PERCENT_MAX}, or pick no cone."


class _RefusedError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


class _Reader:
    """Reads the page's fields one at a time, keeping every refused field's message."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = values
        self.errors: dict[str, str] = {}

    def read[T](self, field: str, check: Callable[[str], T]) -> T | None:
        raw = self._values.get(field)
        text = raw.strip() if isinstance(raw, str) else ""
        if not text:
            return None
        try:
            return check(text)
        except _RefusedError as refused:
            self.errors[field] = refused.message
            return None

    def whole(self, field: str) -> int | None:
        low, high = _WHOLE_RANGES[field]
        return self.read(
            field, lambda text: _whole(text, low, high, f"Enter a whole number from {low:,} to {high:,}.")
        )

    def refuse_if_any(self) -> None:
        if self.errors:
            raise InvalidRecord(
                {field: self.errors[field] for field in RECORD_FIELDS if field in self.errors}
            )


def read_program(values: Mapping[str, str], cones: Collection[ItemId]) -> Program:
    """The four program fields the page sent (preheat_hours, cone, speed, hold_minutes),
    each optional and checked as `read_firing_record` checks them. `InvalidRecord` names
    every refused field; no message quotes the value sent."""
    reader = _Reader(values)
    program = _program(reader, cones)
    reader.refuse_if_any()
    return program


def _program(reader: _Reader, cones: Collection[ItemId]) -> Program:
    def cone(text: str) -> ItemId:
        if text not in cones:
            raise _RefusedError(_CONE_MESSAGE)
        return ItemId(text)

    return Program(
        preheat_hours=reader.whole("preheat_hours"),
        cone=reader.read("cone", cone),
        speed=reader.read("speed", _speed),
        hold_minutes=reader.whole("hold_minutes"),
    )


def read_firing_record(values: Mapping[str, str], cones: Collection[ItemId]) -> FiringRecord:
    """The record the page sent. Every field is optional: a missing or blank one is None.

    Each is stripped and checked, length first, so `int()` never sees thousands of digits:
    whole numbers in range; the firing time as `H:MM` or `HH:MM`, at most 72:00; the cost
    as dollars (`8`, `8.1`, `8.19`, an optional `$`), at most $100, kept as cents; the
    cone, an ID in `cones` (the caller's choice: `SaveFiringRecord` passes the active
    cones and the one the record already names); the speed, a `Speed`;
    each witness cone a whole % or `none`. `InvalidRecord` names every refused field with
    its message; no message quotes the value sent.
    """
    reader = _Reader(values)
    record = FiringRecord(
        percent_full=reader.whole("percent_full"),
        firing_number=reader.whole("firing_number"),
        all_time_number=reader.whole("all_time_number"),
        program=_program(reader, cones),
        firing_minutes=reader.read("firing_time", _firing_minutes),
        max_temp_f=reader.whole("max_temp_f"),
        board_temp_f=reader.whole("board_temp_f"),
        cost_cents=reader.read("cost", _cost_cents),
        cone_top=reader.read("cone_top", _cone_reading),
        cone_center=reader.read("cone_center", _cone_reading),
        cone_bottom=reader.read("cone_bottom", _cone_reading),
    )
    reader.refuse_if_any()
    return record


def _whole(text: str, low: int, high: int, message: str) -> int:
    if len(text) <= len(str(high)) and _WHOLE_NUMBER.fullmatch(text):
        number = int(text)
        if low <= number <= high:
            return number
    raise _RefusedError(message)


def _firing_minutes(text: str) -> int:
    match = _DURATION.fullmatch(text) if len(text) <= _DURATION_TEXT_MAX else None
    if match is not None:
        minutes = int(match[1]) * 60 + int(match[2])
        if minutes <= FIRING_MINUTES_MAX:
            return minutes
    raise _RefusedError(_FIRING_TIME_MESSAGE)


def _cost_cents(text: str) -> int:
    match = _DOLLARS.fullmatch(text) if len(text) <= _DOLLARS_TEXT_MAX else None
    if match is not None:
        cents = int(match[1]) * 100 + int((match[2] or "0").ljust(2, "0"))
        if cents <= COST_CENTS_MAX:
            return cents
    raise _RefusedError(_COST_MESSAGE)


def _speed(text: str) -> Speed:
    try:
        return Speed(text.lower())
    except ValueError:
        raise _RefusedError(_SPEED_MESSAGE) from None


def _cone_reading(text: str) -> ConeReading:
    if text.lower() == NO_CONE.value:
        return NO_CONE
    return _whole(text, PERCENT_MIN, PERCENT_MAX, _CONE_READING_MESSAGE)


def record_changes(
    old: FiringRecord, new: FiringRecord, cone_name: Callable[[ItemId], str]
) -> tuple[str, ...]:
    """One line per changed field, in the page's order, with its new value as the page
    shows it ("Max temp: 2,236 °F", "Cost: $8.19", "Bottom cone: no cone", "Firing time:
    cleared"). Empty when nothing changed. Phase 5 writes them into the load's history."""
    lines: list[str] = []
    for field in changed_fields(old, new):
        after = _value(new, field)
        shown = "cleared" if after is None else _shown(field, after, cone_name)
        lines.append(f"{_LABELS[field]}: {shown}")
    return tuple(lines)


def changed_fields(old: FiringRecord, new: FiringRecord) -> tuple[str, ...]:
    """The names (`RECORD_FIELDS`) of the fields that differ, in the page's order: what a
    log line may say about a saved record, never the values."""
    return tuple(field for field in RECORD_FIELDS if _value(old, field) != _value(new, field))


def record_values(record: FiringRecord) -> dict[str, str]:
    """The record as the form shows it, one text per field in `RECORD_FIELDS` ("" when not
    recorded): whole numbers without separators, the firing time as `H:MM` ("11:38"), the
    cost in dollars ("8.19"), the cone's ID, the speed, and a witness cone as a % or
    "none". `read_firing_record` reads it back to the same record."""
    values: dict[str, str] = {}
    for field in RECORD_FIELDS:
        value = _value(record, field)
        match field, value:
            case (_, None):
                values[field] = ""
            case ("firing_time", int()):
                values[field] = f"{value // 60}:{value % 60:02d}"
            case ("cost", int()):
                values[field] = f"{value // 100}.{value % 100:02d}"
            case (_, StrEnum()):
                values[field] = value.value
            case _:
                values[field] = str(value)
    return values


def _value(record: FiringRecord, field: str) -> object:
    match field:
        case "preheat_hours" | "cone" | "speed" | "hold_minutes":
            return getattr(record.program, field)
        case "firing_time":
            return record.firing_minutes
        case "cost":
            return record.cost_cents
        case _:
            return getattr(record, field)


def _shown(field: str, value: object, cone_name: Callable[[ItemId], str]) -> str:
    match field, value:
        case ("cone", str()):
            return cone_name(ItemId(value))
        case ("speed", Speed()):
            return value.value
        case (_, NoCone()):
            return "no cone"
        case ("percent_full" | "cone_top" | "cone_center" | "cone_bottom", int()):
            return f"{value}%"
        case ("preheat_hours", int()):
            return f"{value} h"
        case ("hold_minutes", int()):
            return f"{value} min"
        case ("firing_time", int()):
            return f"{value // 60}:{value % 60:02d}"
        case ("max_temp_f" | "board_temp_f", int()):
            return f"{value:,} °F"
        case ("cost", int()):
            return f"${value // 100}.{value % 100:02d}"
        case _:
            return f"{value:,}" if isinstance(value, int) else str(value)
