"""A web request's deadline, shared by the web layer that sets it and the AWS clients
that check it (standard library only).

The form's use cases run synchronously on the event loop, so an `asyncio` timeout can't
stop one, and `adapters.aws.clients.CLIENT_CONFIG` bounds each AWS call, not a request:
a submit makes some forty calls in a row. So `web.app.RequestDeadline` starts the clock
when a request arrives, and `adapters.aws.deadline` refuses to send another AWS request
once it has passed. The adapters report that as their port's `Unavailable`, which the
page answers with its "try again" 503 and a logged line, before Lambda's 29 s and API
Gateway's 30 s run out with nothing logged.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

REQUEST_BUDGET_SECONDS = 14.0
"""From the request's start to the last AWS request its work may send."""

CLEANUP_BUDGET_SECONDS = 22.0
"""From the request's start to the last AWS request a cleanup may send (`cleanup()`): a
submit cut off after keeping photos still deletes them, so no photo is left without a
record (#7, decision 0004). One attempt takes at most `clients.CONNECT_TIMEOUT_SECONDS` +
`clients.READ_TIMEOUT_SECONDS` (6 s), so a request ends by about 28 s, under the
function's 29 s."""

_deadlines: ContextVar[tuple[float, float] | None] = ContextVar("asmbly_ceramics_deadlines", default=None)
_cleaning_up: ContextVar[bool] = ContextVar("asmbly_ceramics_cleaning_up", default=False)


def passed(clock: Callable[[], float] = time.monotonic) -> bool:
    """True once the current request's deadline has passed (the later, cleanup one inside
    `cleanup()`); False outside a request."""
    deadlines = _deadlines.get()
    if deadlines is None:
        return False
    work, cleanup_ = deadlines
    return clock() >= (cleanup_ if _cleaning_up.get() else work)


@contextmanager
def request_deadline(
    seconds: float = REQUEST_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    cleanup_seconds: float = CLEANUP_BUDGET_SECONDS,
) -> Iterator[None]:
    """Everything inside runs under one deadline, `seconds` from now."""
    start = clock()
    token = _deadlines.set((start + seconds, start + max(seconds, cleanup_seconds)))
    try:
        yield
    finally:
        _deadlines.reset(token)


@contextmanager
def cleanup() -> Iterator[None]:
    """AWS requests inside undo what the request already wrote: they get the cleanup
    deadline instead of the work's."""
    token = _cleaning_up.set(True)
    try:
        yield
    finally:
        _cleaning_up.reset(token)
