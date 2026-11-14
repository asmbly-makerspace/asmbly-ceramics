"""The botocore settings phase 7's composition root builds every client with.

botocore's defaults (60 s to connect, 60 s per read, and up to 10 tries for DynamoDB)
outlast API Gateway's 30 s and the web functions' 29 s timeout, so a slow AWS call would
end as a gateway timeout with nothing logged. With these, one call gives up in at most
`TOTAL_MAX_ATTEMPTS * (CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS)` seconds plus
botocore's short backoff (under 30 s), and the adapter logs and raises its port's
error. `READ_TIMEOUT_SECONDS` is per socket read, not for a whole response, so a 10 MB
photo still downloads.

SES is the exception: `mailer.SES_CLIENT_CONFIG` makes one attempt (a retried send may
have been sent twice), with the same connect timeout and a longer read for a large
message.
"""

from botocore.config import Config

CONNECT_TIMEOUT_SECONDS = 2
READ_TIMEOUT_SECONDS = 4
TOTAL_MAX_ATTEMPTS = 3

CLIENT_CONFIG = Config(
    connect_timeout=CONNECT_TIMEOUT_SECONDS,
    read_timeout=READ_TIMEOUT_SECONDS,
    retries={"total_max_attempts": TOTAL_MAX_ATTEMPTS, "mode": "standard"},
)
"""For the DynamoDB, S3 and SSM clients."""
