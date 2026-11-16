"""A load's firing record (#42): every field optional, every set one checked."""

from dataclasses import replace
from typing import cast

import pytest

from asmbly_ceramics.domain.errors import InvalidRecord
from asmbly_ceramics.domain.firing import (
    CONE_READING_RANGE,
    CONE_READING_TEXT_MAX,
    EMPTY_RECORD,
    NO_CONE,
    RECORD_FIELDS,
    WITNESS_CONES,
    FiringRecord,
    Program,
    Speed,
    changed_fields,
    is_no_cone,
    read_firing_record,
    read_program,
    record_changes,
    record_values,
)
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import COST_CENTS_MAX, FIRING_MINUTES_MAX

CONE_6 = ItemId("cone-6")
CONES = (ItemId("cone-06"), ItemId("cone-5"), CONE_6)
NAMES = {ItemId("cone-06"): "^06", ItemId("cone-5"): "^5", CONE_6: "^6"}

# The design's example record, as the form sends it.
FULL_FORM = {
    "percent_full": "85",
    "firing_number": "98",
    "all_time_number": "252",
    "preheat_hours": "0",
    "cone": "cone-6",
    "speed": "medium",
    "hold_minutes": "7",
    "firing_time": "11:38",
    "max_temp_f": "2236",
    "board_temp_f": "156",
    "cost": "8.19",
    "cone_top": "100",
    "cone_center": "100",
    "cone_bottom": "none",
}
FULL_RECORD = FiringRecord(
    percent_full=85,
    firing_number=98,
    all_time_number=252,
    program=Program(preheat_hours=0, cone=CONE_6, speed=Speed.MEDIUM, hold_minutes=7),
    firing_minutes=11 * 60 + 38,
    max_temp_f=2236,
    board_temp_f=156,
    cost_cents=819,
    cone_top=100,
    cone_center=100,
    cone_bottom=NO_CONE,
)


def refused(values: dict[str, str]) -> dict[str, str]:
    with pytest.raises(InvalidRecord) as caught:
        read_firing_record(values, CONES)
    return dict(caught.value.errors)


def test_blank_form_is_an_empty_record() -> None:
    assert read_firing_record({}, CONES) == EMPTY_RECORD
    assert read_firing_record(dict.fromkeys(RECORD_FIELDS, "  "), CONES) == EMPTY_RECORD
    assert read_firing_record(dict.fromkeys(RECORD_FIELDS, ""), ()) == EMPTY_RECORD


def test_reads_a_full_record() -> None:
    assert read_firing_record(FULL_FORM, CONES) == FULL_RECORD
    padded = {field: f"  {value} " for field, value in FULL_FORM.items()}
    assert read_firing_record(padded, CONES) == FULL_RECORD


@pytest.mark.parametrize(
    ("cost", "cents"),
    [("8", 800), ("8.1", 810), ("8.19", 819), ("$8.19", 819), ("0", 0), ("100", 10_000), ("100.00", 10_000)],
)
def test_reads_cost_as_cents(cost: str, cents: int) -> None:
    assert read_firing_record({"cost": cost}, ()).cost_cents == cents


@pytest.mark.parametrize(("text", "minutes"), [("0:00", 0), ("1:05", 65), ("11:38", 698), ("72:00", 4320)])
def test_reads_firing_time_as_minutes(text: str, minutes: int) -> None:
    assert read_firing_record({"firing_time": text}, ()).firing_minutes == minutes


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("percent_full", "-1"),
        ("percent_full", "101"),
        ("max_temp_f", "2501"),
        ("board_temp_f", "401"),
        ("cost", "100.01"),
        ("preheat_hours", "49"),
        ("hold_minutes", "601"),
        ("firing_time", "72:01"),
        ("firing_number", "0"),
        ("firing_number", "100001"),
        ("all_time_number", "0"),
        ("all_time_number", "100001"),
        ("cone_top", "101"),
        ("cone_center", "-5"),
    ],
)
def test_refuses_out_of_range_numbers(field: str, value: str) -> None:
    assert list(refused({field: value})) == [field]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("percent_full", "abc"),
        ("max_temp_f", "1.5"),
        ("max_temp_f", "2,236"),
        ("percent_full", "٨٥"),  # Arabic-Indic digits: int() reads them, the form doesn't
        ("firing_time", "11:60"),
        ("firing_time", "11"),
        ("firing_time", "1:5"),
        ("firing_time", "111:00"),
        ("cost", "8.199"),
        ("cost", "$"),
        ("cost", "1000"),
        ("cone_bottom", "half"),
        ("max_temp_f", "9" * 5000),  # refused before int(), which refuses over 4,300 digits
        ("firing_time", "1" * 5000 + ":00"),
        ("cost", "1" * 5000),
    ],
)
def test_refuses_non_numbers(field: str, value: str) -> None:
    assert list(refused({field: value})) == [field]


