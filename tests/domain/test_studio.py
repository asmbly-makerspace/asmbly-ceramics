import re
from datetime import datetime, timedelta

import pytest

from asmbly_ceramics.domain import errors
from asmbly_ceramics.domain.firing import Program, Speed
from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.limits import EMAIL_MAX, HOURS_TEXT_MAX, ITEM_NAME_MAX
from asmbly_ceramics.domain.studio import (
    STARTING_CLAY_BODIES,
    STARTING_CONES,
    CatalogList,
    ItemStatus,
    KilnCounts,
    SettingChange,
    Studio,
    add_item,
    can_delete_item,
    change_email_settings,
    check_sending_address,
    delete_item,
    describe_program,
    is_valid_email,
    kind_name,
    kinds_name,
    nameable_cone_ids,
    nameable_cones,
    names_cone,
    record_new_elements,
    restore_item,
    retire_item,
    set_default_program,
    set_kiln_counts,
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
    cap: str = "300",
) -> tuple[Studio, list[SettingChange]]:
    return change_email_settings(
        studio,
        sending_address=address if address is not None else studio.sending_address,
        pickup_window_days=window,
        pickup_hours_text=hours if hours is not None else studio.pickup_hours_text,
        received_emails_per_day=cap,
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
        SettingChange(LATER, STAFF, "Changed the sending address"),
        SettingChange(LATER, STAFF, "Pickup window: 14 → 10 days"),
        SettingChange(LATER, STAFF, "Changed the pickup hours text"),
    ]
    _, only_window = change(old, window="21")
    assert only_window == [SettingChange(LATER, STAFF, "Pickup window: 14 → 21 days")]


def test_a_new_studio_caps_received_emails_at_300() -> None:
    studio, _ = starting_studio(a_sending_address(), at=NOW)
    assert studio.received_emails_per_day == 300
    assert a_studio().received_emails_per_day == 300


def test_change_email_settings_records_the_cap_change() -> None:
    old = a_studio()
    studio, changes = change(old, cap=" 120 ")
    assert studio.received_emails_per_day == 120
    assert (studio.sending_address, studio.pickup_window_days, studio.pickup_hours_text) == (
        old.sending_address,
        old.pickup_window_days,
        old.pickup_hours_text,
    )
    assert changes == [SettingChange(LATER, STAFF, "Received emails a day, at most: 300 → 120")]
    assert change(old, cap="0300") == (old, [])


@pytest.mark.parametrize("cap", ["0", "2001", "-5", "1.5", "", "12abc", "١٢", "9" * 5000])
def test_received_emails_per_day_outside_1_to_2000_refused(cap: str) -> None:
    old = a_studio()
    with pytest.raises(errors.InvalidSetting, match="from 1 to 2,000") as refused:
        change(old, window="21", cap=cap)
    assert refused.value.field == "received_emails_per_day"
    assert (old.received_emails_per_day, old.pickup_window_days) == (300, 14)


def test_received_emails_per_day_takes_1_and_2000() -> None:
    assert change(a_studio(), cap="1")[0].received_emails_per_day == 1
    assert change(a_studio(), cap="2000")[0].received_emails_per_day == 2000


def test_the_history_holds_no_sending_address() -> None:
    old = a_studio()
    new_address = a_sending_address("kilnops")
    _, changes = change(old, address=new_address)
    assert changes == [SettingChange(LATER, STAFF, "Changed the sending address")]
    for change_ in changes:
        assert "@" not in change_.what
        assert old.sending_address.split("@")[0] not in change_.what
        assert "kilnops" not in change_.what


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
    studio, _ = retire_item(a_studio(), CatalogList.KILNS, ItemId("helios"), STAFF, LATER)
    assert studio.item(CatalogList.KILNS, ItemId("helios")).status is ItemStatus.RETIRED
    in_use = "Helios is in use by a drop-off, a load, a default program or a note, so it stays retired"
    with pytest.raises(errors.ItemInUse, match=in_use):
        delete_item(studio, CatalogList.KILNS, ItemId("helios"), used=True, by=STAFF, at=LATER)


@pytest.mark.parametrize("used", [False, True])
def test_an_active_item_must_be_retired_before_it_is_deleted(used: bool) -> None:
    # Retiring is what stops new use, so a delete can't race a submit or a new load
    # that names the item: `used` is read only once nothing new can name it.
    with pytest.raises(errors.InvalidSetting, match="Retire Helios before deleting it") as refused:
        delete_item(a_studio(), CatalogList.KILNS, ItemId("helios"), used=used, by=STAFF, at=LATER)
    assert refused.value.field == "status"


