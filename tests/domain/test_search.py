import unicodedata
from dataclasses import replace

import pytest

from asmbly_ceramics.domain.dropoff import Contact, DropOff, DropOffState
from asmbly_ceramics.domain.ids import ID_DIGITS_MAX, DropOffId
from asmbly_ceramics.domain.search import QUERY_MAX, Query, fold, matches, parse_query
from tests.domain.builders import TEST_EMAIL, TEST_NAME, TEST_PHONE, TEST_PHONE_DIGITS, a_drop_off


def named(name: str, number: int = 1) -> DropOff:
    return replace(a_drop_off(number), contact=Contact(name, TEST_EMAIL, TEST_PHONE_DIGITS))


@pytest.mark.parametrize(
    "raw", ["AC-12", "ac12", "ac 12", "12", " AC-12 ", "Ac-12", "ac-012", "-12", "AC  12"]
)
def test_search_parses_every_id_form(raw: str) -> None:
    assert parse_query(raw) == Query(id=DropOffId(12), text="")


@pytest.mark.parametrize("raw", ["AC12x", "AC--12", "12 13", "L-12", "ac", "\u0661\u0662", "AC-\uff11\uff12"])
def test_other_text_is_a_name_search(raw: str) -> None:
    query = parse_query(raw)
    assert query.id is None
    assert query.text == fold(raw)


@pytest.mark.parametrize("raw", ["0", "AC-0", "ac0", "000", "ac-000", "1" * (ID_DIGITS_MAX + 1)])
def test_an_id_form_that_cant_be_an_id_matches_nothing(raw: str) -> None:
    # Not text either: "0" is no one's name, and a use case never builds DropOffId(0).
    query = parse_query(raw)
    assert query == Query(id=None, text="")
    assert not matches(a_drop_off(1), query)
    assert not matches(named("0 000"), query)


def test_the_longest_id_is_read() -> None:
    longest = "9" * ID_DIGITS_MAX
    assert parse_query("AC-" + longest).id == DropOffId(int(longest))
    assert parse_query("ac-00" + longest).id == DropOffId(int(longest))  # leading zeros aren't digits


def test_search_finds_a_drop_off_by_number() -> None:
    assert matches(a_drop_off(12), parse_query("ac12"))
    assert not matches(a_drop_off(120), parse_query("12"))
    assert not matches(a_drop_off(1), parse_query("AC-0"))


def test_search_matches_any_part_of_the_name_case_insensitively() -> None:
    drop_off = named(TEST_NAME)  # "Test Person"
    for raw in ("test person", "PERSON", "st pe", "t", "  Test   Person "):
        assert matches(drop_off, parse_query(raw)), raw
    assert not matches(drop_off, parse_query("Persons"))
    # A number query searches IDs only, never the name.
    assert not matches(named("Test Person 12", number=3), parse_query("12"))


def test_name_search_ignores_email_and_phone() -> None:
    drop_off = named(TEST_NAME)
    assert drop_off.contact is not None
    for raw in (TEST_EMAIL, TEST_EMAIL.split("@")[0], "example.org", TEST_PHONE, "+1" + TEST_PHONE_DIGITS):
        assert parse_query(raw).id is None  # each is a name search, not an ID
        assert not matches(drop_off, parse_query(raw)), "a contact field matched"


def test_search_folds_nfc_and_case_on_both_sides() -> None:
    composed, decomposed = "José Example", "José Example"
    assert matches(named(decomposed), parse_query("josé"))
    assert matches(named(composed), parse_query("JOSÉ"))
    assert matches(named("Straße Example"), parse_query("STRASSE"))  # casefold, not lower
    assert fold("  A\tB\n c ") == "a b c"


def test_fold_applies_nfc_again_after_casefolding() -> None:
    # Casefolding the composed "ΐ" gives a decomposed sequence; only the second NFC
    # composes it again, so a stored name and a typed query fold to the same text.
    assert unicodedata.normalize("NFC", "ΐ".casefold()) != "ΐ".casefold()
    assert fold("ΐ") == unicodedata.normalize("NFC", "ΐ".casefold())
    assert fold("ΐ") == fold("\u03b9\u0308\u0301")
    assert matches(named("Test Παΐσιος"), parse_query("ΠΑΐΣΙΟΣ"))


def test_fold_drops_format_characters_as_names_do() -> None:
    # DropOffDetails.create drops format characters (category Cf) from a name; a query
    # pasted with one, or a name stored before that rule, still matches.
    for hidden in ("\u200b", "\u200d", "\u2060", "\ufeff", "\u00ad"):
        assert unicodedata.category(hidden) == "Cf"
        assert fold(f"Te{hidden}st") == "test"
        assert matches(named(TEST_NAME), parse_query(f"Per{hidden}son"))
        assert matches(named(f"Test Per{hidden}son"), parse_query("person"))
    assert parse_query("AC-\u200b12").id == DropOffId(12)
    # A format character between a letter and its combining accent still lets them compose.
    assert fold("Jose\u200d\u0301") == fold("Jos\u00e9")
    assert matches(named("Test Jos\u00e9"), parse_query("jose\u200b\u0301"))


def test_a_closed_drop_off_matches_by_number_only() -> None:
    closed = a_drop_off(9, DropOffState.CLOSED)
    assert closed.contact is None
    assert matches(closed, parse_query("AC-9"))
    assert not matches(closed, parse_query("test"))


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_an_empty_query_matches_nothing(raw: str) -> None:
    query = parse_query(raw)
    assert query == Query(id=None, text="")
    assert not matches(named(TEST_NAME), query)


def test_a_long_query_is_cut_to_100() -> None:
    assert QUERY_MAX == 100
    query = parse_query("a" * 99 + "bc")
    assert query.text == "a" * 99 + "b"
    # A number past the 100th character is not read as part of it.
    assert parse_query("1" * 100 + "2") == Query(id=None, text="")  # 100 digits: no ID


def test_a_query_repr_holds_no_text() -> None:
    query = parse_query(TEST_NAME)
    assert query.text == "test person"
    assert "test" not in repr(query).casefold()
    assert repr(query) == "Query(id=None)"
