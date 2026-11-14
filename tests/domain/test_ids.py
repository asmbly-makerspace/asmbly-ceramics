import pytest

from asmbly_ceramics.domain.ids import (
    ITEM_ID_MAX,
    DropOffId,
    ItemId,
    LoadId,
    is_drop_off_id,
    is_item_id,
    is_load_id,
    new_item_id,
)


def test_drop_off_id_formats_and_parses() -> None:
    assert str(DropOffId(1)) == "AC-1"
    assert str(DropOffId(12)) == "AC-12"
    assert DropOffId.parse("AC-12") == DropOffId(12)
    assert DropOffId(2) < DropOffId(10)


@pytest.mark.parametrize(
    "text",
    [
        "AC-0",
        "AC-",
        "ac-12",
        "ac-12x",
        "AC-012",
        " AC-12",
        "AC-12\n",
        "AC-١٢",
        "L-4",
        "AC-1" + "0" * 12,
        "AC-" + "9" * 4000,
    ],
)
def test_drop_off_id_parse_refuses_anything_else(text: str) -> None:
    with pytest.raises(ValueError, match="not a AC- ID"):
        DropOffId.parse(text)


def test_an_id_of_twelve_digits_parses() -> None:
    assert DropOffId.parse("AC-" + "9" * 12) == DropOffId(999_999_999_999)
    assert LoadId.parse("L-" + "9" * 12) == LoadId(999_999_999_999)


def test_load_id_formats_and_parses() -> None:
    assert str(LoadId(4)) == "L-4"
    assert LoadId.parse("L-4") == LoadId(4)


@pytest.mark.parametrize(
    "text", ["L-0", "L-", "l-4", "L-04", "AC-4", "L-4 ", "L-1" + "0" * 12, "L-" + "9" * 4000]
)
def test_load_id_parse_refuses_anything_else(text: str) -> None:
    with pytest.raises(ValueError, match="not a L- ID"):
        LoadId.parse(text)


@pytest.mark.parametrize("number", [0, -1, True])
def test_an_id_number_starts_at_one(number: int) -> None:
    with pytest.raises(ValueError, match="from 1"):
        DropOffId(number)
    with pytest.raises(ValueError, match="from 1"):
        LoadId(number)


def test_new_item_id_makes_a_unique_slug() -> None:
    assert new_item_id("Commercial glaze", []) == "commercial-glaze"
    assert new_item_id("  Cone 6 / Oxidation!! ", []) == "cone-6-oxidation"
    assert new_item_id("***", []) == "item"
    taken = [ItemId("helios"), ItemId("helios-2")]
    assert new_item_id("Helios", taken) == "helios-3"


def test_new_item_id_stays_within_40_characters() -> None:
    long_name = "a" * 39 + " b" * 5
    first = new_item_id(long_name, [])
    assert first == "a" * 39
    second = new_item_id(long_name, [first])
    assert second == "a" * 38 + "-2"
    assert len(second) <= ITEM_ID_MAX
    taken = [first, *(ItemId("a" * 38 + f"-{n}") for n in range(2, 10))]
    assert new_item_id(long_name, taken) == "a" * 37 + "-10"


def test_a_name_without_a_letter_gets_a_slug_with_one() -> None:
    assert new_item_id("06", []) == "item-06"
    assert new_item_id("06", [ItemId("item-06")]) == "item-06-2"
    assert new_item_id("1" * 50, []) == "item-" + "1" * 35
    # Cutting for the suffix can't drop the only letter either.
    tail_letter = "1" * 39 + "a"
    assert new_item_id(tail_letter, []) == tail_letter
    second = new_item_id(tail_letter, [ItemId(tail_letter)])
    assert second == "item-" + "1" * 33 + "-2"
    assert is_item_id(second)


@pytest.mark.parametrize("name", ["06", "Commercial glaze", "***", "1" * 60, "a" * 39 + " b" * 5, "-7-"])
def test_every_new_item_id_has_the_item_id_shape(name: str) -> None:
    first = new_item_id(name, [])
    assert is_item_id(first)
    assert is_item_id(new_item_id(name, [first]))


def test_is_item_id() -> None:
    assert is_item_id("cone-6")
    assert is_item_id("a" * ITEM_ID_MAX)
    for text in ["06", "512-555-01", "", "a" * (ITEM_ID_MAX + 1), "Cone", "cone_6", 6]:
        assert not is_item_id(text)


def test_is_drop_off_id_and_is_load_id_agree_with_parse() -> None:
    assert is_drop_off_id(str(DropOffId(12)))
    assert is_load_id(str(LoadId(4)))
    for text in ["ac-12", "AC-012", "AC-0", "L-4", " AC-12", "AC-" + "1" * 13, 12]:
        assert not is_drop_off_id(text)
    for text in ["l-4", "L-04", "AC-12", "L-" + "1" * 13, 4]:
        assert not is_load_id(text)
