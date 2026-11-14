from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pytest

from asmbly_ceramics.domain.closing import close, is_due_to_close, pickup_day, pickup_deadline
from asmbly_ceramics.domain.dropoff import DropOff, DropOffState, Rejection
from asmbly_ceramics.domain.email import Email, EmailKind, claim, mark_sent, new_email
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import STUDIO_TZ
from tests.domain.builders import NOW, STAFF, TEST_MESSAGE, a_drop_off, a_sent_ready_email

WINDOW = 14
DAYS = timedelta(days=WINDOW)
READY = NOW + timedelta(hours=2)  # the ready email went out after the firing
# NOW is 12:30 PM CST on Fri 13 Nov 2026, READY 2:30 PM: the windows end at Austin midnight.
READY_END = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)  # 00:00 CST Sat 28 Nov
REJECTED_END = READY_END  # the rejection (NOW) is the same Austin day
SECOND = timedelta(seconds=1)


def is_closable(drop_off: DropOff, ready_sent_at: datetime | None, window: int, now: datetime) -> bool:
    """`is_due_to_close` for a ready email sent at `ready_sent_at` (unsent when `None`) that
    gave `window`; a drop-off that isn't fired is given `window` as the studio's."""
    if drop_off.state is not DropOffState.FIRED:
        return is_due_to_close(drop_off, None, window, now)
    unsent = claim(new_email(drop_off.id, EmailKind.READY, NOW), NOW)
    ready = unsent if ready_sent_at is None else a_sent_ready_email(drop_off.id, ready_sent_at, window)
    return is_due_to_close(drop_off, ready, window, now)


def test_fired_closes_after_the_window_from_the_ready_email() -> None:
    fired = a_drop_off(state=DropOffState.FIRED)
    assert pickup_deadline(READY, WINDOW) == READY_END
    assert not is_closable(fired, READY, WINDOW, READY_END - SECOND)
    assert is_closable(fired, READY, WINDOW, READY_END)
    # Counted from the ready email, not from the firing: a late email moves the close.
    late = NOW + timedelta(days=2)
    assert not is_closable(fired, late, WINDOW, READY_END)
    assert is_closable(fired, late, WINDOW, READY_END + timedelta(days=2))


def test_fired_without_a_sent_ready_email_never_closes() -> None:
    fired = a_drop_off(state=DropOffState.FIRED)
    assert not is_closable(fired, None, WINDOW, NOW + timedelta(days=365))


def test_rejected_closes_after_the_window_from_the_rejection() -> None:
    rejected = a_drop_off(state=DropOffState.REJECTED)
    assert not is_closable(rejected, None, WINDOW, REJECTED_END - SECOND)
    assert is_closable(rejected, None, WINDOW, REJECTED_END)


def test_the_window_is_the_studios_setting() -> None:
    rejected = a_drop_off(state=DropOffState.REJECTED)
    assert not is_closable(rejected, None, 1, REJECTED_END - timedelta(days=13) - SECOND)
    assert is_closable(rejected, None, 1, REJECTED_END - timedelta(days=13))
    assert not is_closable(rejected, None, 30, NOW + timedelta(days=30))


@pytest.mark.parametrize("state", [DropOffState.WAITING, DropOffState.IN_LOAD, DropOffState.CLOSED])
def test_waiting_never_closes(state: DropOffState) -> None:
    assert not is_closable(a_drop_off(state=state), READY, WINDOW, NOW + timedelta(days=365))


def test_is_closable_needs_a_window_and_an_aware_time() -> None:
    fired = a_drop_off(state=DropOffState.FIRED)
    with pytest.raises(ValueError, match="window"):
        is_closable(fired, READY, 0, NOW)
    with pytest.raises(ValueError, match="aware"):
        is_closable(fired, READY, WINDOW, NOW.replace(tzinfo=None))


def test_is_closable_refuses_a_naive_ready_email_time() -> None:
    # Only a fired drop-off's close reads a ready email's time.
    with pytest.raises(ValueError, match="aware"):
        is_closable(a_drop_off(state=DropOffState.FIRED), READY.replace(tzinfo=None), WINDOW, NOW + DAYS)


def test_rejected_without_its_rejection_is_reported_not_closed() -> None:
    rejected = replace(a_drop_off(state=DropOffState.REJECTED), rejection=None)
    with pytest.raises(ValueError, match="no rejection"):
        is_closable(rejected, None, WINDOW, NOW + timedelta(days=365))


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


def test_the_pickup_deadline_is_the_same_instant_in_any_zone() -> None:
    start = datetime(2026, 10, 25, 5, 30, tzinfo=UTC)
    assert pickup_deadline(start.astimezone(STUDIO_TZ), 14) == pickup_deadline(start, 14)
    assert pickup_deadline(start, 14).utcoffset() is not None


