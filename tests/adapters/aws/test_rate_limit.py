"""`DynamoDbRateLimiter`'s requests, races and failures."""

import logging
from datetime import timedelta
from typing import Any

import pytest
from botocore.stub import Stubber

from asmbly_ceramics.adapters.aws.rate_limit import TRIES, DynamoDbRateLimiter
from asmbly_ceramics.domain.limits import DEVICE_LIMIT, RateLimit
from asmbly_ceramics.ports.errors import RecordsUnavailable
from tests.adapters.conftest import TABLE, a_client, assert_nothing_holds
from tests.domain.builders import NOW

KEY = "made-up-keyed-hash"
ITEM_KEY = {"PK": {"S": f"RATE#{KEY}"}, "SK": {"S": "META"}}
NOW_US = int(NOW.timestamp()) * 1_000_000


def stored(version: int, hits: list[int]) -> dict[str, Any]:
    return {
        "Item": {**ITEM_KEY, "version": {"N": str(version)}, "hits": {"L": [{"N": str(h)} for h in hits]}}
    }


def test_hit_reads_consistently_and_puts_with_the_version_condition_and_ttl() -> None:
    client = a_client("dynamodb")
    earlier = NOW_US - 60_000_000
    gone = NOW_US - 11 * 60_000_000  # outside the 10 minutes
    with Stubber(client) as stubber:
        stubber.add_response(
            "get_item",
            stored(3, [gone, earlier]),
            {"TableName": TABLE, "Key": ITEM_KEY, "ConsistentRead": True},
        )
        stubber.add_response(
            "put_item",
            {},
            {
                "TableName": TABLE,
                "Item": {
                    **ITEM_KEY,
                    "type": {"S": "rate"},
                    "version": {"N": "4"},
                    "hits": {"L": [{"N": str(earlier)}, {"N": str(NOW_US)}]},
                    "ttl": {"N": str(int((NOW + timedelta(minutes=10, days=1)).timestamp()))},
                },
                "ConditionExpression": "attribute_not_exists(PK) OR #v = :v",
                "ExpressionAttributeNames": {"#v": "version"},
                "ExpressionAttributeValues": {":v": {"N": "3"}},
            },
        )
        assert DynamoDbRateLimiter(client, TABLE).hit(KEY, DEVICE_LIMIT, NOW)


def test_item_keeps_at_most_limit_hits() -> None:
    client = a_client("dynamodb")
    small = RateLimit(limit=2, window=timedelta(minutes=10))
    hits = [NOW_US - 3_000_000, NOW_US - 2_000_000]
    written: list[Any] = []
    with Stubber(client) as stubber:
        stubber.add_response("get_item", stored(1, hits))
        stubber.add_response("put_item", {})
        client.meta.events.register(
            "provide-client-params.dynamodb.PutItem",
            lambda params, **_: written.append(params["Item"]["hits"]),
        )
        assert not DynamoDbRateLimiter(client, TABLE).hit(KEY, small, NOW)
    assert written == [{"L": [{"N": str(NOW_US - 2_000_000)}, {"N": str(NOW_US)}]}]


def test_a_version_conflict_is_retried_then_fails_closed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    client = a_client("dynamodb")
    with Stubber(client) as stubber:
        stubber.add_response("get_item", {})
        stubber.add_client_error("put_item", service_error_code="ConditionalCheckFailedException")
        stubber.add_response("get_item", stored(1, [NOW_US - 1]))
        stubber.add_response("put_item", {})
        assert DynamoDbRateLimiter(client, TABLE).hit(KEY, DEVICE_LIMIT, NOW)  # the second try lands
        for _ in range(TRIES):
            stubber.add_response("get_item", {})
            stubber.add_client_error("put_item", service_error_code="ConditionalCheckFailedException")
        with pytest.raises(RecordsUnavailable) as raised:
            DynamoDbRateLimiter(client, TABLE).hit(KEY, DEVICE_LIMIT, NOW)
        stubber.assert_no_pending_responses()
    assert raised.value.code == "ConditionalCheckFailedException"
    assert_nothing_holds(caplog.records, KEY)


@pytest.mark.parametrize("operation", ["get_item", "put_item"])
def test_outage_fails_closed_with_records_unavailable(
    operation: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    client = a_client("dynamodb")
    message = "Request failed for key " + KEY
    with Stubber(client) as stubber:
        if operation == "put_item":
            stubber.add_response("get_item", {})
        stubber.add_client_error(operation, service_error_code="ThrottlingException", service_message=message)
        with pytest.raises(RecordsUnavailable) as raised:
            DynamoDbRateLimiter(client, TABLE).hit(KEY, DEVICE_LIMIT, NOW)
    assert raised.value.code == "ThrottlingException"
    assert message not in str(raised.value)
    assert_nothing_holds(caplog.records, KEY, message)


def test_a_malformed_item_fails_closed() -> None:
    client = a_client("dynamodb")
    with Stubber(client) as stubber:
        stubber.add_response("get_item", {"Item": {**ITEM_KEY, "hits": {"S": "nonsense"}}})
        with pytest.raises(RecordsUnavailable, match="UnexpectedItem"):
            DynamoDbRateLimiter(client, TABLE).hit(KEY, DEVICE_LIMIT, NOW)
