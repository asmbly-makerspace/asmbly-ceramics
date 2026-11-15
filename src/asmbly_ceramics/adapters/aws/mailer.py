"""`Mailer` on SES v2's `SendEmail`, with the photos as inline attachments.

`ports.mailer.REFUSED_CODES` are the codes a send fails with only when the message
certainly wasn't sent, which `SendPendingEmail` relies on to tell staff whether the
person may have the email. So:

- SES's own error responses (API_SendEmail.html) on the only try are `SendFailed(code)`;
  a throttle (manage-sending-quotas-errors.html) is retried here, with a short wait,
  since a refused send can safely be sent again;
- an error that came after botocore retried (`RetryAttempts > 0`) is
  `SendFailed("unknown")`: an earlier try may have timed out after SES took it. Phase 7
  builds the client with `SES_CLIENT_CONFIG` (one attempt), so this doesn't happen;
- a network error or timeout is `SendFailed(<its class name>)`, which `REFUSED_CODES`
  doesn't hold: it may have been sent.

Nothing logged holds the recipient, the subject, the body, an attachment or AWS's
message; the use case logs the drop-off's ID and the email's kind.
"""

import time
from collections.abc import Callable
from email.utils import formataddr
from typing import TYPE_CHECKING, Any

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from asmbly_ceramics.adapters.aws.clients import CONNECT_TIMEOUT_SECONDS
from asmbly_ceramics.adapters.aws.errors import log_aws_error, retry_attempts
from asmbly_ceramics.ports.errors import UNKNOWN_CODE
from asmbly_ceramics.ports.mailer import OutgoingEmail, SendFailed, check_outgoing

if TYPE_CHECKING:
    from mypy_boto3_sesv2.client import SESV2Client
    from mypy_boto3_sesv2.type_defs import AttachmentTypeDef
else:
    SESV2Client = Any
    AttachmentTypeDef = dict

SES_READ_TIMEOUT_SECONDS = 10
SES_CLIENT_CONFIG = Config(
    connect_timeout=CONNECT_TIMEOUT_SECONDS,
    read_timeout=SES_READ_TIMEOUT_SECONDS,
    retries={"total_max_attempts": 1, "mode": "standard"},
)
"""The client phase 7 builds for this adapter: one attempt, so a refused code is the
answer to the only try, with timeouts under API Gateway's 30 s (`clients`)."""

STREAM_SES_READ_TIMEOUT_SECONDS = 30
STREAM_SES_CLIENT_CONFIG = SES_CLIENT_CONFIG.merge(Config(read_timeout=STREAM_SES_READ_TIMEOUT_SECONDS))
"""The mailer's: it runs from the stream with no gateway and a 300 s timeout, so a slow
answer to a six-photo message gets 30 s before it becomes "may have been sent". Still
one attempt and the same connect timeout; the console's test email keeps
`SES_CLIENT_CONFIG`."""

# SES counts a message's size after base64 (quotas.html: 40 MB through the v2 API); kept
# well under it for the headers and the MIME parts.
MAX_ENCODED_BYTES = 38 * 1024 * 1024
TOO_LARGE = "MessageTooLarge"
THROTTLED = frozenset({"Throttling", "ThrottlingException", "TooManyRequestsException"})
TRIES = 3
BACKOFF_SECONDS = (1.0, 2.0)


def _encoded(size: int) -> int:
    return 4 * ((size + 2) // 3)


def encoded_size(message: OutgoingEmail) -> int:
    """The message's body and attachments after base64, which SES's limit counts."""
    body = len(message.html.encode()) + len(message.text.encode()) + len(message.subject.encode())
    return _encoded(body) + sum(_encoded(len(image.data)) for image in message.inline)


class SesMailer:
    def __init__(self, client: SESV2Client, sleep: Callable[[float], None] = time.sleep) -> None:
        self._client = client
        self._sleep = sleep

    def send(self, message: OutgoingEmail) -> None:
        check_outgoing(message)
        if encoded_size(message) > MAX_ENCODED_BYTES:
            raise SendFailed(TOO_LARGE)
        attachments: list[AttachmentTypeDef] = [
            {
                "FileName": image.filename,
                "RawContent": image.data,
                "ContentDisposition": "INLINE",
                "ContentId": image.content_id,
                "ContentType": image.content_type,
                "ContentTransferEncoding": "BASE64",
            }
            for image in message.inline
        ]
        for attempt in range(1, TRIES + 1):
            try:
                self._client.send_email(
                    FromEmailAddress=formataddr((message.from_name, message.from_address)),
                    Destination={"ToAddresses": [message.to]},
                    ReplyToAddresses=[message.reply_to],
                    Content={
                        "Simple": {
                            "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                            "Body": {
                                "Html": {"Data": message.html, "Charset": "UTF-8"},
                                "Text": {"Data": message.text, "Charset": "UTF-8"},
                            },
                            "Attachments": attachments,
                        }
                    },
                )
                return
            except ClientError as error:
                code = log_aws_error("send_email", error)
                if retry_attempts(error) > 0:
                    raise SendFailed(UNKNOWN_CODE) from None
                if code in THROTTLED and attempt < TRIES:
                    self._sleep(BACKOFF_SECONDS[attempt - 1])
                    continue
                raise SendFailed(code) from None
            except BotoCoreError as error:
                raise SendFailed(log_aws_error("send_email", error)) from None
