"""Drop-off, load and studio item IDs.

Issuing the numbers is the `IdNumbers` port's contract (phase 1d); this module only
formats and parses them.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import NewType, Self

ITEM_ID_MAX = 40
ID_DIGITS_MAX = 12  # far beyond any real count; refuses "AC-" plus thousands of digits
_NUMBER = rf"[1-9][0-9]{{0,{ID_DIGITS_MAX - 1}}}"
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def _check_number(number: int) -> None:
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError("an ID's number is a whole number from 1")


def _parse_number(prefix: str, text: str) -> int:
    match = re.fullmatch(rf"{prefix}-({_NUMBER})", text, flags=re.ASCII)
    if match is None:
        raise ValueError(f"not a {prefix}- ID")
    return int(match.group(1))


@dataclass(frozen=True, slots=True, order=True)
class DropOffId:
    number: int

    def __post_init__(self) -> None:
        _check_number(self.number)

    def __str__(self) -> str:
        return f"AC-{self.number}"

    @classmethod
    def parse(cls, text: str) -> Self:
        """`AC-12` only: no other case, no leading zero, at most 12 digits, nothing around it."""
        return cls(_parse_number("AC", text))


@dataclass(frozen=True, slots=True, order=True)
class LoadId:
    number: int

    def __post_init__(self) -> None:
        _check_number(self.number)

    def __str__(self) -> str:
        return f"L-{self.number}"

    @classmethod
    def parse(cls, text: str) -> Self:
        """`L-4` only: no other case, no leading zero, at most 12 digits, nothing around it."""
        return cls(_parse_number("L", text))


ItemId = NewType("ItemId", str)
"""A studio item's slug: 1 to 40 of `[a-z0-9-]`, made by `new_item_id`."""


def new_item_id(name: str, existing: Collection[ItemId]) -> ItemId:
    """A slug for `name` that isn't in `existing`: `Commercial glaze` gives `commercial-glaze`."""
    base = _NOT_SLUG.sub("-", name.lower()).strip("-")[:ITEM_ID_MAX].strip("-") or "item"
    if base not in existing:
        return ItemId(base)
    suffix = 2
    while True:
        tail = f"-{suffix}"
        candidate = base[: ITEM_ID_MAX - len(tail)].rstrip("-") + tail
        if candidate not in existing:
            return ItemId(candidate)
        suffix += 1
