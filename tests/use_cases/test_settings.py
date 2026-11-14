"""The settings use cases and the test email (#6), against the fakes."""

import logging
from datetime import timedelta

import pytest

from asmbly_ceramics.domain.email import EmailStatus
from asmbly_ceramics.domain.errors import (
    DuplicateItem,
    InvalidSetting,
    ItemInUse,
    NoStaffEmail,
    SendingAddressOutsideAsmbly,
    TestEmailFailed,
    UnknownItem,
)
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.studio import CatalogList, ItemStatus, Studio
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import BadCursor, Conflict
from asmbly_ceramics.ports.staff import StaffMember
from tests.domain.builders import NOW, STAFF, a_sending_address, an_address
from tests.use_cases.conftest import World
from tests.use_cases.flows import ATHENA, BISQUE, STAFF_EMAIL, STAFF_MEMBER, dropped_off, loaded

KILNS = CatalogList.KILNS


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, object]]:
    return [vars(r) for r in caplog.records if r.getMessage() == name]


def change_email(
    world: World, *, address: str | None = None, window: str = "14", hours: str | None = None
) -> Studio:
    studio = world.studio()
    return world.change_email_settings(
        sending_address=address if address is not None else studio.sending_address,
        pickup_window_days=window,
        pickup_hours_text=hours if hours is not None else studio.pickup_hours_text,
        version=studio.version,
        staff=STAFF_MEMBER,
    )


# Email settings and the test email


def test_an_address_outside_asmbly_org_is_refused(world: World) -> None:
    commits = len(world.records.commits)
    for address in (an_address("ceramics"), an_address("ceramics", "asmbly.org.example.org")):
        with pytest.raises(SendingAddressOutsideAsmbly):
            change_email(world, address=address)
        with pytest.raises(SendingAddressOutsideAsmbly):
            world.send_test_email(sending_address=address, staff=STAFF_MEMBER)
    assert len(world.records.commits) == commits + 1  # only the studio's seeding
    assert world.mailer.sent == []


