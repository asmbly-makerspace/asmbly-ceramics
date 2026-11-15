"""JSON log lines for every deployed function, with fixed field names.

The field names are a contract with `infra/app.yaml`'s metric filters (`$.event`,
`$.level`): `level`, `logger`, `message`, `version` and `use_cases.log.LOG_FIELDS` (the
fields `log_event` passes in `extra`). Any other `extra` key is dropped, and so are a
record's arguments and its traceback: a library's formatted message or a traceback can
quote what was sent (a person's details, a token), so a line holds the message's
template only, and an exception only by its class name (`error_code`).
"""

import json
import logging
import sys
from typing import Any, TextIO

from asmbly_ceramics.use_cases.log import LOG_FIELDS

APP_LOGGER = "asmbly_ceramics"
WITHHELD = "(a library's message, withheld)"
UNSTRUCTURED_EVENT = "unstructured"  # a library's line, not `log_event`'s
BASE_FIELDS = ("level", "logger", "message", "version")
FIELDS = frozenset({*BASE_FIELDS, *LOG_FIELDS})
# Their debug output can hold request bodies (an item, a photo, a token).
LIBRARY_LOGGERS = ("botocore", "boto3", "urllib3", "s3transfer")


def _is_ours(record: logging.LogRecord) -> bool:
    return record.name == APP_LOGGER or record.name.startswith(APP_LOGGER + ".")


def _no_library_debug(record: logging.LogRecord) -> bool:
    """Below INFO, only the app's own lines: a library's debug output can hold what it
    handles (Pillow logs a photo's EXIF tags, location included; botocore a request)."""
    return record.levelno >= logging.INFO or _is_ours(record)


class JsonFormatter(logging.Formatter):
    def __init__(self, version: str) -> None:
        super().__init__()
        self.version = version

    def format(self, record: logging.LogRecord) -> str:
        # The template, never the arguments: `log_event`'s message is the event alone. A
        # library's message without arguments may have been formatted before logging
        # (an f-string holding what was sent), so it is withheld.
        if not isinstance(record.msg, str):
            message = type(record.msg).__name__
        elif _is_ours(record) or record.args:
            message = record.msg
        else:
            message = WITHHELD
        line: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "version": self.version,
        }
        for name in LOG_FIELDS:
            if name in record.__dict__:
                line[name] = record.__dict__[name]
        # Every line has an `event`, so a metric filter's `$.event != ...` matches a
        # library's line too (a JSON filter is false on a missing field).
        line.setdefault("event", UNSTRUCTURED_EVENT)
        if record.exc_info and record.exc_info[0] is not None and "error_code" not in line:
            line["error_code"] = record.exc_info[0].__name__
        return json.dumps(line, default=lambda value: type(value).__name__, separators=(",", ":"))


def configure_logging(level: str, version: str, stream: TextIO | None = None) -> None:
    """One handler on the root logger, writing JSON lines; any handler already there
    (Lambda's runtime installs one) is removed."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(version))
    handler.addFilter(_no_library_debug)
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    for name in LIBRARY_LOGGERS:
        library = logging.getLogger(name)
        if library.getEffectiveLevel() < logging.INFO:
            library.setLevel(logging.INFO)
    # uvicorn's own handlers would print its lines unformatted: send them to the root's.
    for name in ("uvicorn", "uvicorn.error"):
        server = logging.getLogger(name)
        server.handlers.clear()
        server.propagate = True
    # Its access log stays off (run.sh's --no-access-log): a line would hold the
    # client's address and the path. uvicorn logs it whenever the logger has a handler.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
