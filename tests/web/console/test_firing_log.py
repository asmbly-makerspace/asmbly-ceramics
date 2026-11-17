"""The firing log page and its CSV (#42): fired loads by kiln, date range and kind, every
query parameter checked on the server, the CSV safe to open in a spreadsheet, and both
for signed-in ceramics staff only."""

import csv
import html
import io
import re
from datetime import date, timedelta
from urllib.parse import urlencode

import httpx2
import pytest

from asmbly_ceramics.domain.firing import RECORD_FIELDS
from asmbly_ceramics.domain.ids import LoadId
from asmbly_ceramics.domain.limits import LOG_RANGE_MAX_YEARS
from asmbly_ceramics.domain.notes import Ruling
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.use_cases.notes import NoteInput
from asmbly_ceramics.web.console.firing_log import CSV_COLUMNS, DASH, csv_cell
from tests.domain.builders import STAFF, TEST_EMAIL, TEST_NAME, TEST_PHONE, TEST_PHONE_DIGITS
from tests.use_cases.flows import HELIOS, STAFF_MEMBER, version
from tests.use_cases.test_firing_log import fired_on
from tests.web.console.conftest import OUTSIDER, Console

LOG = "/console/firing-log"
CSV = "/console/firing-log.csv"
TODAY = date(2026, 11, 13)


@pytest.fixture
def staff(console: Console) -> Console:
    console.sign_in()
    return console


def text(answer: httpx2.Response) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", answer.text)).split())


def listed(answer: httpx2.Response) -> list[LoadId]:
    """The load IDs the table links to, in order."""
    return [LoadId.parse(id) for id in re.findall(r'href="/console/loads/(L-[0-9]+)"', answer.text)]


def rows(answer: httpx2.Response) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(answer.text)))


def save_record(console: Console, load_id: LoadId, **values: str) -> None:
    world = console.world
    world.save_firing_record(load_id, values, version(world, load_id), STAFF_MEMBER)


# --- the page ------------------------------------------------------------------------------


def test_lists_fired_loads_default_range(staff: Console) -> None:
    old = fired_on(staff.world, date(2026, 8, 1))  # before the last 12 weeks
    recent = fired_on(staff.world, date(2026, 11, 2))
    latest = fired_on(staff.world, TODAY)

    answer = staff.get(LOG)

    assert answer.status_code == 200
    assert listed(answer) == [latest, recent]
    assert old not in listed(answer)
    assert "Dated Fri Aug 21, 2026 to today, and any dated ahead." in text(answer)
    assert 'id="from" name="from" value=""' in answer.text  # no date the query didn't give
    assert 'id="to" name="to" value=""' in answer.text


def test_a_load_dated_ahead_stays_listed_after_filtering_by_kiln(staff: Console) -> None:
    """The default read takes loads dated ahead of today; the filter form, sent back with
    its date fields as the page left them, must not cut them off at today."""
    ahead = fired_on(staff.world, date(2026, 11, 16), kiln=HELIOS)
    assert ahead in listed(staff.get(LOG))

    sent = staff.get(LOG + "?" + urlencode({"kiln": "helios", "from": "", "to": "", "kind": "all"}))

    assert listed(sent) == [ahead]


def test_filter_kiln(staff: Console) -> None:
    athena = fired_on(staff.world, TODAY)
    helios = fired_on(staff.world, TODAY, kiln=HELIOS)

    answer = staff.get(f"{LOG}?kiln=helios")

    assert listed(answer) == [helios]
    assert athena not in listed(answer)
    assert '<option value="helios" selected>' in answer.text


def test_filter_kind_tests(staff: Console) -> None:
    fired_on(staff.world, TODAY)
    test = fired_on(staff.world, TODAY, test=True)

    assert listed(staff.get(f"{LOG}?kind=tests")) == [test]