def test_email_settings_are_saved_with_the_new_values(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    saved = change_email(world, address=a_sending_address("kilnops"), window="10", hours="Daily, 9 to 5.")

    assert (saved.sending_address, saved.pickup_window_days, saved.pickup_hours_text) == (
        a_sending_address("kilnops"),
        10,
        "Daily, 9 to 5.",
    )
    assert world.studio() == saved
    [event] = events(caplog, "settings_changed")
    assert event["user"] == STAFF


def test_saving_the_same_values_commits_and_logs_nothing(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    before = world.studio()
    commits = len(world.records.commits)

    assert change_email(world) == before

    assert len(world.records.commits) == commits
    assert events(caplog, "settings_changed") == []


def test_the_test_email_goes_from_the_new_address_to_the_signed_in_staff_member_and_saves_nothing(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    before = world.studio()
    commits = len(world.records.commits)

    world.send_test_email(sending_address=" " + an_address("kilnops", "ASMBLY.ORG") + " ", staff=STAFF_MEMBER)

    [message] = world.mailer.sent
    assert message.to == STAFF_EMAIL
    assert message.from_address == message.reply_to == a_sending_address("kilnops")
    assert message.inline == ()
    assert a_sending_address("kilnops") in message.text  # the test email names the new address
    assert world.studio() == before
    assert len(world.records.commits) == commits
    assert world.records.emails_in(set(EmailStatus)) == []  # nothing queued
    [event] = events(caplog, "test_email")
    assert (event["user"], event["outcome"]) == (STAFF, "sent")


def test_a_test_email_without_a_staff_email_is_refused(world: World) -> None:
    with pytest.raises(NoStaffEmail):
        world.send_test_email(sending_address=a_sending_address(), staff=StaffMember(STAFF, None))
    assert world.mailer.sent == []


def test_a_failed_test_email_reports_the_code(world: World, caplog: pytest.LogCaptureFixture) -> None:
    world.mailer.fail_with = "MessageRejected"

    with pytest.raises(TestEmailFailed) as failed:
        world.send_test_email(sending_address=a_sending_address(), staff=STAFF_MEMBER)

    assert failed.value.code == "MessageRejected"
    [event] = events(caplog, "test_email")
    assert (event["outcome"], event["error_code"]) == ("failed", "MessageRejected")


def test_a_test_email_to_a_token_address_that_isnt_one_fails(world: World) -> None:
    with pytest.raises(TestEmailFailed) as failed:
        world.send_test_email(sending_address=a_sending_address(), staff=StaffMember(STAFF, "not an address"))
    assert failed.value.code == "bad_recipient"
    assert world.mailer.sent == []


# The history


def test_every_change_records_who_and_when(world: World) -> None:
    world.studio()
    world.clock.advance(timedelta(minutes=5))
    change_email(world, window="21")
    world.clock.advance(timedelta(minutes=5))
    world.add_item(
        KILNS,
        "Kiln Four",
        needs_glaze_type=False,
        needs_message=False,
        version=world.studio().version,
        staff=STAFF_MEMBER,
    )

    history = world.view_studio().history

    assert [(c.what, c.by, c.at) for c in history] == [
        ("Added kiln Kiln Four", STAFF, NOW + timedelta(minutes=10)),
        ("Pickup window: 14 → 21 days", STAFF, NOW + timedelta(minutes=5)),
        ("Starting settings", "system", NOW),
    ]


def test_history_pages_newest_first(world: World) -> None:
    world.studio()
    for minutes in range(1, 5):
        world.clock.advance(timedelta(minutes=1))
        change_email(world, window=str(14 + minutes))

    first = world.view_studio(limit=2)
    second = world.view_studio(before=first.older, limit=2)
    third = world.view_studio(before=second.older, limit=2)

    assert [c.what for c in first.history] == ["Pickup window: 17 → 18 days", "Pickup window: 16 → 17 days"]
    assert [c.what for c in second.history] == ["Pickup window: 15 → 16 days", "Pickup window: 14 → 15 days"]
    assert [c.what for c in third.history] == ["Starting settings"]
    assert third.older is None
    with pytest.raises(BadCursor):
        world.view_studio(before="not-a-cursor")


def test_history_pages_keep_the_changes_of_one_save_together(world: World) -> None:
    world.studio()
    world.clock.advance(timedelta(minutes=1))
    change_email(world, address=a_sending_address("kilnops"), window="21", hours="Daily, 9 to 5.")

    first = world.view_studio(limit=2)
    rest = world.view_studio(before=first.older, limit=2)

    whats = [c.what for c in (*first.history, *rest.history)]
    assert sorted(whats[:3]) == [
        "Changed the pickup hours text",
        "Changed the sending address",
        "Pickup window: 14 → 21 days",
    ]
    assert whats[3:] == ["Starting settings"]


def test_the_history_holds_no_sending_address(world: World) -> None:
    change_email(world, address=a_sending_address("kilnops"))

    texts = [c.what for c in world.view_studio().history]

    assert "Changed the sending address" in texts
    assert not any("@" in text for text in texts)


def test_a_stale_version_is_a_conflict(world: World) -> None:
    stale = world.studio().version
    change_email(world, window="21")
    commits = len(world.records.commits)

    with pytest.raises(Conflict):
        world.change_email_settings(
            sending_address=a_sending_address(),
            pickup_window_days="7",
            pickup_hours_text="Daily.",
            version=stale,
            staff=STAFF_MEMBER,
        )
    with pytest.raises(Conflict):
        world.retire_item(KILNS, ATHENA, stale, STAFF_MEMBER)

    assert len(world.records.commits) == commits
    assert world.studio().pickup_window_days == 21


# The lists


def test_adding_an_item_records_its_list_and_id(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    studio = world.add_item(
        KILNS,
        "Kiln Four",
        needs_glaze_type=False,
        needs_message=False,
        version=world.studio().version,
        staff=STAFF_MEMBER,
    )

    assert studio.kilns[-1].name == "Kiln Four"
    [event] = events(caplog, "settings_changed")
    assert (event["list"], event["item"], event["user"]) == ("kilns", "kiln-four", STAFF)
    with pytest.raises(DuplicateItem):
        world.add_item(
            KILNS,
            "kiln four",
            needs_glaze_type=False,
            needs_message=False,
            version=studio.version,
            staff=STAFF_MEMBER,
        )


def test_a_used_kiln_can_be_retired_not_deleted(world: World) -> None:
    loaded(world)  # a load on Athena
    retired = world.retire_item(KILNS, ATHENA, world.studio().version, STAFF_MEMBER)
    assert retired.item(KILNS, ATHENA).status is ItemStatus.RETIRED
    assert world.view_studio().used[KILNS, ATHENA] is True

    with pytest.raises(ItemInUse):
        world.delete_item(KILNS, ATHENA, retired.version, STAFF_MEMBER)

    assert world.studio().item(KILNS, ATHENA).status is ItemStatus.RETIRED
    restored = world.restore_item(KILNS, ATHENA, retired.version, STAFF_MEMBER)
    assert restored.item(KILNS, ATHENA).status is ItemStatus.ACTIVE


def test_an_active_item_must_be_retired_before_it_is_deleted(world: World) -> None:
    reads = len(world.records.reads)
    with pytest.raises(InvalidSetting) as refused:
        world.delete_item(KILNS, ItemId("vulcan"), world.studio().version, STAFF_MEMBER)
    assert refused.value.message == "Retire Vulcan before deleting it."
    # Use is asked only once retiring has stopped new use.
    assert "is_item_used" not in world.records.reads[reads:]


def test_a_retired_unused_item_can_be_deleted(world: World) -> None:
    retired = world.retire_item(KILNS, ItemId("vulcan"), world.studio().version, STAFF_MEMBER)
    assert world.view_studio().used[KILNS, ItemId("vulcan")] is False

    deleted = world.delete_item(KILNS, ItemId("vulcan"), retired.version, STAFF_MEMBER)

    assert [kiln.id for kiln in deleted.kilns] == [ATHENA, ItemId("helios")]
    with pytest.raises(UnknownItem):
        world.delete_item(KILNS, ItemId("vulcan"), deleted.version, STAFF_MEMBER)
    assert world.view_studio().history[0].what == "Deleted kiln Vulcan"


def test_a_new_firing_type_needing_a_glaze_type_is_offered_by_the_form(world: World) -> None:
    world.add_item(
        CatalogList.FIRING_TYPES,
        "Raku",
        needs_glaze_type=True,
        needs_message=False,
        version=world.studio().version,
        staff=STAFF_MEMBER,
    )

    offered = {item.id: item.needs_glaze_type for item in world.choices().firing_types}
    assert offered[ItemId("raku")] is True
    id = dropped_off(world, 1, firing_type="raku", glaze_type="house-dip-glaze")
    drop_off = world.records.drop_off(id)
    assert drop_off is not None
    assert (drop_off.firing_type, drop_off.glaze_type) == (ItemId("raku"), ItemId("house-dip-glaze"))
    assert BISQUE in offered


def test_a_store_that_cant_be_reached_saves_nothing(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    before = world.studio()
    world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")

    with pytest.raises(RecordsUnavailable):
        change_email(world, window="21")

    assert world.studio() == before
    assert events(caplog, "settings_changed") == []
    world.records.fail_reads_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        world.view_studio()
