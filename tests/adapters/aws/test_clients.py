"""The client settings phase 7 builds every client with: a call gives up before API
Gateway's 30 seconds."""

from asmbly_ceramics.adapters.aws.clients import (
    CLIENT_CONFIG,
    CONNECT_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
    TOTAL_MAX_ATTEMPTS,
)
from asmbly_ceramics.adapters.aws.mailer import BACKOFF_SECONDS, SES_CLIENT_CONFIG

GATEWAY_SECONDS = 30
# Standard mode waits at most 2**n seconds (with jitter) before the n-th retry.
MOST_BACKOFF = sum(2**n for n in range(1, TOTAL_MAX_ATTEMPTS))


def test_one_call_gives_up_before_the_gateway() -> None:
    config = vars(CLIENT_CONFIG)
    assert config["connect_timeout"] == CONNECT_TIMEOUT_SECONDS
    assert config["read_timeout"] == READ_TIMEOUT_SECONDS
    assert config["retries"] == {"total_max_attempts": TOTAL_MAX_ATTEMPTS, "mode": "standard"}
    worst = TOTAL_MAX_ATTEMPTS * (CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS) + MOST_BACKOFF
    assert worst < GATEWAY_SECONDS


def test_a_send_gives_up_before_the_gateway() -> None:
    config = vars(SES_CLIENT_CONFIG)
    # One slow try (a timeout isn't retried) after the throttled ones, which answer at once.
    worst = config["connect_timeout"] + config["read_timeout"] + sum(BACKOFF_SECONDS)
    assert worst < GATEWAY_SECONDS
    assert config["connect_timeout"] < 60  # not botocore's default
    assert config["read_timeout"] < 60