@pytest.mark.parametrize(
    ("start", "day", "end"),
    [
        # Fall back (1 Nov 2026): 00:30 CDT on Sun 25 Oct (05:30 UTC). 14 days counted in
        # UTC would end at 23:30 CST on 7 Nov, the 13th day; the window keeps all of 8 Nov.
        (datetime(2026, 10, 25, 5, 30, tzinfo=UTC), "2026-11-08", datetime(2026, 11, 9, 6, 0, tzinfo=UTC)),
        # Fall back, late in the day: 23:30 CDT on Sat 24 Oct (04:30 UTC on the 25th).
        (datetime(2026, 10, 25, 4, 30, tzinfo=UTC), "2026-11-07", datetime(2026, 11, 8, 6, 0, tzinfo=UTC)),
        # Spring forward (14 Mar 2027): 23:30 CST on Sat 6 Mar (05:30 UTC on the 7th).
        # Counted in UTC it would reach 00:30 CDT on 21 Mar, a 15th day; the window ends
        # with the 14th, 20 Mar, at midnight CDT.
        (datetime(2027, 3, 7, 5, 30, tzinfo=UTC), "2027-03-20", datetime(2027, 3, 21, 5, 0, tzinfo=UTC)),
        # Spring forward, early in the day: 00:30 CST on Sun 7 Mar (06:30 UTC).
        (datetime(2027, 3, 7, 6, 30, tzinfo=UTC), "2027-03-21", datetime(2027, 3, 22, 5, 0, tzinfo=UTC)),
    ],
)
def test_the_window_ends_with_the_austin_day_across_daylight_saving(
    start: datetime, day: str, end: datetime
) -> None:
    assert str(pickup_day(start, 14)) == day
    assert pickup_deadline(start, 14) == end
    assert pickup_deadline(start, 14).astimezone(STUDIO_TZ).time() == time(0)
    fired = a_drop_off(12, DropOffState.FIRED)
    local = start.astimezone(STUDIO_TZ)
    assert not is_closable(fired, local, 14, end - SECOND)
    assert is_closable(fired, local, 14, end)
    rejected = replace(
        a_drop_off(12, DropOffState.REJECTED), rejection=Rejection(ItemId("other"), None, STAFF, local)
    )
    assert not is_closable(rejected, None, 14, end - SECOND)
    assert is_closable(rejected, None, 14, end)


def test_the_daily_close_never_deletes_on_the_pick_up_by_day() -> None:
    # A ready email sent at 00:30 Austin, before the close's 03:17 run: the close at 03:17
    # on the pick-up-by day keeps everything; the one the next morning closes it.
    sent_at = datetime(2026, 11, 13, 0, 30, tzinfo=STUDIO_TZ)
    assert str(pickup_day(sent_at, 14)) == "2026-11-27"
    fired = a_drop_off(12, DropOffState.FIRED)
    assert not is_closable(fired, sent_at, 14, datetime(2026, 11, 27, 3, 17, tzinfo=STUDIO_TZ))
    assert not is_closable(fired, sent_at, 14, datetime(2026, 11, 27, 23, 59, 59, tzinfo=STUDIO_TZ))
    assert is_closable(fired, sent_at, 14, datetime(2026, 11, 28, 3, 17, tzinfo=STUDIO_TZ))


def test_the_pickup_deadline_needs_a_window_and_an_aware_time() -> None:
    with pytest.raises(ValueError, match="at least a day"):
        pickup_deadline(NOW, 0)
    with pytest.raises(ValueError, match="at least a day"):
        pickup_day(NOW, 0)
    with pytest.raises(ValueError, match="aware"):
        pickup_deadline(NOW.replace(tzinfo=None), 14)


def _ready(sent_at: datetime | None, window: int | None, number: int = 1) -> Email:
    email = claim(new_email(DropOffId(number), EmailKind.READY, NOW), NOW)
    if sent_at is None:
        return email
    return replace(mark_sent(email, sent_at, pickup_window_days=WINDOW), pickup_window_days=window)


def test_a_fired_drop_off_is_due_by_its_sent_ready_emails_kept_window() -> None:
    fired = a_drop_off(1, DropOffState.FIRED)
    sent = _ready(READY, WINDOW)
    # The studio's window now (1 day) is ignored: the email gave 14.
    assert not is_due_to_close(fired, sent, 1, READY_END - SECOND)
    assert is_due_to_close(fired, sent, 1, READY_END)
    # Not sent yet (or never queued): the window hasn't started.
    assert not is_due_to_close(fired, _ready(None, None), 1, NOW + timedelta(days=365))


def test_a_rejected_drop_off_is_due_by_the_studios_window() -> None:
    rejected = a_drop_off(1, DropOffState.REJECTED)
    assert not is_due_to_close(rejected, None, WINDOW, REJECTED_END - SECOND)
    assert is_due_to_close(rejected, None, WINDOW, REJECTED_END)
    assert not is_due_to_close(a_drop_off(1), None, WINDOW, NOW + timedelta(days=365))


def test_a_broken_ready_email_is_reported_not_skipped() -> None:
    fired = a_drop_off(1, DropOffState.FIRED)
    with pytest.raises(ValueError, match="no pickup window"):
        is_due_to_close(fired, _ready(READY, None), WINDOW, READY_END)
    with pytest.raises(ValueError, match="no ready email"):
        is_due_to_close(fired, None, WINDOW, READY_END)
    rejected = replace(a_drop_off(1, DropOffState.REJECTED), rejection=None)
    with pytest.raises(ValueError, match="no rejection"):
        is_due_to_close(rejected, None, WINDOW, REJECTED_END)
    with pytest.raises(ValueError, match="isn't AC-1's ready email"):
        is_due_to_close(fired, _ready(READY, WINDOW, number=2), WINDOW, READY_END)