def test_filter_kind_regular(staff: Console) -> None:
    regular = fired_on(staff.world, TODAY)
    fired_on(staff.world, TODAY, test=True)

    assert listed(staff.get(f"{LOG}?kind=regular")) == [regular]


def test_unknown_kind_is_all(staff: Console) -> None:
    regular = fired_on(staff.world, TODAY)
    test = fired_on(staff.world, TODAY, test=True)

    assert listed(staff.get(f"{LOG}?kind=%3Cb%3E")) == [test, regular]


@pytest.mark.parametrize("kiln", ["kiln-nobody-has", "<script>", "ATHENA"])
def test_unknown_kiln_message(staff: Console, kiln: str) -> None:
    load = fired_on(staff.world, TODAY)

    answer = staff.get(LOG + "?" + urlencode({"kiln": kiln}))

    assert answer.status_code == 200
    assert "Pick a kiln from the list." in text(answer)
    assert listed(answer) == [load]  # the default list
    assert kiln not in answer.text


@pytest.mark.parametrize(("start", "end"), [("13/11/2026", ""), ("", "2026-02-30"), ("<b>", "x")])
def test_bad_dates_message(staff: Console, start: str, end: str) -> None:
    load = fired_on(staff.world, TODAY)

    answer = staff.get(LOG + "?" + urlencode({"from": start, "to": end}))

    assert "Enter dates like 2026-11-13." in text(answer)
    assert listed(answer) == [load]
    assert "&lt;b&gt;" not in answer.text
    assert "<b>" not in answer.text


def test_range_too_long_message(staff: Console) -> None:
    load = fired_on(staff.world, TODAY)

    answer = staff.get(f"{LOG}?from=2010-01-01&to=2026-11-13")

    assert f"Choose a date range of at most {LOG_RANGE_MAX_YEARS} years" in text(answer)
    assert listed(answer) == [load]


def test_the_dates_filter_by_the_load_s_date(staff: Console) -> None:
    page = staff.get(LOG).text
    assert '<label for="from">Load dated from</label>' in page
    assert '<label for="to">Load dated to</label>' in page


def test_a_chosen_range(staff: Console) -> None:
    fired_on(staff.world, date(2026, 10, 1))
    inside = fired_on(staff.world, date(2026, 10, 15))

    answer = staff.get(f"{LOG}?from=2026-10-10&to=2026-10-20")

    assert listed(answer) == [inside]
    assert 'value="2026-10-10"' in answer.text
    assert 'value="2026-10-20"' in answer.text
    assert 'href="/console/firing-log.csv?from=2026-10-10&amp;to=2026-10-20"' in answer.text


def test_missing_values_dash(staff: Console) -> None:
    fired_on(staff.world, TODAY, test=True)
    load = fired_on(staff.world, TODAY)
    save_record(staff, load, percent_full="80", max_temp_f="2236", cost="8.19", hold_minutes="", cone="")

    page = text(staff.get(f"{LOG}?kiln=athena&kind=regular"))

    d = DASH
    assert f"{load} Fri Nov 13, 2026 {d} 80% {d} {d} {d} 2,236 °F $8.19 {STAFF} / {STAFF}" in page


def test_record_columns(staff: Console) -> None:
    load = fired_on(staff.world, TODAY)
    save_record(staff, load, firing_number="12", cone="item-6", speed="medium", hold_minutes="7")

    page = text(staff.get(LOG))

    assert f"12 {DASH} ^6 Medium 7 min" in page


def test_test_tag(staff: Console) -> None:
    test = fired_on(staff.world, TODAY, test=True)

    answer = staff.get(LOG)

    assert f'{test}</a> <span class="tag">Test</span>' in answer.text


def test_each_row_opens_its_load(staff: Console) -> None:
    load = fired_on(staff.world, TODAY)

    assert f'href="/console/loads/{load}"' in staff.get(LOG).text


def test_no_firings_match(staff: Console) -> None:
    assert "No firings match." in text(staff.get(LOG))