def test_each_limits_maximum_reads_back() -> None:
    hours, minutes = divmod(FIRING_MINUTES_MAX, 60)
    dollars, cents = divmod(COST_CENTS_MAX, 100)
    at_most = {"firing_time": f"{hours}:{minutes:02d}", "cost": f"${dollars}.{cents:02d}"}
    record = read_firing_record(at_most, CONES)
    assert (record.firing_minutes, record.cost_cents) == (FIRING_MINUTES_MAX, COST_CENTS_MAX)
    over_hours, over_minutes = divmod(FIRING_MINUTES_MAX + 1, 60)
    over_dollars, over_cents = divmod(COST_CENTS_MAX + 1, 100)
    over = {"firing_time": f"{over_hours}:{over_minutes:02d}", "cost": f"${over_dollars}.{over_cents:02d}"}
    assert list(refused(over)) == ["firing_time", "cost"]


def test_non_text_field_reads_as_blank() -> None:
    sent = cast("dict[str, str]", {"max_temp_f": 2236, "cost": None, "cone_top": ["100"]})
    assert read_firing_record(sent, CONES) == EMPTY_RECORD


def test_reports_every_refused_field_at_once() -> None:
    errors = refused({**FULL_FORM, "percent_full": "101", "speed": "warp", "cost": "lots", "cone": "^7"})
    assert list(errors) == ["percent_full", "cone", "speed", "cost"]  # in the page's order
    assert errors["percent_full"] == "Enter a whole number from 0 to 100."
    assert errors["cost"] == "Enter the cost in dollars, like 8.19, up to $100.00."


def test_unknown_cone_and_speed_refused() -> None:
    assert refused({"cone": "cone-10", "speed": "turbo"}) == {
        "cone": "Pick a cone from the list.",
        "speed": "Pick slow, medium or fast.",
    }
    program = read_firing_record({"cone": " cone-6 ", "speed": "SLOW"}, CONES).program
    assert (program.cone, program.speed) == (CONE_6, Speed.SLOW)
    # Until phase 2 passes the studio's cones, no cone is accepted.
    with pytest.raises(InvalidRecord):
        read_firing_record({"cone": "cone-6"}, ())


def test_error_messages_never_quote_the_value() -> None:
    sent = {field: f"9{field}X7" for field in RECORD_FIELDS}
    with pytest.raises(InvalidRecord) as caught:
        read_firing_record(sent, CONES)
    assert set(caught.value.errors) == set(RECORD_FIELDS)
    for field, message in caught.value.errors.items():
        assert sent[field] not in message
        assert sent[field] not in caught.value.message
    assert caught.value.errors["max_temp_f"] == "Enter a whole number from 0 to 2,500."


def test_record_changes_lists_each_changed_field() -> None:
    assert record_changes(EMPTY_RECORD, FULL_RECORD, NAMES.__getitem__) == (
        "% full: 85%",
        "Firing number: 98",
        "All-time number: 252",
        "Preheat: 0 h",
        "Cone: ^6",
        "Speed: medium",
        "Hold: 7 min",
        "Firing time: 11:38",
        "Max temp: 2,236 °F",
        "Board temp: 156 °F",
        "Cost: $8.19",
        "Top cone: 100%",
        "Center cone: 100%",
        "Bottom cone: no cone",
    )
    bigger = replace(FULL_RECORD, all_time_number=1252, cost_cents=5)
    assert record_changes(FULL_RECORD, bigger, NAMES.__getitem__) == ("All-time number: 1,252", "Cost: $0.05")


