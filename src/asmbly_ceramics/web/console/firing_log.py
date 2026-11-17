"""The firing log (#42): fired loads by kiln, date range and kind, as each kiln's workbook
tab listed them, and the same rows as a CSV download.

Both are reads behind the `ceramics` check (`require_staff`): they change nothing, so the
filter form is a GET with no CSRF token, and they log nothing. Every query parameter is
checked here and never echoed or logged: the page drops a bad one with a message, and the
CSV, which has no page to say so on, answers 400 with that message. Rows hold staff
usernames, studio items, record values and note counts, never a person's details or a
note's text.

Kiln, firing type and cone names are typed by staff, so every CSV cell goes through
`csv_cell`, which stops a spreadsheet reading it as a formula (OWASP's "CSV Injection").
"""

import csv
import io
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import Response

from asmbly_ceramics.domain.errors import InvalidLogRange, UnknownItem
from asmbly_ceramics.domain.firing import RECORD_FIELDS, record_values
from asmbly_ceramics.domain.ids import ItemId, LoadId, is_item_id
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.mail.compose import austin_date
from asmbly_ceramics.use_cases.firing_log import FiringKind, FiringLogRow, FiringLogView
from asmbly_ceramics.use_cases.notes import NoteCount
from asmbly_ceramics.web.console.auth import require_staff
from asmbly_ceramics.web.console.common import parse_date, render, services
from asmbly_ceramics.web.console.services import ConsoleServices
from asmbly_ceramics.web.errors import PageError

PICK_KILN = "Pick a kiln from the list."
BAD_DATES = "Enter dates like 2026-11-13."
DASH = "\N{EN DASH}"  # a value that wasn't recorded
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
CSV_TYPE = "text/csv; charset=utf-8"
CSV_COLUMNS = (
    "load",
    "kiln",
    "firing type",
    "test",
    "date",
    "started at",
    "started by",
    "firing started at",
    "firing started by",
    "fired at",
    "fired by",
    *(field.replace("_", " ") for field in RECORD_FIELDS),
    "notes",
    "not allowed notes",
)
KINDS = {kind.value: kind for kind in FiringKind}
KIND_LABELS = ((FiringKind.ALL, "All"), (FiringKind.TESTS, "Tests only"), (FiringKind.REGULAR, "No tests"))


@dataclass(frozen=True)
class LogQuery:
    """The query parameters after their checks: what was refused is None (or `ALL`), with
    a message for each refusal."""

    kiln: ItemId | None
    start: date | None
    end: date | None
    kind: FiringKind
    problems: tuple[str, ...]

    def as_params(self) -> dict[str, str]:
        """The checked values, as the page's links pass them on: none was typed text."""
        params: dict[str, str] = {}
        if self.kiln is not None:
            params["kiln"] = self.kiln
        if self.start is not None:
            params["from"] = self.start.isoformat()
        if self.end is not None:
            params["to"] = self.end.isoformat()
        if self.kind is not FiringKind.ALL:
            params["kind"] = self.kind.value
        return params


def _query(params: Mapping[str, str]) -> LogQuery:
    problems: list[str] = []
    raw_kiln = params.get("kiln", "")
    kiln = ItemId(raw_kiln) if is_item_id(raw_kiln) else None
    if raw_kiln and kiln is None:
        problems.append(PICK_KILN)
    raw_from, raw_to = params.get("from", ""), params.get("to", "")
    start, end = parse_date(raw_from or None), parse_date(raw_to or None)
    if (raw_from and start is None) or (raw_to and end is None):
        problems.append(BAD_DATES)
        start = end = None
    kind = KINDS.get(params.get("kind", ""), FiringKind.ALL)
    return LogQuery(kiln, start, end, kind, tuple(problems))


def _read(console: ConsoleServices, query: LogQuery) -> tuple[LogQuery, FiringLogView]:
    """The log for `query`. A kiln the studio doesn't have falls back to every kiln, and a
    refused range to the default one, each with its message; each can happen once, so
    this reads at most three times."""
    try:
        return query, console.firing_log(query.kiln, query.start, query.end, query.kind)
    except UnknownItem:  # only for a kiln: with none, the use case never raises it
        return _read(console, replace(query, kiln=None, problems=(*query.problems, PICK_KILN)))
    except InvalidLogRange as refused:  # the default range is never refused
        return _read(
            console, replace(query, start=None, end=None, problems=(*query.problems, refused.message))
        )


# --- the page ------------------------------------------------------------------------------


def _or_dash(value: object, template: str = "{}") -> str:
    return DASH if value is None else template.format(value)


def _counts(console: ConsoleServices, view: FiringLogView) -> Mapping[LoadId, NoteCount]:
    """Each listed load's notes, from one read (`NoteCounts`)."""
    return console.note_counts([row.load for row in view.rows])


