"""The studio's settings, read for every use case that needs them, and what the form offers.

The studio is data staff manage (#6). It is seeded with the starting values the first
time anything reads it, from the sending address composition passes in.
"""

# The error is named for what happened, as the plan's contract names its errors.
# ruff: noqa: N818

from dataclasses import dataclass

from asmbly_ceramics.domain.errors import UnknownItem
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.studio import (
    CatalogItem,
    CatalogList,
    ItemStatus,
    Studio,
    check_sending_address,
    starting_studio,
)
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import Conflict, Put, Records
from asmbly_ceramics.use_cases.log import log_event


class StudioNotSeeded(Exception):
    """A read-only `CurrentStudio` found no studio stored: a setup error."""

    def __init__(self) -> None:
        super().__init__("the studio's settings aren't stored yet")


class CurrentStudio:
    def __init__(
        self, records: Records, clock: Clock, initial_sending_address: str, *, seed: bool = True
    ) -> None:
        self._records = records
        self._clock = clock
        # Checked now, so a wrong value fails composition at start, not a person's form.
        self._initial_sending_address = check_sending_address(initial_sending_address)
        self._seed = seed

    def __call__(self) -> Studio:
        studio = self._records.studio()
        if studio is not None:
            return studio
        if not self._seed:
            raise StudioNotSeeded()
        new, change = starting_studio(self._initial_sending_address, self._clock.now())
        try:
            self._records.commit([Put(new), Put(change)])
        except Conflict:
            # Another request seeded it first: theirs is the studio.
            winner = self._records.studio()
            if winner is None:
                raise RecordsUnavailable("StudioMissing") from None
            return winner
        log_event("studio_seeded")
        # Read back, as the `Records` contract says, rather than guessing the stored version.
        stored = self._records.studio()
        if stored is None:
            raise RecordsUnavailable("StudioMissing")
        return stored


@dataclass(frozen=True, slots=True)
class StudioChoices:
    """What the form offers: active items only, in the studio's order."""

    firing_types: tuple[CatalogItem, ...]  # each says whether it needs_glaze_type
    glaze_types: tuple[CatalogItem, ...]


class ViewStudioChoices:
    def __init__(self, studio: CurrentStudio) -> None:
        self._studio = studio

    def __call__(self) -> StudioChoices:
        studio = self._studio()
        return StudioChoices(
            firing_types=active_items(studio.firing_types),
            glaze_types=active_items(studio.glaze_types),
        )


def item_name(studio: Studio, which: CatalogList, id: ItemId) -> str:
    """The item's name, retired or not, for a console page. An item the studio doesn't have
    (it never deletes a used one) shows as its ID, so one bad record can't hide a page."""
    try:
        return studio.item(which, id).name
    except UnknownItem:
        return str(id)


def active_items(items: tuple[CatalogItem, ...]) -> tuple[CatalogItem, ...]:
    """The items staff may still choose, for a form."""
    return tuple(item for item in items if item.status is ItemStatus.ACTIVE)
