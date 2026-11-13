from datetime import datetime, timedelta

import pytest

from asmbly_ceramics.domain import errors
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import EMAIL_MAX, HOURS_TEXT_MAX, ITEM_NAME_MAX
from asmbly_ceramics.domain.studio import (
    CatalogList,
    ItemStatus,
    SettingChange,
    Studio,
    add_item,
    change_email_settings,
    check_sending_address,
    delete_item,
    is_valid_email,
    restore_item,
    retire_item,
    starting_studio,
)
from tests.domain.builders import NOW, STAFF, a_sending_address, a_studio, an_address

LATER = NOW + timedelta(hours=1)


def names(studio: Studio, which: CatalogList) -> list[str]:
    return [item.name for item in studio.items(which)]


def active_names(studio: Studio, which: CatalogList) -> list[str]:
    return [item.name for item in studio.items(which) if item.status is ItemStatus.ACTIVE]


# The sending address and email checks


@pytest.mark.parametrize(
    "address",
    [
        an_address("kilnops"),  # another domain
        an_address("kilnops", "mail.asmbly.org"),  # a subdomain
        an_address("kilnops", "asmbly.org.example.org"),
        "kilnops.asmbly.org",  # no @
        an_address("kiln@ops", "asmbly.org"),  # two @
        an_address("", "asmbly.org"),
        an_address("kiln ops", "asmbly.org"),
        "",
    ],
)
def test_sending_address_must_be_at_asmbly_org(address: str) -> None:
    with pytest.raises(errors.SendingAddressOutsideAsmbly, match=r"Use an address at asmbly\.org\."):
        check_sending_address(address)


def test_sending_address_is_stripped_and_its_domain_lowercased() -> None:
    assert check_sending_address("  " + an_address("KilnOps", "Asmbly.ORG") + " ") == an_address(
        "KilnOps", "asmbly.org"
    )


# 64 + "@" + 189 = EMAIL_MAX, with every label within 63.
LONGEST_DOMAIN = "b" * 63 + "." + "b" * 63 + "." + "b" * (EMAIL_MAX - 64 - 1 - 63 - 63 - 6) + ".org"


@pytest.mark.parametrize(
    ("address", "valid"),
    [
        (an_address("someone"), True),
        (an_address("first.last+kiln"), True),
        (an_address("someone", "mail.example.org"), True),
        (an_address("someone", "example"), False),
        (an_address("someone", "-example.org"), False),
        (an_address("someone", "example-.org"), False),
        (an_address("someone", "example..org"), False),
        (an_address("some\tone"), False),
        (an_address("some\x00one"), False),
        (an_address("søren"), False),
        (an_address("some,one"), False),
        (an_address("<someone>"), False),
        (an_address('"some one"'), False),
        (an_address(".someone"), False),
        (an_address("some..one"), False),
        (an_address("someone\n"), False),
        (an_address("someone", "exa_mple.org"), False),
        (an_address("a" * 64), True),
        (an_address("a" * 65), False),
        (an_address("someone", "a" * 63 + ".org"), True),
        (an_address("someone", "a" * 64 + ".org"), False),
        (an_address("a" * 64, LONGEST_DOMAIN), True),
        (an_address("a" * 64, LONGEST_DOMAIN.replace(".org", "b.org")), False),
    ],
)
def test_is_valid_email(address: str, valid: bool) -> None:
    assert is_valid_email(address) is valid


# The starting settings


def test_starting_studio_has_the_decided_values() -> None:
    studio, _ = starting_studio(a_sending_address(), NOW)
    assert studio.sending_address == a_sending_address()
    assert studio.pickup_window_days == 14
    assert "5am to 2am" in studio.pickup_hours_text
    assert "Steward on Duty (SOD)" in studio.pickup_hours_text
    assert names(studio, CatalogList.KILNS) == ["Athena", "Helios", "Vulcan"]
    assert names(studio, CatalogList.FIRING_TYPES) == ["Bisque", "Glaze"]
    assert [item.needs_glaze_type for item in studio.firing_types] == [False, True]
    assert names(studio, CatalogList.GLAZE_TYPES) == ["House dip glaze", "Commercial glaze"]
    assert names(studio, CatalogList.REASONS) == ["Has glaze issues", "Needs more time to dry", "Other"]
    assert [item.needs_message for item in studio.reasons] == [False, False, True]
    assert [item.id for item in studio.glaze_types] == ["house-dip-glaze", "commercial-glaze"]
    assert studio.version == 0
    assert all(item.status is ItemStatus.ACTIVE for which in CatalogList for item in studio.items(which))


