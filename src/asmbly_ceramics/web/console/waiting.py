"""The waiting list (`GET /console`) and the search box (`POST /console/search`) (#3).

Search is a POST: its text is often part of a person's name, and in a URL it would stay in
the browser's history, in logs and in a `Referer`. It is never logged.
"""

from starlette.requests import Request
from starlette.responses import Response

from asmbly_ceramics.domain.ids import ItemId, is_item_id
from asmbly_ceramics.domain.search import QUERY_MAX
from asmbly_ceramics.use_cases.waiting import Found
from asmbly_ceramics.web.console.auth import require_staff, require_staff_post
from asmbly_ceramics.web.console.common import Staff, render, services

SEARCH_TEXT_MAX = QUERY_MAX  # the domain reads no more; longer is cut, not refused


def _page(
    request: Request, staff: Staff, *, firing: ItemId | None, query: str, found: Found | None
) -> Response:
    view = services(request).waiting_list(firing)
    return render(
        request,
        "console/waiting.html",
        {
            "view": view,
            "firing": firing,
            "query": query,
            "found": found,
            "tab": "waiting",
            "search_max": SEARCH_TEXT_MAX,
            "waiting_count": sum(view.totals.drop_offs.values()),
        },
        staff,
    )


async def waiting_page(request: Request) -> Response:
    staff = require_staff(request)
    raw = request.query_params.get("firing")
    firing = ItemId(raw) if raw is not None and is_item_id(raw) else None
    return _page(request, staff, firing=firing, query="", found=None)


async def search(request: Request) -> Response:
    staff, form = await require_staff_post(request)
    query = form.get("q", "")[:SEARCH_TEXT_MAX]
    if not query.strip():  # the box cleared and Find pressed: the plain list
        return _page(request, staff, firing=None, query="", found=None)
    found = services(request).find_drop_offs(query)
    return _page(request, staff, firing=None, query=query, found=found)
