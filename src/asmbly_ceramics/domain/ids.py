"""Identifiers. Issuing numbers is the `IdNumbers` port's job; formatting is the domain's."""

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import NewType, Self

ItemId = NewType("ItemId", str)  # a slug, 1-40 of [a-z0-9-]

_DROP_OFF = re.compile(r"AC-([1-9][0-9]*)")
_LOAD = re.compile(r"L-([1-9][0-9]*)")
_SLUG_MAX = 40


@dataclass(frozen=True, slots=True, order=True)
class DropOffId:
    number: int

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("A drop-off number starts at 1.")

    def __str__(self) -> str:
        return f"AC-{self.number}"

    @classmethod
    def parse(cls, text: str) -> Self:
        found = _DROP_OFF.fullmatch(text)
        if found is None:
            raise ValueError("Not a drop-off ID.")
        return cls(int(found.group(1)))


@dataclass(frozen=True, slots=True, order=True)
class LoadId:
    number: int

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("A load number starts at 1.")

    def __str__(self) -> str:
        return f"L-{self.number}"

    @classmethod
    def parse(cls, text: str) -> Self:
        found = _LOAD.fullmatch(text)
        if found is None:
            raise ValueError("Not a load ID.")
        return cls(int(found.group(1)))


def new_item_id(name: str, existing: Collection[ItemId]) -> ItemId:
    """A slug from `name`, made unique among `existing` with a numeric suffix."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:_SLUG_MAX].strip("-") or "item"
    candidate, n = slug, 1
    while ItemId(candidate) in existing:
        n += 1
        suffix = f"-{n}"
        candidate = slug[: _SLUG_MAX - len(suffix)].rstrip("-") + suffix
    return ItemId(candidate)
