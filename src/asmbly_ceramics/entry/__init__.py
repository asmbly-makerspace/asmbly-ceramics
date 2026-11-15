"""What Lambda starts: `run.sh` for the web functions (through the Lambda Web Adapter),
`mailer.handler` for the table's stream and `close.handler` for the daily close."""

from asmbly_ceramics.ports.errors import Unavailable, error_code
from asmbly_ceramics.settings import SettingsError


def failure_code(error: Exception) -> str:
    """What a handler logs and raises for a failure, never the error's own text: an
    `Unavailable`'s code; `SettingsError.TABLE_NAME` for a missing or malformed variable
    (its name only, never its value); else the class name."""
    if isinstance(error, Unavailable):
        return error.code
    if isinstance(error, SettingsError):
        return error_code(f"SettingsError.{error.variable}")
    return type(error).__name__