def _page_row(row: FiringLogRow, notes: NoteCount) -> dict[str, object]:
    load, record = row.load, row.load.record
    program = record.program
    cost = record_values(record)["cost"]  # dollars, as the record's form shows them
    return {
        "load": load,
        "kiln": row.kiln,
        "fired": DASH if load.fired_at is None else austin_date(load.fired_at.astimezone(STUDIO_TZ).date()),
        "firing_number": _or_dash(record.firing_number, "{:,}"),
        "full": _or_dash(record.percent_full, "{}%"),
        "cone": _or_dash(row.cone),
        "speed": DASH if program.speed is None else program.speed.value.capitalize(),
        "hold": _or_dash(program.hold_minutes, "{:,} min"),
        "max_temp": _or_dash(record.max_temp_f, "{:,} °F"),
        "cost": f"${cost}" if cost else DASH,
        "started_by": row.started_by,
        "fired_by": _or_dash(row.fired_by),
        "notes": notes.total,
        "not_allowed": notes.not_allowed,
    }


async def firing_log_page(request: Request) -> Response:
    staff = require_staff(request)
    console = services(request)
    studio = console.studio()
    query, view = _read(console, _query(request.query_params))
    counts = None
    if view.kiln is not None and view.counts is not None:
        counts = {
            "from": austin_date(view.counts.as_of.astimezone(STUDIO_TZ).date()),
            "since": f"{view.counts.since_elements:,}",
        }
    params = query.as_params()
    notes = _counts(console, view)
    context = {
        "tab": "firing-log",
        "log_view": "firings",
        "view": view,
        "kilns": studio.kilns,
        "kinds": KIND_LABELS,
        "problems": query.problems,
        "rows": [_page_row(row, notes[row.load.id]) for row in view.rows],
        "show_kiln": view.kiln is None,
        "counts": counts,
        # What the query gave, not the range read: a date field prefilled with today as
        # the end would, sent back, drop the loads dated ahead that the default read takes.
        "from_value": "" if query.start is None else query.start.isoformat(),
        "to_value": "" if query.end is None else query.end.isoformat(),
        "range": f"Dated {austin_date(view.start)} to "
        + (austin_date(view.end) if query.end is not None else "today, and any dated ahead"),
        "csv_url": "/console/firing-log.csv" + (f"?{urlencode(params)}" if params else ""),
    }
    return render(request, "console/firing_log.html", context, staff)


# --- the CSV -------------------------------------------------------------------------------


def csv_cell(value: str) -> str:
    """`value`, with `'` in front when a spreadsheet would read it as a formula: when it
    starts with `=`, `+`, `-`, `@`, a tab or a carriage return."""
    return "'" + value if value.startswith(FORMULA_STARTS) else value


def _iso(at: datetime | None) -> str:
    return "" if at is None else at.astimezone(STUDIO_TZ).isoformat(timespec="seconds")


def _csv_row(row: FiringLogRow, notes: NoteCount) -> list[str]:
    """One fired load. The record's cells are `record_values`' texts (H:MM, dollars, a
    witness cone's "none"), as its form shows them, but the cone by name; then how many
    notes it has, and how many of them say "not allowed"."""
    load = row.load
    values = record_values(load.record)
    cells = [
        str(load.id),
        row.kiln,
        row.firing_type,
        "yes" if load.test else "no",
        load.date.isoformat(),
        _iso(load.started_at),
        row.started_by,
        _iso(load.firing_started_at),
        row.firing_started_by or "",
        _iso(load.fired_at),
        row.fired_by or "",
        *((row.cone or "") if field == "cone" else values[field] for field in RECORD_FIELDS),
        str(notes.total),
        str(notes.not_allowed),
    ]
    return [csv_cell(cell) for cell in cells]


async def firing_log_csv(request: Request) -> Response:
    """The rows for the query, or 400 with the first refusal's message: a download can't
    show which filter was dropped, so it never falls back to another kiln or range."""
    require_staff(request)
    console = services(request)
    query = _query(request.query_params)
    if query.problems:
        raise PageError(400, query.problems[0])
    try:
        view = console.firing_log(query.kiln, query.start, query.end, query.kind)
    except UnknownItem:
        raise PageError(400, PICK_KILN) from None
    except InvalidLogRange as refused:
        raise PageError(400, refused.message) from None
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    notes = _counts(console, view)
    writer.writerows(_csv_row(row, notes[row.load.id]) for row in view.rows)
    # Built from the checked values only: an item ID's shape and two dates.
    name = f"firing-log-{view.kiln or 'all'}-{view.start.isoformat()}-{view.end.isoformat()}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"}
    return Response(out.getvalue(), media_type=CSV_TYPE, headers=headers)
