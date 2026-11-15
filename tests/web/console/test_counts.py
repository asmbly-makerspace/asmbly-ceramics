"""Weekly counts (#7): Monday to Sunday in Austin time, by firing type, kiln and reason,
and the overdue drop-offs first."""

import html
import re
from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.use_cases.reject import RejectRequest
from tests.use_cases.flows import STAFF_MEMBER, fired
from tests.web.console.conftest import Console

COUNTS = "/console/counts"


@pytest.fixture
def staff(console: Console) -> Console:
    console.sign_in()
    return console


def text(answer: httpx2.Response) -> str:
    """The page's words, tags dropped (headings marked), spaces collapsed."""
    marked = answer.text.replace("<h3>", " §h3 ")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", marked)).split())


def at(console: Console, when: datetime) -> None:
    console.world.clock.advance(when - console.world.clock.now())


def section(page: str, heading: str) -> str:
    return page.split(heading, 1)[1].split("§h3", 1)[0]


def test_counts_by_firing_type_kiln_and_reason_for_one_week(staff: Console) -> None:
    world = staff.world
    one = staff.drop_off(1)
    staff.drop_off(2, firing_type="glaze", glaze_type="house-dip-glaze")
    three = staff.drop_off(3)
    fired(world, one)  # in Athena
    world.reject(RejectRequest(three, ItemId("has-glaze-issues"), "", version=1, staff=STAFF_MEMBER))

    answer = staff.get(COUNTS)

    assert answer.status_code == 200
    assert 'aria-current="page">Weekly counts' in answer.text
    page = text(answer)
    assert "Mon Nov 9 to Sun Nov 15" in page
    received = section(page, "Drop-offs received")
    assert "Bisque 2 6" in received  # two drop-offs, three pieces each
    assert "Glaze 1 3" in received
    assert "Total 3 9" in received
    assert "Athena: 1" in section(page, "Loads fired, by kiln")
    assert "Has glaze issues: 1" in section(page, "Rejections, by reason")
    assert "Its ID, dates, firing type, pieces, load and reason are kept for these counts." in page


def test_the_week_runs_monday_to_sunday_in_austin_time(staff: Console) -> None:
    # 23:30 on Sunday 15 November in Austin is 05:30 on Monday in UTC.
    at(staff, datetime(2026, 11, 16, 5, 30, tzinfo=UTC))
    staff.drop_off(1)

    this_week = text(staff.get(f"{COUNTS}?week=2026-11-09"))
    next_week = text(staff.get(f"{COUNTS}?week=2026-11-16"))

    assert "Bisque 1 3" in section(this_week, "Drop-offs received")
    assert "No drop-offs this week." in next_week


@pytest.mark.parametrize(
    ("sunday_night", "week", "following"),
    [
        # Clocks went back at 2 AM on Sunday 1 November 2026: CST, UTC-6, that night.
        (datetime(2026, 11, 2, 5, 30, tzinfo=UTC), "2026-10-26", "2026-11-02"),
        # Clocks go forward at 2 AM on Sunday 14 March 2027: CDT, UTC-5, that night.
        (datetime(2027, 3, 15, 4, 30, tzinfo=UTC), "2027-03-08", "2027-03-15"),
    ],
)
def test_a_week_across_the_daylight_saving_change(
    staff: Console, sunday_night: datetime, week: str, following: str
) -> None:
    at(staff, sunday_night)  # 23:30 on the Sunday, Austin time
    staff.drop_off(1)
    at(staff, sunday_night + timedelta(hours=1))  # 00:30 on the Monday
    staff.drop_off(2, firing_type="glaze", glaze_type="house-dip-glaze")

    assert "Bisque 1 3" in section(text(staff.get(f"{COUNTS}?week={week}")), "Drop-offs received")
    assert "Glaze" not in section(text(staff.get(f"{COUNTS}?week={week}")), "Drop-offs received")
    assert "Glaze 1 3" in section(text(staff.get(f"{COUNTS}?week={following}")), "Drop-offs received")


def test_overdue_drop_offs_are_listed_first(staff: Console) -> None:
    old = staff.drop_off(1)
    at(staff, staff.world.clock.now() + timedelta(days=61))
    staff.drop_off(2)

    page = text(staff.get(COUNTS))

    overdue = page.split("Overdue: waiting 60 days or more", 1)[1].split("Drop-offs received", 1)[0]
    assert f"{old} " in overdue
    assert "61" in overdue
    assert "AC-2" not in overdue
    assert page.index("Overdue") < page.index("Drop-offs received")
    assert staff.world.records.drop_off(DropOffId(1)) is not None  # shown, never deleted


def test_a_week_that_isnt_a_monday_shows_its_monday(staff: Console) -> None:
    assert "Mon Nov 9 to Sun Nov 15" in text(staff.get(f"{COUNTS}?week=2026-11-12"))
    assert "Mon Nov 9 to Sun Nov 15" in text(staff.get(f"{COUNTS}?week=not-a-date"))
    assert "Mon Nov 9 to Sun Nov 15" in text(staff.get(f"{COUNTS}?week=2026-02-30"))
    for edge in ("0001-01-01", "9999-12-31"):  # the calendar's edges: no week before or after
        answer = staff.get(f"{COUNTS}?week={edge}")
        assert answer.status_code == 200
        assert "Mon Nov 9 to Sun Nov 15" in text(answer)
    page = staff.get(f"{COUNTS}?week=2026-11-12").text
    assert 'href="/console/counts?week=2026-11-02"' in page
    assert 'href="/console/counts?week=2026-11-16"' in page


def test_markup_in_an_overdue_name_is_escaped(staff: Console) -> None:
    staff.drop_off(1, name='Robin "><script>x()</script>')
    at(staff, staff.world.clock.now() + timedelta(days=61))
    answer = staff.get(COUNTS)
    assert "<script>" not in answer.text
    assert "&lt;script&gt;" in answer.text