def test_counts_line_for_one_kiln(staff: Console) -> None:
    world = staff.world
    world.set_kiln_counts(HELIOS, "40", "300", world.studio().version, STAFF_MEMBER)

    one = text(staff.get(f"{LOG}?kiln=helios"))
    every = text(staff.get(LOG))

    assert "Firing # counts from Fri Nov 13, 2026 (40 since elements then)." in one
    assert "Firing # counts from" not in every


def test_a_kiln_with_no_counts_has_no_counts_line(staff: Console) -> None:
    assert "Firing # counts from" not in text(staff.get(f"{LOG}?kiln=helios"))


def test_tab_shown_and_current(staff: Console) -> None:
    assert 'href="/console/firing-log" aria-current="page">Firing log' in staff.get(LOG).text
    loads = staff.get("/console/loads").text
    assert 'href="/console/firing-log">Firing log' in loads


def test_download_link_carries_the_checked_query_only(staff: Console) -> None:
    answer = staff.get(LOG + "?" + urlencode({"kiln": "helios", "kind": "tests", "from": "bad"}))

    assert 'href="/console/firing-log.csv?kiln=helios&amp;kind=tests"' in answer.text


def test_default_range_csv_link_has_no_dates(staff: Console) -> None:
    """The page's default range reads loads dated ahead of today; the CSV link leaves the
    dates out so the download lists the same rows."""
    ahead = fired_on(staff.world, date(2026, 11, 20))

    page = staff.get(LOG)
    download = rows(staff.get(CSV))

    assert listed(page) == [ahead]
    assert 'href="/console/firing-log.csv"' in page.text
    assert [row["load"] for row in download] == [str(ahead)]


# --- the CSV -------------------------------------------------------------------------------


def test_csv_headers_and_rows(staff: Console) -> None:
    test = fired_on(staff.world, TODAY, test=True)
    save_record(
        staff,
        test,
        percent_full="80",
        firing_number="3",
        all_time_number="301",
        preheat_hours="2",
        cone="item-6",
        speed="slow",
        hold_minutes="10",
        firing_time="11:38",
        max_temp_f="2236",
        board_temp_f="120",
        cost="8.19",
        cone_top="100",
        cone_center="none",
    )

    answer = staff.get(CSV)

    assert answer.status_code == 200
    assert answer.headers["content-type"] == "text/csv; charset=utf-8"
    assert answer.text.splitlines()[0] == ",".join(CSV_COLUMNS)
    (row,) = rows(answer)
    assert row["load"] == str(test)
    assert row["kiln"] == "Athena"
    assert row["firing type"] == "Glaze"
    assert row["test"] == "yes"
    assert row["date"] == "2026-11-13"
    assert row["started by"] == row["firing started by"] == row["fired by"] == STAFF
    assert row["fired at"].endswith("-06:00")  # Austin, with its offset
    assert row["started at"]
    assert row["firing started at"]
    assert [row[c] for c in CSV_COLUMNS[11:]] == [
        "80",
        "3",
        "301",
        "2",
        "^6",
        "slow",
        "10",
        "11:38",
        "2236",
        "120",
        "8.19",
        "100",
        "none",
        "",
        "0",
        "0",
    ]


def test_csv_has_a_header_for_each_record_field_and_each_row_fits_it() -> None:
    """The record's headers come from the domain's field list, so a field added there
    gets a column; this pins the download's headers, which a spreadsheet may rely on."""
    assert CSV_COLUMNS[11:] == (
        "percent full",
        "firing number",
        "all time number",
        "preheat hours",
        "cone",
        "speed",
        "hold minutes",
        "firing time",
        "max temp f",
        "board temp f",
        "cost",
        "cone top",
        "cone center",
        "cone bottom",
        "notes",
        "not allowed notes",
    )
    assert len(CSV_COLUMNS) == 11 + len(RECORD_FIELDS) + 2


