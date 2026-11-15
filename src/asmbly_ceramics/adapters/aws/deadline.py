"""Stops a client sending once the web request's deadline has passed (`asmbly_ceramics.deadline`).

botocore emits `before-send` before each attempt, retries included. Raising there stops
the call before that attempt is sent, and a `BotoCoreError` is what every adapter
already turns into its port's `Unavailable`, logged by its error code.

Two errors, because what they say differs: `DeadlinePassed` refuses a call's first
attempt, so nothing of that call reached AWS; `DeadlinePassedOnRetry` refuses a retry,
after an attempt that failed in a way that may still have landed (a read timeout), so
the adapters treat its outcome as unknown, exactly as they treat the failure it hides.
"""

from typing import Any

from botocore.exceptions import BotoCoreError

from asmbly_ceramics import deadline


class DeadlinePassed(BotoCoreError):  # noqa: N818 (its class name is the logged error code)
    fmt = "The request's deadline passed before this AWS request was sent"


class DeadlinePassedOnRetry(BotoCoreError):  # noqa: N818 (its class name is the logged error code)
    fmt = "The request's deadline passed before this AWS request was retried"


def attempt(request: Any) -> int:
    """The attempt's number from botocore's `amz-sdk-request: attempt=N; max=M` header;
    an unreadable header counts as a retry (the safe reading)."""
    headers = getattr(request, "headers", None) or {}
    value = headers.get("amz-sdk-request", b"")
    text = value.decode("ascii", "replace") if isinstance(value, bytes) else str(value)
    for part in text.split(";"):
        name, _, number = part.strip().partition("=")
        if name == "attempt" and number.isdigit():
            return int(number)
    return 2


def refuse_after_deadline(request: Any = None, **_: Any) -> None:
    if deadline.passed():
        if attempt(request) == 1:
            raise DeadlinePassed()
        raise DeadlinePassedOnRetry()


# What botocore's standard mode retries on, besides a caught exception and a 5xx.
_RETRIED_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "ThrottledException",
        "RequestThrottledException",
        "TooManyRequestsException",
        "ProvisionedThroughputExceededException",
        "TransactionInProgressException",
        "RequestLimitExceeded",
        "BandwidthLimitExceeded",
        "LimitExceededException",
        "RequestThrottled",
        "SlowDown",
        "PriorRequestNotComplete",
        "EC2ThrottledException",
        "RequestTimeout",
        "RequestTimeoutException",
    }
)


def refuse_retry_after_deadline(response: Any = None, caught_exception: Any = None, **_: Any) -> None:
    """Before botocore sleeps to retry: once the deadline has passed, no sleep and no
    retry. A failure that would be retried may have landed, so it is an unknown outcome;
    any other answer (a success, a refusal such as a failed condition) is left alone."""
    if not deadline.passed() or isinstance(caught_exception, DeadlinePassed | DeadlinePassedOnRetry):
        return  # nothing to stop, or our own refusal, which botocore raises as it is
    if caught_exception is not None:
        raise DeadlinePassedOnRetry()
    if response is not None:
        http, parsed = response
        status = getattr(http, "status_code", 200)
        code = parsed.get("Error", {}).get("Code") if isinstance(parsed, dict) else None
        if status >= 500 or code in _RETRIED_CODES:
            raise DeadlinePassedOnRetry()


def check_deadline(client: Any) -> None:
    """Registers the checks on every request `client` sends: before each attempt, and
    before a retry's sleep (which comes before the next attempt's `before-send`)."""
    # First, so no other handler (one that answers a request itself) runs before it.
    events = client.meta.events
    events.register_first("before-send", refuse_after_deadline, unique_id="asmbly-ceramics-deadline")
    events.register_first(
        "needs-retry", refuse_retry_after_deadline, unique_id="asmbly-ceramics-deadline-retry"
    )
