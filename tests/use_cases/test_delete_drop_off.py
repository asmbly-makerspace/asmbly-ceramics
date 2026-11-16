"""Deleting a drop-off made by mistake or as a test, against the fakes: what is stored,
deleted, cancelled, sent and logged."""

import logging

import pytest

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus
from asmbly_ceramics.domain.errors import DropOffNotDeletable, NotFound, NotWaiting
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.photos import PhotoSize
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.errors import PhotosUnavailable, RecordsUnavailable
from asmbly_ceramics.ports.records import Conflict
from asmbly_ceramics.use_cases.reject import RejectRequest
from tests.domain.builders import NOW, STAFF, TEST_EMAIL, TEST_MESSAGE, TEST_NAME
from tests.use_cases.conftest import World
from tests.use_cases.flows import STAFF_MEMBER, dropped_off, email_of, loaded, send_all

AC_1, AC_2 = DropOffId(1), DropOffId(2)


def stored(world: World, id: DropOffId = AC_1) -> DropOff:
    drop_off = world.records.drop_off(id)
    assert drop_off is not None
    return drop_off


def delete(world: World, id: DropOffId = AC_1) -> DropOff:
    return world.delete_drop_off(id, stored(world, id).version, STAFF_MEMBER)


def test_delete_erases_details_and_photos_at_once_and_cancels_the_unsent_email(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    dropped_off(world, 1)
    assert world.photos.kept_count(AC_1) == 4  # two photos, each in both sizes
    commits = len(world.records.commits)

    deleted = delete(world)

    assert deleted.state is DropOffState.DELETED
    assert len(world.records.commits) == commits + 1  # the drop-off and its email together
    record = stored(world)
    assert (record.state, record.contact, record.photos) == (DropOffState.DELETED, None, ())
    assert (record.deleted_by, record.deleted_at) == (STAFF, NOW)
    assert world.photos.kept_count(AC_1) == 0
    assert email_of(world, AC_1, EmailKind.RECEIVED).status is EmailStatus.CANCELLED
    assert send_all(world) == []  # nothing left to send
    assert world.mailer.sent == []
    [event] = [vars(r) for r in caplog.records if r.getMessage() == "drop_off_deleted"]
    assert (event["drop_off_id"], event["user"]) == ("AC-1", STAFF)
    for line in caplog.records:
        assert TEST_NAME not in str(vars(line))
        assert TEST_EMAIL not in str(vars(line))


def test_a_sent_received_email_stays_sent(world: World) -> None:
    dropped_off(world, 1)
    send_all(world)

    delete(world)

    assert email_of(world, AC_1, EmailKind.RECEIVED).status is EmailStatus.SENT


def test_a_deleted_drop_off_leaves_every_list_but_is_found_by_its_id(world: World) -> None:
    dropped_off(world, 1)
    dropped_off(world, 2)

    delete(world)

    assert [row.drop_off.id for row in world.waiting().rows] == [AC_2]
    assert [row.drop_off.id for row in world.find("Test").rows] == [AC_2]
    assert world.find("AC-1", waiting_only=True).rows == ()
    [row] = world.find("AC-1").rows  # a slip with its ID still finds it
    assert row.drop_off.state is DropOffState.DELETED
    view = world.view(AC_1)
    assert (view.can_delete, view.can_reject, view.drop_off.contact) == (False, False, None)
    with pytest.raises(NotFound):
        world.view_photo(AC_1, 1, PhotoSize.FULL)


def test_a_deleted_drop_off_cant_be_loaded_rejected_or_deleted_again(world: World) -> None:
    dropped_off(world, 1)
    delete(world)
    commits = len(world.records.commits)

    with pytest.raises(NotWaiting):
        world.add_to_load(loaded(world), AC_1, confirmed=True, staff=STAFF_MEMBER)
    with pytest.raises(DropOffNotDeletable, match="AC-1 is deleted"):
        delete(world)

    assert len(world.records.commits) == commits + 1  # the load started above only


@pytest.mark.parametrize("state", ["in a load", "rejected"])
def test_only_a_waiting_drop_off_can_be_deleted(world: World, state: str) -> None:
    dropped_off(world, 1)
    if state == "in a load":
        loaded(world, AC_1)
    else:
        world.reject(RejectRequest(AC_1, ItemId("other"), TEST_MESSAGE, stored(world).version, STAFF_MEMBER))
    commits = len(world.records.commits)

    with pytest.raises(DropOffNotDeletable):
        delete(world)

    assert len(world.records.commits) == commits
    assert world.photos.kept_count(AC_1) == 4  # two photos, each in both sizes
    assert stored(world).contact is not None


def test_delete_with_a_stale_version_deletes_nothing(world: World) -> None:
    dropped_off(world, 1)
    shown = stored(world).version
    load_id = loaded(world, AC_1)
    world.remove_from_load(load_id, AC_1, STAFF_MEMBER)  # back to waiting, at a newer version

    with pytest.raises(Conflict):
        world.delete_drop_off(AC_1, shown, STAFF_MEMBER)

    assert world.photos.kept_count(AC_1) == 4  # two photos, each in both sizes
    assert stored(world).state is DropOffState.WAITING


def test_photos_that_cant_be_deleted_keep_everything(world: World) -> None:
    dropped_off(world, 1)
    commits = len(world.records.commits)
    world.photos.fail_with = PhotosUnavailable("ServiceUnavailable")

    with pytest.raises(PhotosUnavailable):
        delete(world)

    world.photos.fail_with = None
    assert len(world.records.commits) == commits
    assert stored(world).contact is not None


def test_a_commit_that_fails_after_the_photos_went_can_be_deleted_again(world: World) -> None:
    dropped_off(world, 1)
    world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")

    with pytest.raises(RecordsUnavailable):
        delete(world)

    assert world.photos.kept_count(AC_1) == 0  # photos first, as the close does
    assert stored(world).state is DropOffState.WAITING
    delete(world)  # staff try again: deleting photos already gone succeeds
    assert stored(world).state is DropOffState.DELETED


def test_a_deleted_drop_off_no_longer_keeps_its_firing_type_in_use(world: World) -> None:
    dropped_off(world, 1, firing_type="glaze", glaze_type="house-dip-glaze")
    assert world.records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("house-dip-glaze"))

    delete(world)

    assert not world.records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("house-dip-glaze"))
    assert not world.records.is_item_used(CatalogList.FIRING_TYPES, ItemId("glaze"))


def test_deleting_a_drop_off_that_doesnt_exist_is_not_found(world: World) -> None:
    with pytest.raises(NotFound):
        world.delete_drop_off(DropOffId(99), 1, STAFF_MEMBER)