def test_record_changes_cleared_field() -> None:
    cleared = replace(FULL_RECORD, firing_minutes=None, program=replace(FULL_RECORD.program, speed=None))
    assert record_changes(FULL_RECORD, cleared, NAMES.__getitem__) == (
        "Speed: cleared",
        "Firing time: cleared",
    )


def test_record_changes_nothing_changed_is_empty() -> None:
    assert record_changes(FULL_RECORD, FULL_RECORD, NAMES.__getitem__) == ()
    assert record_changes(EMPTY_RECORD, EMPTY_RECORD, NAMES.__getitem__) == ()


# read_program: a firing type's default program (#42)


def test_read_program_reads_the_four_fields() -> None:
    form = {"preheat_hours": " 8 ", "cone": "cone-06", "speed": "Slow", "hold_minutes": "0", "cost": "x"}
    assert read_program(form, CONES) == Program(
        preheat_hours=8, cone=ItemId("cone-06"), speed=Speed.SLOW, hold_minutes=0
    )
    assert read_program({}, CONES) == Program()


def test_read_program_refuses_every_bad_field_at_once() -> None:
    form = {"preheat_hours": "49", "cone": "cone-9", "speed": "warp", "hold_minutes": "601"}
    with pytest.raises(InvalidRecord) as refused:
        read_program(form, CONES)
    assert list(refused.value.errors) == ["preheat_hours", "cone", "speed", "hold_minutes"]


def test_read_firing_record_reports_program_and_other_fields_together() -> None:
    with pytest.raises(InvalidRecord) as refused:
        read_firing_record({"percent_full": "101", "cone": "cone-9", "cost": "200"}, CONES)
    assert list(refused.value.errors) == ["percent_full", "cone", "cost"]


def test_record_values_shows_the_record_as_the_form_sends_it() -> None:
    assert record_values(FULL_RECORD) == FULL_FORM | {"max_temp_f": "2236"}
    assert record_values(EMPTY_RECORD) == dict.fromkeys(RECORD_FIELDS, "")
    short = replace(FULL_RECORD, firing_minutes=65, cost_cents=5, cone_top=0)
    assert {k: record_values(short)[k] for k in ("firing_time", "cost", "cone_top")} == {
        "firing_time": "1:05",
        "cost": "0.05",
        "cone_top": "0",
    }


def test_record_values_reads_back_to_the_same_record() -> None:
    maxed = replace(FULL_RECORD, firing_minutes=FIRING_MINUTES_MAX, cost_cents=COST_CENTS_MAX)
    for record in (FULL_RECORD, EMPTY_RECORD, maxed):
        assert read_firing_record(record_values(record), CONES) == record


def test_changed_fields_names_only_what_changed_in_page_order() -> None:
    new = replace(FULL_RECORD, cost_cents=None, percent_full=90, program=Program())
    assert changed_fields(FULL_RECORD, new) == (
        "percent_full",
        "preheat_hours",
        "cone",
        "speed",
        "hold_minutes",
        "cost",
    )
    assert changed_fields(FULL_RECORD, FULL_RECORD) == ()


def test_witness_cones_are_record_fields_read_in_their_range() -> None:
    assert set(WITNESS_CONES) <= set(RECORD_FIELDS)
    low, high = CONE_READING_RANGE
    assert len(str(high)) == CONE_READING_TEXT_MAX
    for name in WITNESS_CONES:
        record = read_firing_record({name: str(high)}, CONES)
        assert getattr(record, name) == high
        assert getattr(read_firing_record({name: str(low)}, CONES), name) == low
        with pytest.raises(InvalidRecord):
            read_firing_record({name: str(high + 1)}, CONES)
        assert getattr(read_firing_record({name: "None"}, CONES), name) is NO_CONE
    assert is_no_cone(" NONE ")
    assert not is_no_cone("0")