def test_a_retired_unused_item_can_be_deleted() -> None:
    studio, _ = retire_item(a_studio(), CatalogList.KILNS, ItemId("helios"), STAFF, LATER)
    studio, record = delete_item(studio, CatalogList.KILNS, ItemId("helios"), used=False, by=STAFF, at=LATER)
    assert names(studio, CatalogList.KILNS) == ["Athena", "Vulcan"]
    assert record == SettingChange(LATER, STAFF, "Deleted kiln Helios")


@pytest.mark.parametrize("retired", [False, True])
@pytest.mark.parametrize("used", [False, True])
def test_can_delete_item_agrees_with_delete_item(retired: bool, used: bool) -> None:
    studio = a_studio()
    if retired:
        studio, _ = retire_item(studio, CatalogList.KILNS, ItemId("helios"), STAFF, LATER)
    item = studio.item(CatalogList.KILNS, ItemId("helios"))
    assert item.retired is retired
    try:
        delete_item(studio, CatalogList.KILNS, item.id, used=used, by=STAFF, at=LATER)
    except errors.InvalidSetting, errors.ItemInUse:
        assert not can_delete_item(item, used=used)
    else:
        assert can_delete_item(item, used=used)


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
    with pytest.raises(errors.InvalidSetting, match=f"{re.escape(last.name)} is the last active") as refused:
        retire_item(studio, which, last.id, STAFF, LATER)
    assert refused.value.field == "status"
    with pytest.raises(errors.InvalidSetting, match=f"Retire {re.escape(last.name)} before deleting it"):
        delete_item(studio, which, last.id, used=False, by=STAFF, at=LATER)


def test_changes_leave_the_version_alone() -> None:
    studio, _ = add_item(a_studio(), CatalogList.KILNS, "Hestia", STAFF, LATER)
    assert studio.version == 0


# Cones, clay bodies, default programs and kiln counts (#42, #17)

CONE_06, CONE_6 = ItemId("item-06"), ItemId("item-6")
HELIOS = ItemId("helios")
GLAZE = ItemId("glaze")
GLAZE_PROGRAM = {"preheat_hours": "0", "cone": "item-6", "speed": "medium", "hold_minutes": "7"}


def test_starting_studio_has_cones_and_clay_bodies() -> None:
    studio = a_studio()
    assert names(studio, CatalogList.CONES) == ["^06", "^5", "^6"]
    assert names(studio, CatalogList.CLAY_BODIES) == ["Buffalo Wallow", "Cinco Blanco", "Cone 5 Porcelain"]
    assert all(item.counts is None for item in studio.kilns)


def test_starting_firing_types_have_default_programs() -> None:
    studio = a_studio()
    assert studio.item(CatalogList.FIRING_TYPES, ItemId("bisque")).default_program == Program(
        preheat_hours=8, cone=CONE_06, speed=Speed.SLOW, hold_minutes=0
    )
    assert studio.item(CatalogList.FIRING_TYPES, GLAZE).default_program == Program(
        preheat_hours=0, cone=CONE_6, speed=Speed.MEDIUM, hold_minutes=7
    )


def test_a_studio_built_without_the_new_lists_has_the_starting_ones() -> None:
    studio = a_studio()
    older = Studio(
        studio.sending_address,
        studio.pickup_window_days,
        studio.pickup_hours_text,
        studio.kilns,
        studio.firing_types,
        studio.glaze_types,
        studio.reasons,
    )
    assert older.cones == STARTING_CONES
    assert older.clay_bodies == STARTING_CLAY_BODIES


def test_cone_ids_from_caret_names() -> None:
    # `^` isn't a slug character: a cone's ID is its number with `item-` in front.
    assert [item.id for item in a_studio().cones] == ["item-06", "item-5", "item-6"]
    studio, _ = add_item(a_studio(), CatalogList.CONES, "^04", STAFF, LATER)
    assert studio.item(CatalogList.CONES, ItemId("item-04")).name == "^04"


