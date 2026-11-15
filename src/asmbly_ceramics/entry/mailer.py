"""The mailer's Lambda handler: one call of `SendPendingEmail` for each stream record.

The event-source mapping (`infra/app.yaml`) passes only new images whose `type` is
`email` and `status` is `pending`. The handler reads each record's `Keys`, never its
image's fields, and turns them into the email's key with `keys.parse_email_key`.

- A key that isn't an email's is logged as `mailer_bad_key` (no key text) and skipped.
- `SendPendingEmail` marks a failed send `failed` and logs `email_failed` itself; that
  isn't retried by Lambda, since the send may have half happened.
- Any other exception (the email couldn't be read or claimed) reports the record in
  `batchItemFailures`, so Lambda tries it again, and logs `mailer_crashed` with the
  exception's class only.
- A failure to start (the settings, the clients) logs `mailer_start_failed` with a code
  only (`entry.failure_code`) and raises `MailerStartFailed` holding only that, so
  Lambda retries the whole batch and its traceback never carries an error's own text.
"""

import logging
from typing import Any

from asmbly_ceramics.adapters.aws.keys import parse_email_key
from asmbly_ceramics.entry import failure_code
from asmbly_ceramics.ports.errors import error_code
from asmbly_ceramics.use_cases.emails import SendPendingEmail
from asmbly_ceramics.use_cases.log import log_event

_sender: SendPendingEmail | None = None


class MailerStartFailed(Exception):  # noqa: N818  # named for what happened, like CloseAborted
    """The mailer couldn't start; holds a code, never an error's text."""

    def __init__(self, code: str) -> None:
        super().__init__(f"the mailer couldn't start: {code}")
        self.code = code


def sender() -> SendPendingEmail:
    """Built on the first record of a container, then kept."""
    global _sender
    if _sender is None:
        from asmbly_ceramics.composition import build_mailer
        from asmbly_ceramics.logs import configure_logging
        from asmbly_ceramics.settings import Settings

        settings = Settings.from_environment()
        configure_logging(settings.log_level, settings.version)
        _sender = build_mailer(settings)
    return _sender


def handler(event: dict[str, Any], context: object) -> dict[str, list[dict[str, str]]]:
    """For each stream record, send its email; report the ones that failed to retry."""
    try:
        send = sender()
    except Exception as error:  # by code only: the text can quote a setting's value
        code = failure_code(error)
        log_event("mailer_start_failed", level=logging.ERROR, error_code=code)
        raise MailerStartFailed(code) from None
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        stream = record.get("dynamodb") or {}
        try:
            drop_off_id, kind, occasion = parse_email_key(stream.get("Keys") or {})
        except ValueError:
            log_event("mailer_bad_key", level=logging.WARNING)
            continue
        try:
            send(drop_off_id, kind, occasion)
        except Exception as error:  # by class only: the text can quote a record
            log_event(
                "mailer_crashed",
                level=logging.ERROR,
                drop_off_id=str(drop_off_id),
                error_code=error_code(type(error).__name__),
            )
            failures.append({"itemIdentifier": str(stream.get("SequenceNumber", ""))})
    return {"batchItemFailures": failures}