def test_csv_rows_have_one_cell_per_header(staff: Console) -> None:
    fired_on(staff.world, TODAY)
    lines = list(csv.reader(io.StringIO(staff.get(CSV).text)))
    assert len(lines) == 2
    assert all(len(line) == len(CSV_COLUMNS) for line in lines)


def test_csv_regular_and_kind_filter(staff: Console) -> None:
    regular = fired_on(staff.world, TODAY)
    fired_on(staff.world, TODAY, test=True)

    (row,) = rows(staff.get(f"{CSV}?kind=regular"))

    assert row["load"] == str(regular)
    assert row["test"] == "no"


def test_csv_filename_from_checked_values(staff: Console) -> None:
    chosen = staff.get(f"{CSV}?kiln=helios&from=2026-10-01&to=2026-10-31")
    default = staff.get(CSV)

    disposition = 'attachment; filename="firing-log-helios-2026-10-01-2026-10-31.csv"'
    assert chosen.headers["content-disposition"] == disposition
    assert (
        default.headers["content-disposition"]
        == 'attachment; filename="firing-log-all-2026-08-21-2026-11-13.csv"'
    )


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({"kiln": 'evil"; x='}, "Pick a kiln from the list."),
        ({"kiln": "kiln-nobody-has"}, "Pick a kiln from the list."),
        ({"from": "x"}, "Enter dates like 2026-11-13."),
        ({"to": "2026-02-30"}, "Enter dates like 2026-11-13."),
        (
            {"from": "2010-01-01", "to": "2026-11-13"},
            f"Choose a date range of at most {LOG_RANGE_MAX_YEARS} years",
        ),
        ({"from": "2026-11-13", "to": "2026-11-01"}, "ending after it starts"),
    ],
)
def test_csv_with_a_refused_filter_is_400_not_another_download(
    staff: Console, query: dict[str, str], message: str
) -> None:
    """A download can't show which filter was dropped, so it never falls back to the
    default kiln or range: it answers 400 with the message, and no CSV."""
    fired_on(staff.world, TODAY)

    answer = staff.get(CSV + "?" + urlencode(query))

    assert answer.status_code == 400
    assert "text/csv" not in answer.headers["content-type"]
    assert "content-disposition" not in answer.headers
    assert message in text(answer)
    assert "evil" not in answer.text  # nothing sent is echoed
    assert "kiln-nobody-has" not in answer.text


def test_csv_formula_cells_prefixed(staff: Console) -> None:
    world = staff.world
    world.add_item(
        CatalogList.KILNS,
        "=HYPERLINK(1)",
        needs_glaze_type=False,
        needs_message=False,
        version=world.studio().version,
        staff=STAFF_MEMBER,
    )
    (kiln,) = (item for item in world.studio().kilns if item.name.startswith("="))
    fired_on(world, TODAY, kiln=kiln.id, test=True)

    (row,) = rows(staff.get(CSV))

    assert row["kiln"] == "'=HYPERLINK(1)"
    assert all(not cell.startswith(("=", "+", "-", "@", "\t", "\r")) for cell in row.values())


def test_markup_in_a_kiln_name_is_escaped(staff: Console) -> None:
    world = staff.world
    world.add_item(
        CatalogList.KILNS,
        "<b>Hot</b>",
        needs_glaze_type=False,
        needs_message=False,
        version=world.studio().version,
        staff=STAFF_MEMBER,
    )
    (kiln,) = (item for item in world.studio().kilns if item.name.startswith("<"))
    fired_on(world, TODAY, kiln=kiln.id)

    answer = staff.get(LOG)

    assert "<b>Hot</b>" not in answer.text
    assert "&lt;b&gt;Hot&lt;/b&gt;" in answer.text


