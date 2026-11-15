"""The waiting list and the search box (#3), through the console's pages on the fakes."""

import re
from datetime import timedelta
from urllib.parse import quote

import pytest

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import OVERDUE_AFTER
from tests.web.console.conftest import Console

MARKUP = "<script>alert(1)</script>"


def ids_in(html: str) -> list[str]:
    return re.findall(r'<td class="mono">(AC-\d+)</td>', html)


@pytest.fixture
def signed_in(console: Console) -> Console:
    console.sign_in()
    return console


def test_waiting_drop_offs_are_listed_oldest_first_with_days_waiting(signed_in: Console) -> None:
    console = signed_in
    first = console.drop_off(1, name="Wren Okafor")
    console.world.clock.advance(timedelta(days=3))
    second = console.drop_off(2, name="Juno Marsh")
    console.world.clock.advance(timedelta(days=1))
    third = console.drop_off(3)
    page = console.get("/console")
    assert page.status_code == 200
    assert ids_in(page.text) == [str(first), str(second), str(third)]
    for text in (
        "Waiting to fire",
        "Oldest first.",
        "Wren Okafor",
        "4 days",
        "1 day",
        "today",
        "Waiting (3)",
    ):
        assert text in page.text, text
    assert f'src="/console/drop-offs/{first}/photos/1/thumb" alt="Photo of {first}"' in page.text
    assert 'loading="lazy"' in page.text
    assert f'href="/console/drop-offs/{first}"' in page.text


def test_bisque_and_glaze_are_totalled_in_pieces_with_glaze_types_split(signed_in: Console) -> None:
    console = signed_in
    console.drop_off(1)  # 3 pieces each
    console.drop_off(2, firing_type="glaze", glaze_type="house-dip-glaze")
    console.drop_off(3, firing_type="glaze", glaze_type="house-dip-glaze")
    console.drop_off(4, firing_type="glaze", glaze_type="commercial-glaze")
    text = console.get("/console").text
    bisque, glaze = text.split("<h3>Bisque</h3>")[1], text.split("<h3>Glaze</h3>")[1]
    assert "3 pieces" in bisque.split("</section>")[0]
    assert "in 1 drop-offs" in bisque.split("</section>")[0]
    glaze_card = glaze.split("</section>")[0]
    assert "9 pieces" in glaze_card
    assert "6 House dip glaze, 3 Commercial glaze" in glaze_card


def test_overdue_drop_offs_are_counted_and_tagged_at_60_days(signed_in: Console) -> None:
    console = signed_in
    console.drop_off(1)
    console.world.clock.advance(timedelta(days=1))
    console.drop_off(2)
    console.world.clock.advance(OVERDUE_AFTER - timedelta(days=1))
    text = console.get("/console").text
    overdue = text.split("<h3>Overdue</h3>")[1].split("</section>")[0]
    assert '<p class="card-number">1</p>' in overdue
    assert text.count('<span class="tag tag-overdue">overdue</span>') == 1
    assert f"{OVERDUE_AFTER.days} days" in text


@pytest.mark.parametrize("query", ["AC-12", "ac12", "ac-12", "12", " 12 "])
def test_search_finds_by_id(signed_in: Console, query: str) -> None:
    console = signed_in
    for n in range(1, 13):
        console.drop_off(n)
    page = console.post("/console/search", {"q": query})
    assert page.status_code == 200
    assert ids_in(page.text) == ["AC-12"]


def test_search_finds_by_any_part_of_the_name(signed_in: Console) -> None:
    console = signed_in
    console.drop_off(1, name="Wren Okafor")
    console.drop_off(2, name="Juno Marsh")
    page = console.post("/console/search", {"q": "OKAF"})
    assert ids_in(page.text) == ["AC-1"]
    assert "Found for “OKAF”" in page.text


def test_a_search_with_no_match_says_so(signed_in: Console) -> None:
    signed_in.drop_off(1)
    page = signed_in.post("/console/search", {"q": "Nobody At All"})
    assert "No drop-offs match that. Check the ID, or try part of the name." in page.text
    assert ids_in(page.text) == []


