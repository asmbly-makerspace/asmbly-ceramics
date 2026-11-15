"""Every email needing attention, studio-wide (`GET /console/emails`) (#4, #7).

The only page that shows a fired drop-off whose ready email never went out once its load
has left the loads list. Its rows carry keys and states only: no name, address or
message.
"""

from starlette.requests import Request
from starlette.responses import Response

from asmbly_ceramics.domain.email import EmailStatus
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.mail.compose import austin_time
from asmbly_ceramics.use_cases.emails import EmailNeedingAttention
from asmbly_ceramics.web.console.auth import require_staff
from asmbly_ceramics.web.console.common import render, services
from asmbly_ceramics.web.console.dropoffs import DONE, KIND_LABELS


def row_state(row: EmailNeedingAttention) -> str:
    if row.status is EmailStatus.FAILED:
        return f"Sending failed ({row.error_code or 'unknown'})"
    if row.status is EmailStatus.SENDING:
        return "Stuck sending" if row.since is None else f"Stuck sending since {austin_time(row.since)}"
    return "Waiting to send" if row.since is None else f"Waiting to send since {austin_time(row.since)}"


async def emails_page(request: Request) -> Response:
    staff = require_staff(request)
    rows = services(request).emails_needing_attention()
    notice = None
    if request.query_params.get("done") == "retried":
        try:
            notice = DONE["retried"].format(id=DropOffId.parse(request.query_params.get("id", "")))
        except ValueError:
            notice = None
    context = {
        "rows": [(row, KIND_LABELS[row.kind], row_state(row)) for row in rows],
        "notice": notice,
    }
    return render(request, "console/emails.html", context, staff, attention=len(rows))