@pytest.mark.parametrize(
    ("value", "cell"),
    [
        ("=1+1", "'=1+1"),
        ("+1", "'+1"),
        ("-1", "'-1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("\rx", "'\rx"),
        ("Helios", "Helios"),
        ("", ""),
        ("a=b", "a=b"),
    ],
)
def test_csv_cell(value: str, cell: str) -> None:
    assert csv_cell(value) == cell


def test_csv_no_personal_details(staff: Console) -> None:
    fired_on(staff.world, TODAY)
    fired_on(staff.world, TODAY)

    answer = staff.get(CSV)

    assert len(rows(answer)) == 2
    for detail in (TEST_NAME, TEST_EMAIL, TEST_PHONE, TEST_PHONE_DIGITS, "AC-"):
        assert detail not in answer.text


def test_csv_no_store(staff: Console) -> None:
    assert staff.get(CSV).headers["cache-control"] == "no-store"


# --- who can reach them ----------------------------------------------------------------------


@pytest.mark.parametrize("path", [LOG, CSV])
def test_firing_log_not_in_group_not_allowed(console: Console, path: str) -> None:
    fired_on(console.world, TODAY)
    console.sign_in(groups=("front-desk",), username=OUTSIDER)

    answer = console.get(path)

    assert answer.status_code == 403
    assert "text/csv" not in answer.headers["content-type"]
    assert STAFF not in answer.text


def test_firing_log_signed_out_redirects(console: Console) -> None:
    answer = console.get(LOG)

    assert answer.status_code in (302, 303)
    assert answer.headers["location"].startswith("/console/auth/sign-in")


def test_csv_signed_out_redirects(console: Console) -> None:
    fired_on(console.world, TODAY)

    answer = console.get(CSV)

    assert answer.status_code in (302, 303)
    assert "text/csv" not in answer.headers.get("content-type", "")
    assert STAFF not in answer.text


# --- the notes column (#42's "number of notes", from #17) ----------------------------------


def note_on(console: Console, load_id: LoadId, ruling: Ruling | None) -> None:
    note = NoteInput("Made-up note for the count.", (), (), ruling)
    console.world.write_note(load_id, note, STAFF_MEMBER)


def test_notes_column(staff: Console) -> None:
    noted = fired_on(staff.world, TODAY)
    quiet = fired_on(staff.world, TODAY)
    note_on(staff, noted, Ruling.NOT_ALLOWED)
    note_on(staff, noted, Ruling.ALLOWED)
    note_on(staff, noted, None)

    answer = staff.get(LOG)

    assert '<th scope="col">Notes</th>' in answer.text
    last = r"<td>([0-9]+)(?: <span class=\"tag tag-not-allowed\">✕ ([0-9]+).*?</span></span>)?</td>\s*</tr>"
    cells = re.findall(last, answer.text)
    assert listed(answer) == [quiet, noted]
    assert cells == [("0", ""), ("3", "1")]
    assert "✕ 1 not allowed" in text(answer)


def test_notes_column_counts_a_note_added_long_after_the_firing(staff: Console) -> None:
    load_id = fired_on(staff.world, TODAY)
    staff.world.clock.advance(timedelta(days=200))
    note_on(staff, load_id, Ruling.NOT_ALLOWED)

    (row,) = rows(staff.get(f"{CSV}?from=2026-11-01&to=2026-11-30"))

    assert (row["notes"], row["not allowed notes"]) == ("1", "1")


def test_csv_notes_columns(staff: Console) -> None:
    noted = fired_on(staff.world, TODAY)
    note_on(staff, noted, Ruling.NOT_ALLOWED)
    note_on(staff, noted, Ruling.ALLOWED_WITH_CONDITIONS)
    removed = staff.world.write_note(noted, NoteInput("Made-up note, removed.", (), (), None), STAFF_MEMBER)
    staff.world.remove_note(noted, removed.id, removed.version, STAFF_MEMBER)

    (row,) = rows(staff.get(CSV))

    assert CSV_COLUMNS[-2:] == ("notes", "not allowed notes")
    assert (row["notes"], row["not allowed notes"]) == ("2", "1")
    assert "Made-up note" not in staff.get(CSV).text  # counts only, never a note's text