@pytest.mark.parametrize(
    ("which", "kind"), [(CatalogList.CONES, "cone"), (CatalogList.CLAY_BODIES, "clay body")]
)
def test_add_retire_delete_cone_and_clay_body(which: CatalogList, kind: str) -> None:
    studio, added = add_item(a_studio(), which, "Speckled", STAFF, LATER)
    assert added.what == f"Added {kind} Speckled"
    item = ItemId("speckled")
    with pytest.raises(errors.DuplicateItem):
        add_item(studio, which, "speckled", STAFF, LATER)
    studio, retired = retire_item(studio, which, item, STAFF, LATER)
    assert retired.what == f"Retired {kind} Speckled"
    with pytest.raises(errors.ItemInUse):
        delete_item(studio, which, item, used=True, by=STAFF, at=LATER)
    studio, restored = restore_item(studio, which, item, STAFF, LATER)
    assert restored.what == f"Restored {kind} Speckled"
    studio, _ = retire_item(studio, which, item, STAFF, LATER)
    studio, deleted = delete_item(studio, which, item, used=False, by=STAFF, at=LATER)
    assert deleted.what == f"Deleted {kind} Speckled"
    assert "Speckled" not in names(studio, which)


def test_set_default_program_and_history() -> None:
    form = {"preheat_hours": "1", "cone": "item-5", "speed": "FAST", "hold_minutes": "10"}
    studio, change = set_default_program(a_studio(), GLAZE, form, STAFF, LATER)
    assert studio.item(CatalogList.FIRING_TYPES, GLAZE).default_program == Program(
        preheat_hours=1, cone=ItemId("item-5"), speed=Speed.FAST, hold_minutes=10
    )
    assert change == SettingChange(
        LATER, STAFF, "Default program for Glaze: ^5, fast, preheat 1 h, hold 10 min"
    )
    # The same program again changes nothing.
    assert set_default_program(studio, GLAZE, form, STAFF, LATER) == (studio, None)
    # A part left blank is left out of the history line.
    _, change = set_default_program(studio, GLAZE, {"cone": "item-6"}, STAFF, LATER)
    assert change is not None
    assert change.what == "Default program for Glaze: ^6"


def test_set_default_program_blank_clears() -> None:
    blank = dict.fromkeys(GLAZE_PROGRAM, " ")
    studio, change = set_default_program(a_studio(), GLAZE, blank, STAFF, LATER)
    assert studio.item(CatalogList.FIRING_TYPES, GLAZE).default_program is None
    assert change == SettingChange(LATER, STAFF, "Cleared the default program for Glaze")
    assert set_default_program(studio, GLAZE, {}, STAFF, LATER) == (studio, None)


def test_set_default_program_unknown_cone() -> None:
    with pytest.raises(errors.InvalidRecord) as refused:
        set_default_program(
            a_studio(), GLAZE, GLAZE_PROGRAM | {"cone": "item-99", "hold_minutes": "x"}, STAFF, LATER
        )
    assert list(refused.value.errors) == ["cone", "hold_minutes"]
    with pytest.raises(errors.UnknownItem, match="firing type"):
        set_default_program(a_studio(), ItemId("raku"), GLAZE_PROGRAM, STAFF, LATER)


def test_set_default_program_takes_active_cones_or_the_one_it_names() -> None:
    studio, _ = retire_item(a_studio(), CatalogList.CONES, CONE_6, STAFF, LATER)
    # Glaze's program already names ^6: its hold can still change.
    studio, change = set_default_program(studio, GLAZE, GLAZE_PROGRAM | {"hold_minutes": "9"}, STAFF, LATER)
    assert change is not None
    # Bisque's doesn't: a retired cone is refused for it.
    with pytest.raises(errors.InvalidRecord) as refused:
        set_default_program(studio, ItemId("bisque"), GLAZE_PROGRAM, STAFF, LATER)
    assert list(refused.value.errors) == ["cone"]


def test_nameable_cones_are_the_active_ones_and_the_one_already_named() -> None:
    studio, _ = retire_item(a_studio(), CatalogList.CONES, CONE_6, STAFF, LATER)
    active = [cone.id for cone in studio.cones if not cone.retired]

    assert [cone.id for cone in nameable_cones(studio, None)] == active
    named = [cone.id for cone in nameable_cones(studio, CONE_6)]
    assert set(named) == {*active, CONE_6}
    assert named == [cone.id for cone in studio.cones if cone.id in named]  # the studio's order
    assert nameable_cone_ids(studio, CONE_6) == frozenset(named)
    # A cone gone from the list still counts for the program that names it.
    gone = ItemId("item-99")
    assert [cone.id for cone in nameable_cones(studio, gone)] == active
    assert nameable_cone_ids(studio, gone) == frozenset({*active, gone})


def test_set_default_program_on_a_retired_firing_type() -> None:
    studio, _ = retire_item(a_studio(), CatalogList.FIRING_TYPES, GLAZE, STAFF, LATER)
    studio, change = set_default_program(studio, GLAZE, GLAZE_PROGRAM | {"hold_minutes": "8"}, STAFF, LATER)
    assert change is not None
    program = studio.item(CatalogList.FIRING_TYPES, GLAZE).default_program
    assert program is not None
    assert program.hold_minutes == 8