def test_starting_studio_records_system_as_the_author() -> None:
    _, change = starting_studio(a_sending_address(), NOW)
    assert change == SettingChange(NOW, "system", "Starting settings")


def test_starting_studio_checks_the_sending_address() -> None:
    with pytest.raises(errors.SendingAddressOutsideAsmbly):
        starting_studio(an_address("ceramics"), NOW)


def test_a_change_needs_an_aware_time_and_a_username() -> None:
    with pytest.raises(ValueError, match="aware"):
        starting_studio(a_sending_address(), datetime(2026, 11, 13))  # noqa: DTZ001
    with pytest.raises(ValueError, match="username"):
        add_item(a_studio(), CatalogList.KILNS, "Hestia", "", NOW)


# The email settings


def change(
    studio: Studio,
    *,
    address: str | None = None,
    window: str = "14",
    hours: str | None = None,
) -> tuple[Studio, list[SettingChange]]:
    return change_email_settings(
        studio,
        sending_address=address if address is not None else studio.sending_address,
        pickup_window_days=window,
        pickup_hours_text=hours if hours is not None else studio.pickup_hours_text,
        by=STAFF,
        at=LATER,
    )


def test_change_email_settings_records_one_change_per_value() -> None:
    old = a_studio()
    new_address = a_sending_address("kilnops")
    studio, changes = change(old, address=new_address, window=" 10 ", hours="  Open daily.  ")
    assert (studio.sending_address, studio.pickup_window_days, studio.pickup_hours_text) == (
        new_address,
        10,
        "Open daily.",
    )
    assert changes == [
        SettingChange(LATER, STAFF, f"Sending address: {old.sending_address} → {new_address}"),
        SettingChange(LATER, STAFF, "Pickup window: 14 → 10 days"),
        SettingChange(LATER, STAFF, "Changed the pickup hours text"),
    ]
    _, only_window = change(old, window="21")
    assert only_window == [SettingChange(LATER, STAFF, "Pickup window: 14 → 21 days")]


def test_change_email_settings_records_nothing_when_unchanged() -> None:
    old = a_studio()
    studio, changes = change(
        old,
        address=" " + an_address("ceramics", "ASMBLY.ORG") + " ",
        window="014",
        hours=old.pickup_hours_text + "\n",
    )
    assert changes == []
    assert studio is old


def test_change_email_settings_records_nothing_when_only_line_endings_differ() -> None:
    old = a_studio()
    crlf = old.pickup_hours_text.replace("\n", "\r\n")
    assert crlf != old.pickup_hours_text
    studio, changes = change(old, hours=crlf)
    assert changes == []
    assert studio is old
    studio, changes = change(old, hours=old.pickup_hours_text.replace("\n", "\r"))
    assert changes == []


