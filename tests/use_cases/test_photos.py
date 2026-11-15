"""`ViewPhoto` (#3): a kept photo for the console, never a closed drop-off's."""

from datetime import timedelta

import pytest

from asmbly_ceramics.domain.errors import NotFound
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.photos import PhotoRef, PhotoSize
from asmbly_ceramics.ports.errors import PhotosUnavailable
from tests.use_cases.conftest import World
from tests.use_cases.flows import dropped_off, fired, send_all


@pytest.mark.parametrize("size", list(PhotoSize))
def test_a_kept_photo_is_read_in_either_size(world: World, size: PhotoSize) -> None:
    drop_off_id = dropped_off(world, 1)
    expected = world.photos.read(PhotoRef(drop_off_id, 1), size)
    assert world.view_photo(drop_off_id, 1, size) == expected


@pytest.mark.parametrize("past_the_last", [0, 1, 5])
def test_a_photo_the_drop_off_doesn_t_have_is_not_found(world: World, past_the_last: int) -> None:
    drop_off_id = dropped_off(world, 1)
    drop_off = world.records.drop_off(drop_off_id)
    assert drop_off is not None
    with pytest.raises(NotFound):
        world.view_photo(drop_off_id, len(drop_off.photos) + 1 + past_the_last, PhotoSize.FULL)
    with pytest.raises(NotFound):
        world.view_photo(drop_off_id, 0, PhotoSize.FULL)


def test_an_unknown_drop_off_is_not_found(world: World) -> None:
    with pytest.raises(NotFound):
        world.view_photo(DropOffId(999), 1, PhotoSize.THUMB)


def test_a_closed_drop_off_s_photos_are_not_found(world: World) -> None:
    drop_off_id = dropped_off(world, 1)
    fired(world, drop_off_id)
    send_all(world)
    world.clock.advance(timedelta(days=60))
    world.close()
    with pytest.raises(NotFound):
        world.view_photo(drop_off_id, 1, PhotoSize.FULL)


def test_a_photo_gone_from_the_store_is_not_found(world: World) -> None:
    drop_off_id = dropped_off(world, 1)
    world.photos.delete_drop_off(drop_off_id)
    with pytest.raises(NotFound):
        world.view_photo(drop_off_id, 1, PhotoSize.FULL)


def test_a_store_that_can_t_be_reached_is_unavailable(world: World) -> None:
    drop_off_id = dropped_off(world, 1)
    world.photos.fail_with = PhotosUnavailable("made-up-outage")
    with pytest.raises(PhotosUnavailable):
        world.view_photo(drop_off_id, 1, PhotoSize.FULL)
