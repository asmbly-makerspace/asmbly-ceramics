"""Weekly counts (#7): Monday to Sunday, Austin time, and the overdue drop-offs first.

A read: logs nothing. A `week` that isn't a date shows the current week; any date shows
the week that holds it (`WeeklyCounts` finds its Monday).
"""

from collections.abc import Mapping
from datetime import timedelta

from starlette.requests import Request
from starlette.responses import Response

from asmbly_ceramics.domain.ids import ItemId
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.mail.compose import austin_day
from asmbly_ceramics.use_cases.studio import DELETED_ITEM
from asmbly_ceramics.web.console.auth import require_staff
from asmbly_ceramics.web.console.common import parse_date, render, services

_WEEK = timedelta(days=7)


async def counts_page(request: Request) -> Response:
    staff = require_staff(request)
    console = services(request)
    try:
        view = console.weekly_counts(parse_date(request.query_params.get("week")))
        previous, following = view.counts.week.monday - _WEEK, view.counts.week.monday + _WEEK
    except OverflowError:  # a week at the calendar's edge: show this week
        view = console.weekly_counts(None)
        previous, following = view.counts.week.monday - _WEEK, view.counts.week.monday + _WEEK
    counts = view.counts
    week = counts.week

    def named(which: CatalogList, numbers: Mapping[ItemId, int]) -> list[tuple[str, int]]:
        return sorted(
            ((view.names.get((which, id), DELETED_ITEM), n) for id, n in numbers.items()),
            key=lambda pair: pair[0].casefold(),
        )

    firing = sorted(
        (
            (view.names.get((CatalogList.FIRING_TYPES, id), DELETED_ITEM), n, counts.pieces.get(id, 0))
            for id, n in counts.drop_offs.items()
        ),
        key=lambda row: row[0].casefold(),
    )
    context = {
        "tab": "counts",
        "view": view,
        "week_label": f"{austin_day(week.monday)} to {austin_day(week.sunday())}",
        "previous": previous.isoformat(),
        "next": following.isoformat(),
        "firing": firing,
        "kilns": named(CatalogList.KILNS, counts.loads),
        "reasons": named(CatalogList.REASONS, counts.rejections),
        "total_drop_offs": sum(counts.drop_offs.values()),
        "total_pieces": sum(counts.pieces.values()),
    }
    return render(request, "console/counts.html", context, staff)