def test_the_firing_filter_shows_one_firing_type(signed_in: Console) -> None:
    console = signed_in
    console.drop_off(1)
    console.drop_off(2, firing_type="glaze", glaze_type="house-dip-glaze")
    page = console.get("/console?firing=glaze")
    assert ids_in(page.text) == ["AC-2"]
    assert 'href="/console?firing=glaze" aria-current="true"' in page.text
    assert ids_in(console.get("/console?firing=%3Cnot-an-id%3E").text) == ["AC-1", "AC-2"]


def test_markup_in_a_name_is_shown_escaped(signed_in: Console) -> None:
    signed_in.drop_off(1, name=MARKUP)
    for page in (signed_in.get("/console"), signed_in.post("/console/search", {"q": MARKUP})):
        assert "<script>alert" not in page.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_a_very_long_search_is_cut_not_refused(signed_in: Console) -> None:
    page = signed_in.post("/console/search", {"q": "x" * 500})
    assert page.status_code == 200
    assert "x" * 100 in page.text
    assert "x" * 101 not in page.text


def test_search_is_a_post_and_the_text_never_reaches_a_url(signed_in: Console) -> None:
    console = signed_in
    console.drop_off(1, name="Wren Okafor")
    console.drop_off(2, name="Juno Marsh")
    page = console.get("/console")
    assert '<form method="post" action="/console/search"' in page.text
    assert 'autocomplete="off"' in page.text
    plain = console.get("/console?q=Okafor")
    assert ids_in(plain.text) == ["AC-1", "AC-2"]  # `q` in a URL is ignored
    found = console.post("/console/search", {"q": "Okafor"})
    assert "location" not in found.headers
    assert not re.search(r'href="[^"]*Okafor', found.text)
    assert quote("Okafor") not in str(found.url.query)


def test_a_search_without_the_csrf_token_is_refused(signed_in: Console) -> None:
    page = signed_in.post("/console/search", {"q": "12"}, csrf=False)
    assert page.status_code == 403
    assert "This form has expired. Go back, reload the page and try again." in page.text


def test_an_empty_waiting_list_says_so(signed_in: Console) -> None:
    assert "Nothing is waiting to fire." in signed_in.get("/console").text


def test_search_finds_a_rejected_drop_off_and_its_page_offers_undo(signed_in: Console) -> None:
    console = signed_in
    console.drop_off(1, name="Wren Okafor")
    fields = {"reason": "other", "message": "Made-up message.", "version": console.version(DropOffId(1))}
    assert console.post("/console/drop-offs/AC-1/reject", fields).status_code == 303
    found = console.post("/console/search", {"q": "okafor"})
    assert ids_in(found.text) == ["AC-1"]
    assert "rejected" in found.text
    assert "today" not in found.text  # not waiting: its state, not its days waiting
    assert "Undo rejection" in console.get("/console/drop-offs/AC-1").text


def test_search_by_id_shows_a_closed_drop_off_without_a_name_or_photo(signed_in: Console) -> None:
    from tests.use_cases.flows import fired, send_all

    console = signed_in
    console.drop_off(1, name="Wren Okafor")
    fired(console.world, DropOffId(1))
    send_all(console.world)
    console.world.clock.advance(timedelta(days=60))
    console.world.close()
    found = console.post("/console/search", {"q": "AC-1"})
    assert ids_in(found.text) == ["AC-1"]
    assert "closed" in found.text
    assert "Wren Okafor" not in found.text
    assert "/photos/1/thumb" not in found.text


def test_an_empty_search_shows_the_plain_list(signed_in: Console) -> None:
    signed_in.drop_off(1)
    page = signed_in.post("/console/search", {"q": "  "})
    assert ids_in(page.text) == ["AC-1"]
    assert "Found for" not in page.text


def test_a_filter_with_nothing_says_so(signed_in: Console) -> None:
    signed_in.drop_off(1)
    assert "No waiting drop-offs of this firing type." in signed_in.get("/console?firing=glaze").text