def test_hours_text_counts_a_crlf_newline_once() -> None:
    text = "x\r\n" * (HOURS_TEXT_MAX // 2 - 1) + "xx"
    studio, _ = change(a_studio(), hours=text)
    assert studio.pickup_hours_text == "x\n" * (HOURS_TEXT_MAX // 2 - 1) + "xx"
    assert len(studio.pickup_hours_text) == HOURS_TEXT_MAX


@pytest.mark.parametrize("control", ["\x00", "\x1b", "\x07", "\x7f", "\x85", "\x0b", "\x0c"])
def test_hours_text_refuses_control_characters(control: str) -> None:
    with pytest.raises(errors.InvalidSetting, match="plain text") as refused:
        change(a_studio(), hours=f"Open daily{control}5am to 2am")
    assert refused.value.field == "pickup_hours_text"


def test_hours_text_keeps_newlines_and_tabs() -> None:
    studio, _ = change(a_studio(), hours="Members:\t5am to 2am\nStudents:\tSOD shifts")
    assert studio.pickup_hours_text == "Members:\t5am to 2am\nStudents:\tSOD shifts"


def test_change_email_settings_refuses_an_address_outside_asmbly() -> None:
    with pytest.raises(errors.SendingAddressOutsideAsmbly):
        change(a_studio(), address=an_address("kilnops"))


@pytest.mark.parametrize("window", ["0", "-1", ""])
def test_pickup_window_below_1_refused(window: str) -> None:
    with pytest.raises(errors.InvalidSetting, match="from 1 to 90") as refused:
        change(a_studio(), window=window)
    assert refused.value.field == "pickup_window_days"


def test_pickup_window_above_90_refused() -> None:
    assert change(a_studio(), window="90")[0].pickup_window_days == 90
    with pytest.raises(errors.InvalidSetting, match="from 1 to 90"):
        change(a_studio(), window="91")


@pytest.mark.parametrize("window", ["2.5", "ten", "١٤", "1⁴", "1e1", "+14", "9" * 5000, "00014"])
def test_pickup_window_not_a_whole_number_refused(window: str) -> None:
    with pytest.raises(errors.InvalidSetting, match="from 1 to 90"):
        change(a_studio(), window=window)


def test_hours_text_over_2000_refused() -> None:
    assert change(a_studio(), hours="x" * HOURS_TEXT_MAX)[0].pickup_hours_text == "x" * HOURS_TEXT_MAX
    with pytest.raises(errors.InvalidSetting, match="longer than 2,000") as refused:
        change(a_studio(), hours="x" * (HOURS_TEXT_MAX + 1))
    assert refused.value.field == "pickup_hours_text"


@pytest.mark.parametrize("hours", ["", "  \n "])
def test_hours_text_empty_refused(hours: str) -> None:
    with pytest.raises(errors.InvalidSetting, match="Enter the pickup hours") as refused:
        change(a_studio(), hours=hours)
    assert refused.value.field == "pickup_hours_text"


# The lists


def test_add_item_records_the_change() -> None:
    studio, record = add_item(a_studio(), CatalogList.KILNS, "  Hestia ", STAFF, LATER)
    assert names(studio, CatalogList.KILNS) == ["Athena", "Helios", "Vulcan", "Hestia"]
    assert studio.item(CatalogList.KILNS, ItemId("hestia")).status is ItemStatus.ACTIVE
    assert record == SettingChange(LATER, STAFF, "Added kiln Hestia")


def test_add_item_keeps_the_flags_on_their_own_lists() -> None:
    studio, _ = add_item(a_studio(), CatalogList.FIRING_TYPES, "Raku", STAFF, LATER, needs_glaze_type=True)
    assert studio.item(CatalogList.FIRING_TYPES, ItemId("raku")).needs_glaze_type
    studio, _ = add_item(studio, CatalogList.REASONS, "Cracked", STAFF, LATER, needs_message=True)
    assert studio.item(CatalogList.REASONS, ItemId("cracked")).needs_message
    with pytest.raises(ValueError, match="glaze type"):
        add_item(studio, CatalogList.KILNS, "Hestia", STAFF, LATER, needs_glaze_type=True)
    with pytest.raises(ValueError, match="message"):
        add_item(studio, CatalogList.GLAZE_TYPES, "Celadon", STAFF, LATER, needs_message=True)


@pytest.mark.parametrize("name", ["", "   ", "x" * (ITEM_NAME_MAX + 1), "Two\nlines"])
def test_add_item_refuses_a_bad_name(name: str) -> None:
    with pytest.raises(errors.InvalidSetting) as refused:
        add_item(a_studio(), CatalogList.KILNS, name, STAFF, LATER)
    assert refused.value.field == "name"


def test_add_item_accepts_a_name_of_exactly_the_maximum() -> None:
    name = "K" * ITEM_NAME_MAX
    studio, _ = add_item(a_studio(), CatalogList.KILNS, name, STAFF, LATER)
    assert names(studio, CatalogList.KILNS)[-1] == name


def test_add_item_stores_the_name_in_nfc_and_compares_it_so() -> None:
    decomposed = "Ce\u0301leste"  # e + combining acute
    studio, record = add_item(a_studio(), CatalogList.KILNS, decomposed, STAFF, LATER)
    assert names(studio, CatalogList.KILNS)[-1] == "C\u00e9leste"
    assert record.what == "Added kiln C\u00e9leste"
    with pytest.raises(errors.DuplicateItem):
        add_item(studio, CatalogList.KILNS, decomposed, STAFF, LATER)
    with pytest.raises(errors.DuplicateItem):
        add_item(studio, CatalogList.KILNS, "C\u00e9leste", STAFF, LATER)


def test_duplicate_name_refused_case_insensitively() -> None:
    with pytest.raises(errors.DuplicateItem, match="There is already a kiln called HELIOS"):
        add_item(a_studio(), CatalogList.KILNS, "HELIOS", STAFF, LATER)
    retired, _ = retire_item(a_studio(), CatalogList.KILNS, ItemId("vulcan"), STAFF, LATER)
    with pytest.raises(errors.DuplicateItem):
        add_item(retired, CatalogList.KILNS, "vulcan", STAFF, LATER)


def test_a_new_item_gets_a_unique_id() -> None:
    studio, _ = add_item(a_studio(), CatalogList.KILNS, "Helios!", STAFF, LATER)
    assert [item.id for item in studio.kilns][-1] == "helios-2"


def test_retired_item_cannot_be_picked() -> None:
    studio, record = retire_item(a_studio(), CatalogList.KILNS, ItemId("vulcan"), STAFF, LATER)
    assert record == SettingChange(LATER, STAFF, "Retired kiln Vulcan")
    assert studio.item(CatalogList.KILNS, ItemId("vulcan")).status is ItemStatus.RETIRED
    with pytest.raises(errors.ItemRetired, match="Vulcan is retired"):
        studio.active_item(CatalogList.KILNS, ItemId("vulcan"))
    assert studio.active_item(CatalogList.KILNS, ItemId("athena")).name == "Athena"
    with pytest.raises(errors.InvalidSetting, match="Vulcan is already retired") as refused:
        retire_item(studio, CatalogList.KILNS, ItemId("vulcan"), STAFF, LATER)
    assert refused.value.field == "status"


def test_restore_makes_an_item_pickable_again() -> None:
    retired, _ = retire_item(a_studio(), CatalogList.KILNS, ItemId("vulcan"), STAFF, LATER)
    studio, record = restore_item(retired, CatalogList.KILNS, ItemId("vulcan"), STAFF, LATER)
    assert record == SettingChange(LATER, STAFF, "Restored kiln Vulcan")
    assert studio.active_item(CatalogList.KILNS, ItemId("vulcan")).name == "Vulcan"
    with pytest.raises(errors.InvalidSetting, match="Vulcan is already active"):
        restore_item(studio, CatalogList.KILNS, ItemId("vulcan"), STAFF, LATER)


@pytest.mark.parametrize("which", list(CatalogList))
def test_an_unknown_item_is_refused(which: CatalogList) -> None:
    studio = a_studio()
    unknown = ItemId("nope")
    with pytest.raises(errors.UnknownItem, match=r"That .+ doesn't exist\."):
        studio.item(which, unknown)
    with pytest.raises(errors.UnknownItem):
        retire_item(studio, which, unknown, STAFF, LATER)
    with pytest.raises(errors.UnknownItem):
        restore_item(studio, which, unknown, STAFF, LATER)
    with pytest.raises(errors.UnknownItem):
        delete_item(studio, which, unknown, used=False, by=STAFF, at=LATER)


def test_used_item_can_be_retired_not_deleted() -> None:
    studio = a_studio()
    with pytest.raises(errors.ItemInUse, match="Helios is used by a drop-off or a load: retire it instead"):
        delete_item(studio, CatalogList.KILNS, ItemId("helios"), used=True, by=STAFF, at=LATER)
    retired, _ = retire_item(studio, CatalogList.KILNS, ItemId("helios"), STAFF, LATER)
    assert retired.item(CatalogList.KILNS, ItemId("helios")).status is ItemStatus.RETIRED


def test_unused_item_can_be_deleted() -> None:
    studio, record = delete_item(
        a_studio(), CatalogList.KILNS, ItemId("helios"), used=False, by=STAFF, at=LATER
    )
    assert names(studio, CatalogList.KILNS) == ["Athena", "Vulcan"]
    assert record == SettingChange(LATER, STAFF, "Deleted kiln Helios")


def test_a_retired_item_can_be_deleted_even_when_one_active_item_remains() -> None:
    studio = a_studio()
    for kiln in ("athena", "helios"):
        studio, _ = retire_item(studio, CatalogList.KILNS, ItemId(kiln), STAFF, LATER)
    studio, _ = delete_item(studio, CatalogList.KILNS, ItemId("athena"), used=False, by=STAFF, at=LATER)
    assert names(studio, CatalogList.KILNS) == ["Helios", "Vulcan"]


@pytest.mark.parametrize("which", list(CatalogList))
def test_the_last_active_item_of_each_list_cannot_be_retired_or_deleted(which: CatalogList) -> None:
    studio = a_studio()
    *others, last = studio.items(which)
    for item in others:
        studio, _ = retire_item(studio, which, item.id, STAFF, LATER)
    assert active_names(studio, which) == [last.name]
    with pytest.raises(errors.InvalidSetting, match=f"{last.name} is the last active") as refused:
        retire_item(studio, which, last.id, STAFF, LATER)
    assert refused.value.field == "status"
    with pytest.raises(errors.InvalidSetting, match=f"{last.name} is the last active"):
        delete_item(studio, which, last.id, used=False, by=STAFF, at=LATER)


def test_changes_leave_the_version_alone() -> None:
    studio, _ = add_item(a_studio(), CatalogList.KILNS, "Hestia", STAFF, LATER)
    assert studio.version == 0
