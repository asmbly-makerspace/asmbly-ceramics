from dataclasses import replace
from datetime import timedelta

import pytest

from asmbly_ceramics.domain.closing import close, is_closable
from asmbly_ceramics.domain.dropoff import DropOffState, Rejection
from asmbly_ceramics.domain.ids import ItemId, LoadId
from tests.domain.builders import NOW, STAFF, TEST_MESSAGE, a_drop_off

WINDOW = 14
DAYS = timedelta(days=WINDOW)
READY = NOW + timedelta(hours=2)  # the ready email went out after the firing


def test_fired_closes_after_the_window_from_the_ready_email() -> None:
    fired = a_drop_off(state=DropOffState.FIRED)
    assert not is_closable(fired, READY, WINDOW, READY + DAYS - timedelta(seconds=1))
    assert is_closable(fired, READY, WINDOW, READY + DAYS)
    # Counted from the ready email, not from the firing: a late email moves the close.
    assert not is_closable(fired, READY, WINDOW, NOW + DAYS)


def test_fired_without_a_sent_ready_email_never_closes() -> None:
    fired = a_drop_off(state=DropOffState.FIRED)
    assert not is_closable(fired, None, WINDOW, NOW + timedelta(days=365))


def test_rejected_closes_after_the_window_from_the_rejection() -> None:
    rejected = a_drop_off(state=DropOffState.REJECTED)
    assert not is_closable(rejected, None, WINDOW, NOW + DAYS - timedelta(seconds=1))
    assert is_closable(rejected, None, WINDOW, NOW + DAYS)


def test_the_window_is_the_studios_setting() -> None:
    rejected = a_drop_off(state=DropOffState.REJECTED)
    assert is_closable(rejected, None, 1, NOW + timedelta(days=1))
    assert not is_closable(rejected, None, 30, NOW + DAYS)


@pytest.mark.parametrize("state", [DropOffState.WAITING, DropOffState.IN_LOAD, DropOffState.CLOSED])
def test_waiting_never_closes(state: DropOffState) -> None:
    assert not is_closable(a_drop_off(state=state), READY, WINDOW, NOW + timedelta(days=365))


def test_is_closable_needs_a_window_and_an_aware_time() -> None:
    fired = a_drop_off(state=DropOffState.FIRED)
    with pytest.raises(ValueError, match="window"):
        is_closable(fired, READY, 0, NOW)
    with pytest.raises(ValueError, match="aware"):
        is_closable(fired, READY, WINDOW, NOW.replace(tzinfo=None))


@pytest.mark.parametrize("state", [DropOffState.FIRED, DropOffState.REJECTED, DropOffState.WAITING])
def test_is_closable_refuses_a_naive_ready_email_time(state: DropOffState) -> None:
    with pytest.raises(ValueError, match="aware"):
        is_closable(a_drop_off(state=state), READY.replace(tzinfo=None), WINDOW, NOW + DAYS)


def test_rejected_without_its_rejection_never_closes() -> None:
    rejected = replace(a_drop_off(state=DropOffState.REJECTED), rejection=None)
    assert not is_closable(rejected, None, WINDOW, NOW + timedelta(days=365))


def test_close_deletes_contact_message_and_photos_and_keeps_the_rest() -> None:
    rejected = a_drop_off(12, DropOffState.REJECTED, reason="has-glaze-issues")
    assert rejected.rejection is not None
    assert rejected.rejection.message == TEST_MESSAGE
    at = NOW + DAYS
    closed = close(rejected, at)
    assert (closed.state, closed.contact, closed.photos, closed.closed_at) == (
        DropOffState.CLOSED,
        None,
        (),
        at,
    )
    assert closed.rejection == Rejection(ItemId("has-glaze-issues"), None, STAFF, NOW)
    kept = ("id", "created_at", "firing_type", "glaze_type", "pieces", "load_id", "fired_at", "version")
    assert {name: getattr(closed, name) for name in kept} == {name: getattr(rejected, name) for name in kept}


def test_close_a_fired_drop_off_keeps_its_load_and_dates() -> None:
    fired = replace(a_drop_off(12, DropOffState.FIRED, load=4), version=3)
    closed = close(fired, READY + DAYS)
    assert (closed.state, closed.contact, closed.photos, closed.rejection) == (
        DropOffState.CLOSED,
        None,
        (),
        None,
    )
    assert (closed.load_id, closed.fired_at, closed.created_at, closed.version) == (LoadId(4), NOW, NOW, 3)
    assert (closed.pieces, closed.firing_type) == (fired.pieces, fired.firing_type)


@pytest.mark.parametrize(
    ("state", "said"),
    [(DropOffState.WAITING, "waiting"), (DropOffState.IN_LOAD, "in load"), (DropOffState.CLOSED, "closed")],
)
def test_close_refuses_a_waiting_drop_off(state: DropOffState, said: str) -> None:
    with pytest.raises(ValueError, match=f"AC-12 is {said}: only a fired or rejected drop-off closes"):
        close(a_drop_off(12, state), NOW)


def test_close_needs_an_aware_time() -> None:
    with pytest.raises(ValueError, match="aware"):
        close(a_drop_off(state=DropOffState.FIRED), NOW.replace(tzinfo=None))
