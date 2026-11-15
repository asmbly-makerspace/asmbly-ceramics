"""The daily close's Lambda handler (#7): one run of `CloseFinished` per invocation.

EventBridge Scheduler invokes it at 03:17 Austin time with `{}`; the event's content is
ignored. It logs nothing of its own: `CloseFinished` logs `drop_off_closed` (the ID only)
for each drop-off, `close_failed` (the ID and an error code) for each failure, and
`close_run` (the count) at the end. A run with any failure raises after it finishes, so
Lambda's asynchronous retries run it again (closing is idempotent) and, after them, the
event goes to the function's dead-letter queue, which is alarmed.

A failure before any drop-off is tried (the studio's read, the list) is logged as
`close_aborted` with its code (an `Unavailable`'s, which the adapters build from AWS's
error code), a `SettingsError`'s variable name, or its class name, and raised as
`CloseAborted` holding only that, so Lambda's traceback never carries an error's own
text.
"""

import logging
from collections.abc import Mapping

from asmbly_ceramics.ports.errors import Unavailable, error_code
from asmbly_ceramics.settings import SettingsError
from asmbly_ceramics.use_cases.close import CloseFinished
from asmbly_ceramics.use_cases.log import log_event

_closer: CloseFinished | None = None


class CloseRunError(Exception):
    """Some drop-offs couldn't be closed this run; their IDs are in the log."""

    def __init__(self, failed: int) -> None:
        super().__init__(f"{failed} drop-off(s) could not be closed")
        self.failed = failed


class CloseAborted(Exception):  # noqa: N818  # named for what happened, like the ports' errors
    """The run stopped before closing anything; holds a code, never an error's text."""

    def __init__(self, code: str) -> None:
        super().__init__(f"the close run stopped: {code}")
        self.code = code


def _code(error: Exception) -> str:
    """An `Unavailable`'s code; `SettingsError.TABLE_NAME` for a missing or malformed
    variable (its name only, never its value); else the class name."""
    if isinstance(error, Unavailable):
        return error.code
    if isinstance(error, SettingsError):
        return error_code(f"SettingsError.{error.variable}")
    return type(error).__name__


def closer() -> CloseFinished:
    """Built on the first invocation of a container, then kept."""
    global _closer
    if _closer is None:
        from asmbly_ceramics.composition import build_closer
        from asmbly_ceramics.logs import configure_logging
        from asmbly_ceramics.settings import Settings

        settings = Settings.from_environment()
        configure_logging(settings.log_level, settings.version)
        _closer = build_closer(settings)
    return _closer


def handler(event: Mapping[str, object], context: object) -> dict[str, int]:
    """Closes every drop-off whose pickup window has passed; `{"closed": n}`."""
    try:
        report = closer()()
    except Exception as error:
        code = _code(error)
        log_event("close_aborted", level=logging.ERROR, error_code=code)
        raise CloseAborted(code) from None
    if report.failed:
        raise CloseRunError(report.failed)
    return {"closed": len(report.closed)}