def test_names_cone() -> None:
    studio = a_studio()
    assert names_cone(studio, CONE_6)
    assert not names_cone(studio, ItemId("item-5"))
    studio, _ = set_default_program(studio, GLAZE, {}, STAFF, LATER)
    assert not names_cone(studio, CONE_6)


def test_a_cone_a_default_program_names_is_not_deleted_even_when_unused() -> None:
    studio, _ = retire_item(a_studio(), CatalogList.CONES, CONE_6, STAFF, LATER)
    with pytest.raises(errors.ItemInUse, match=r"\^6 is in use"):
        delete_item(studio, CatalogList.CONES, CONE_6, used=False, by=STAFF, at=LATER)
    studio, _ = set_default_program(studio, GLAZE, {}, STAFF, LATER)
    studio, change = delete_item(studio, CatalogList.CONES, CONE_6, used=False, by=STAFF, at=LATER)
    assert CONE_6 not in {cone.id for cone in studio.cones}
    assert change.what == "Deleted cone ^6"


def test_set_kiln_counts_and_history() -> None:
    studio, change = set_kiln_counts(a_studio(), HELIOS, " 97 ", "1251", STAFF, LATER)
    assert studio.item(CatalogList.KILNS, HELIOS).counts == KilnCounts(97, 1251, LATER)
    assert change == SettingChange(LATER, STAFF, "Helios counts: 97 since elements, 1,251 all time")
    studio, _ = set_kiln_counts(studio, HELIOS, "0", "0", STAFF, LATER)
    assert studio.item(CatalogList.KILNS, HELIOS).counts == KilnCounts(0, 0, LATER)


@pytest.mark.parametrize("bad", ["", "-1", "1.5", "x", "100001", "1" * 5000, "٣"])
def test_set_kiln_counts_checks_numbers(bad: str) -> None:
    with pytest.raises(errors.InvalidSetting, match="Enter a whole number from 0 to 100,000") as refused:
        set_kiln_counts(a_studio(), HELIOS, bad, "10", STAFF, LATER)
    assert refused.value.field == "since_elements"
    with pytest.raises(errors.InvalidSetting) as refused:
        set_kiln_counts(a_studio(), HELIOS, "1", bad, STAFF, LATER)
    assert refused.value.field == "all_time"


def test_set_kiln_counts_since_not_above_all_time() -> None:
    with pytest.raises(errors.InvalidSetting, match="can't be more than") as refused:
        set_kiln_counts(a_studio(), HELIOS, "11", "10", STAFF, LATER)
    assert refused.value.field == "since_elements"
    with pytest.raises(errors.UnknownItem, match="kiln"):
        set_kiln_counts(a_studio(), ItemId("hestia"), "1", "2", STAFF, LATER)


def test_record_new_elements_resets_since() -> None:
    studio, _ = set_kiln_counts(a_studio(), HELIOS, "97", "251", STAFF, NOW)
    studio, change = record_new_elements(studio, HELIOS, 260, STAFF, LATER)
    assert studio.item(CatalogList.KILNS, HELIOS).counts == KilnCounts(0, 260, LATER)
    assert change == SettingChange(LATER, STAFF, "New elements in Helios")
    # A retired kiln can still have new elements recorded.
    studio, _ = retire_item(studio, CatalogList.KILNS, HELIOS, STAFF, LATER)
    studio, _ = record_new_elements(studio, HELIOS, 0, STAFF, LATER)
    with pytest.raises(ValueError, match="all-time count"):
        record_new_elements(studio, HELIOS, -1, STAFF, LATER)
    with pytest.raises(ValueError, match="aware"):
        record_new_elements(studio, HELIOS, 1, STAFF, datetime(2026, 11, 13))  # noqa: DTZ001


def test_describe_program_names_a_cone_it_does_not_know_by_its_id() -> None:
    program = Program(cone=ItemId("item-99"), hold_minutes=5)
    assert describe_program(a_studio(), program) == "item-99, hold 5 min"


@pytest.mark.parametrize(
    ("which", "one", "many"),
    [
        (CatalogList.GLAZE_TYPES, "glaze type", "glaze types"),
        (CatalogList.CLAY_BODIES, "clay body", "clay bodies"),
        (CatalogList.KILNS, "kiln", "kilns"),
    ],
)
def test_kind_names(which: CatalogList, one: str, many: str) -> None:
    assert (kind_name(which), kinds_name(which)) == (one, many)
