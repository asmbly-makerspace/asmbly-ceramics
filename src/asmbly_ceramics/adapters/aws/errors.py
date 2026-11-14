"""The only way an adapter reports an AWS failure: by its error code.

AWS's error message can quote what was sent (an item's attributes, an address), so it
is never logged, raised or stored. A `ClientError` is reported by
`response["Error"]["Code"]`; any other exception (botocore's network errors) by its
class name.
"""

import logging

from botocore.exceptions import ClientError

from asmbly_ceramics.ports.errors import error_code
from asmbly_ceramics.use_cases.log import log_event


def aws_error_code(exc: BaseException) -> str:
    """The error's code, or the exception's class name; `unknown` for anything that isn't
    an error code's shape (`ports.errors.error_code`)."""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code")
        return error_code(code if isinstance(code, str) else "")
    return error_code(type(exc).__name__)


def retry_attempts(exc: ClientError) -> int:
    """How many times botocore retried before this error: 0 when it was the first answer."""
    attempts = exc.response.get("ResponseMetadata", {}).get("RetryAttempts", 0)
    return attempts if isinstance(attempts, int) else 0


def log_aws_error(operation: str, exc: BaseException, *, drop_off_id: str | None = None) -> str:
    """Logs one line, `aws_call_failed`, with the operation (`transact_write_items`) and the
    code; returns the code."""
    code = aws_error_code(exc)
    fields: dict[str, str | int] = {"kind": operation, "error_code": code}
    if drop_off_id is not None:
        fields["drop_off_id"] = drop_off_id
    log_event("aws_call_failed", level=logging.WARNING, **fields)
    return code
