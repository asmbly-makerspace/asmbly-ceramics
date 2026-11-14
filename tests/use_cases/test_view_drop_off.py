"""`ViewDropOff` (#3, #5): one drop-off with its load, its emails and whether its rejection
can still be undone. The person is made up."""

from dataclasses import replace
from datetime import timedelta

import pytest

from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import (
    Email,
    EmailKind,
    claim,
    mark_failed,
    mark_sent,
    new_email,
    rejection_occasion,
)
from asmbly_ceramics.domain.errors import NotFound
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.limits import STALE_SENDING_AFTER
from asmbly_ceramics.domain.load import LoadStatus
from asmbly_ceramics.domain.studio import ItemStatus
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import Put, Update
from tests.domain.builders import NOW, a_drop_off, a_load
from tests.use_cases.conftest import World

AC_1 = DropOffId(1)


def failed(email: Email) -> Email:
    return mark_failed(claim(email, NOW), "Throttling")


def stored(world: World, drop_off: DropOff, *emails: Email) -> None:
    world.records.commit([Put(drop_off), *(Put(email) for email in emails)])


def test_view_drop_off_lists_its_emails_and_those_needing_attention(world: World) -> None:
    received = mark_sent(claim(new_email(AC_1, EmailKind.RECEIVED, NOW - timedelta(days=2)), NOW), NOW)
    ready = failed(new_email(AC_1, EmailKind.READY, NOW - timedelta(days=1)))
    stored(world, a_drop_off(1, DropOffState.FIRED, load=4), received, ready)
    world.records.commit([Put(a_load(4, LoadStatus.FIRED, [1]))])

    view = world.view(AC_1)

    assert str(view.drop_off.id) == "AC-1"
    assert (view.firing_type, view.glaze_type) == ("Bisque", None)
    assert view.load is not None
    assert str(view.load.id) == "L-4"
    assert [email.kind for email in view.emails] == [EmailKind.RECEIVED, EmailKind.READY]
    assert [email.kind for email in view.emails_needing_attention] == [EmailKind.READY]
    assert not view.can_undo_rejection


def test_an_email_stuck_sending_needs_attention(world: World) -> None:
    sending = claim(
        new_email(AC_1, EmailKind.RECEIVED, NOW), NOW - STALE_SENDING_AFTER - timedelta(seconds=1)
    )
    stored(world, a_drop_off(1), sending)

    assert [email.kind for email in world.view(AC_1).emails_needing_attention] == [EmailKind.RECEIVED]


def test_view_unknown_id_is_not_found(world: World) -> None:
    with pytest.raises(NotFound, match="AC-9 doesn't exist"):
        world.view(DropOffId(9))


def test_an_undone_rejections_failed_email_does_not_need_attention(world: World) -> None:
    earlier = NOW - timedelta(hours=1)
    rejected_email = failed(new_email(AC_1, EmailKind.REJECTED, earlier, rejection_occasion(earlier)))
    stored(world, a_drop_off(1), rejected_email)  # waiting again: the rejection was undone

    view = world.view(AC_1)

    assert [email.kind for email in view.emails] == [EmailKind.REJECTED]
    assert view.emails_needing_attention == ()


def test_a_current_rejections_failed_email_needs_attention(world: World) -> None:
    drop_off = a_drop_off(1, DropOffState.REJECTED)
    assert drop_off.rejection is not None
    occasion = rejection_occasion(drop_off.rejection.at)
    stored(world, drop_off, failed(new_email(AC_1, EmailKind.REJECTED, NOW, occasion)))

    assert [email.kind for email in world.view(AC_1).emails_needing_attention] == [EmailKind.REJECTED]


def test_a_rejection_can_be_undone_the_same_austin_day_only(world: World) -> None:
    stored(world, a_drop_off(1, DropOffState.REJECTED))

    assert world.view(AC_1).can_undo_rejection
    world.clock.advance(timedelta(days=1))
    assert not world.view(AC_1).can_undo_rejection


@pytest.mark.parametrize("state", [DropOffState.WAITING, DropOffState.IN_LOAD, DropOffState.CLOSED])
def test_only_a_rejected_drop_off_can_be_undone(world: World, state: DropOffState) -> None:
    stored(world, a_drop_off(1, state))

    assert not world.view(AC_1).can_undo_rejection


def test_the_reject_form_offers_active_reasons_only(world: World) -> None:
    studio = world.studio()
    reasons = tuple(
        replace(item, status=ItemStatus.RETIRED) if item.id == ItemId("has-glaze-issues") else item
        for item in studio.reasons
    )
    world.records.commit([Update(replace(studio, reasons=reasons))])
    stored(world, a_drop_off(1))

    assert [item.id for item in world.view(AC_1).reasons] == ["needs-more-time-to-dry", "other"]


def test_a_glaze_drop_off_shows_its_glaze_types_name(world: World) -> None:
    drop_off = replace(a_drop_off(1), firing_type=ItemId("glaze"), glaze_type=ItemId("commercial-glaze"))
    stored(world, drop_off)

    view = world.view(AC_1)

    assert (view.firing_type, view.glaze_type, view.load) == ("Glaze", "Commercial glaze", None)


def test_a_closed_drop_offs_failed_email_does_not_need_attention(world: World) -> None:
    stored(world, a_drop_off(1, DropOffState.CLOSED), failed(new_email(AC_1, EmailKind.RECEIVED, NOW)))

    view = world.view(AC_1)

    assert [email.kind for email in view.emails] == [EmailKind.RECEIVED]
    assert view.emails_needing_attention == ()


def test_view_raises_when_records_are_unavailable(world: World) -> None:
    world.records.fail_reads_with = RecordsUnavailable("ThrottlingException")

    with pytest.raises(RecordsUnavailable):
        world.view(AC_1)


def test_a_rejected_drop_off_names_its_reason_even_once_retired(world: World) -> None:
    studio = world.studio()
    reasons = tuple(
        replace(item, status=ItemStatus.RETIRED) if item.id == ItemId("other") else item
        for item in studio.reasons
    )
    world.records.commit([Update(replace(studio, reasons=reasons))])
    stored(world, a_drop_off(1, DropOffState.REJECTED))

    view = world.view(AC_1)

    assert view.rejection_reason == "Other"
    assert "other" not in [item.id for item in view.reasons]


def test_a_waiting_drop_off_has_no_rejection_reason(world: World) -> None:
    stored(world, a_drop_off(1))

    assert world.view(AC_1).rejection_reason is None
