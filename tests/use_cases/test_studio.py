"""`CurrentStudio` seeds the studio once; `ViewStudioChoices` offers active items only."""

import logging
from collections.abc import Sequence
from dataclasses import replace

import pytest

from asmbly_ceramics.adapters.memory.clock import FixedClock
from asmbly_ceramics.adapters.memory.records import MemoryRecords
from asmbly_ceramics.domain.errors import SendingAddressOutsideAsmbly
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.studio import (
    SYSTEM,
    CatalogList,
    ItemStatus,
    SettingChange,
    Studio,
    retire_item,
    starting_studio,
)
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import Change, Conflict, Put, Update
from asmbly_ceramics.use_cases.studio import CurrentStudio, StudioNotSeeded, ViewStudioChoices
from tests.domain.builders import NOW, STAFF, a_sending_address, an_address
from tests.use_cases.conftest import World


class RacingRecords(MemoryRecords):
    """Another request seeds the studio between this one's read and its commit."""

    def __init__(self, winner: Studio | None) -> None:
        super().__init__()
        self.winner = winner

    def commit(self, changes: Sequence[Change]) -> None:
        if self.winner is not None:
            winner, self.winner = self.winner, None
            super().commit([Put(winner), Put(SettingChange(NOW, SYSTEM, "Starting settings"))])
            self.fail_next_commit_with = Conflict()
        super().commit(changes)


def test_the_studio_is_seeded_once_with_the_starting_values(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    first = world.studio()
    second = world.studio()
    expected, change = starting_studio(a_sending_address(), NOW)
    assert first == second == replace(expected, version=1)
    assert len(world.records.commits) == 1
    assert world.records.commits[0] == (Put(expected), Put(change))
    assert [r.getMessage() for r in caplog.records] == ["studio_seeded"]


def test_studio_logs_hold_no_sending_address(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="asmbly_ceramics")
    world.studio()
    assert caplog.records
    for record in caplog.records:
        assert a_sending_address() not in str(vars(record))


def test_a_seeding_race_reads_the_winner(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    winner, _ = starting_studio(a_sending_address("studio"), NOW)
    records = RacingRecords(winner)
    studio = CurrentStudio(records, FixedClock(NOW), a_sending_address())()
    assert studio == replace(winner, version=1)
    assert studio.sending_address == a_sending_address("studio")
    assert len(records.commits) == 1  # only the winner's
    assert caplog.records == []  # this request seeded nothing


class ForgetfulRecords(MemoryRecords):
    """A table whose studio read finds nothing even after a commit landed."""

    def studio(self) -> Studio | None:
        super().studio()
        return None


def test_a_seeded_studio_that_cant_be_read_back_raises_records_unavailable() -> None:
    records = ForgetfulRecords()
    with pytest.raises(RecordsUnavailable) as raised:
        CurrentStudio(records, FixedClock(NOW), a_sending_address())()
    assert raised.value.code == "StudioMissing"
    assert len(records.commits) == 1


def test_a_conflict_with_no_studio_after_it_raises_records_unavailable(world: World) -> None:
    world.records.fail_next_commit_with = Conflict()
    with pytest.raises(RecordsUnavailable) as raised:
        world.studio()
    assert raised.value.code == "StudioMissing"


def test_records_unavailable_goes_up(world: World) -> None:
    world.records.fail_reads_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        world.studio()
    world.records.fail_reads_with = None
    world.records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
    with pytest.raises(RecordsUnavailable):
        world.studio()
    assert world.records.studio() is None


def test_a_wrong_initial_sending_address_fails_at_construction(world: World) -> None:
    with pytest.raises(SendingAddressOutsideAsmbly):
        CurrentStudio(world.records, world.clock, an_address("ceramics"))
    assert world.records.reads == []


def test_read_only_studio_raises_studio_not_seeded(world: World) -> None:
    read_only = CurrentStudio(world.records, world.clock, a_sending_address(), seed=False)
    with pytest.raises(StudioNotSeeded):
        read_only()
    assert world.records.commits == []
    seeded = world.studio()
    assert read_only() == seeded


def test_studio_choices_list_only_active_items(world: World) -> None:
    studio = world.studio()
    offered = ViewStudioChoices(world.studio)()
    assert [item.id for item in offered.firing_types] == [ItemId("bisque"), ItemId("glaze")]
    assert [item.needs_glaze_type for item in offered.firing_types] == [False, True]
    retired, _ = retire_item(studio, CatalogList.GLAZE_TYPES, studio.glaze_types[0].id, STAFF, NOW)
    retired, _ = retire_item(retired, CatalogList.FIRING_TYPES, ItemId("bisque"), STAFF, NOW)
    world.records.commit([Update(retired)])
    choices = ViewStudioChoices(world.studio)()
    assert [item.id for item in choices.firing_types] == [ItemId("glaze")]
    assert choices.firing_types[0].needs_glaze_type
    assert [item.name for item in choices.glaze_types] == [studio.glaze_types[1].name]
    assert all(item.status is ItemStatus.ACTIVE for item in choices.glaze_types)
