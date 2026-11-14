"""`RateLimiter` on the records table: one item per keyed hash, a rolling window.

The item holds the latest hits (epoch microseconds, oldest first), at most `limit.limit`
of them: only those can decide a later hit, so the item stays small under a flood. A hit
reads the item consistently and writes it back under a version check; a write that lost
a race reads again, at most `TRIES` times, then fails closed. The item's `ttl` is a day
after its window ends, so a lost item means no recent hits, which is true.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from botocore.exceptions import BotoCoreError, ClientError

from asmbly_ceramics.adapters.aws import keys
from asmbly_ceramics.adapters.aws.errors import log_aws_error
from asmbly_ceramics.domain.limits import RateLimit
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.use_cases.log import log_event

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
else:
    DynamoDBClient = Any

TRIES = 3
_LOST_RACE = "ConditionalCheckFailedException"
_TTL_AFTER_WINDOW = timedelta(days=1)


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _micros(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(microseconds=1)


class DynamoDbRateLimiter:
    def __init__(self, client: DynamoDBClient, table: str) -> None:
        self._client = client
        self._table = table

    def hit(self, key: str, limit: RateLimit, now: datetime) -> bool:
        if now.utcoffset() is None:
            raise ValueError("a rate limit's time is aware")
        item_key = keys.rate_key(key)
        now_us = _micros(now)
        start_us = _micros(now - limit.window)
        ttl = int((now + limit.window + _TTL_AFTER_WINDOW).timestamp())
        for _ in range(TRIES):
            version, hits = self._read(item_key)
            earlier = [at for at in hits if start_us < at <= now_us]
            allowed = len(earlier) < limit.limit
            kept = [*earlier, now_us][-limit.limit :]
            if self._write(item_key, version, kept, ttl):
                return allowed
        log_event("aws_call_failed", level=logging.WARNING, kind="put_item", error_code=_LOST_RACE)
        raise RecordsUnavailable(_LOST_RACE)

    def _read(self, item_key: keys.AttributeMap) -> tuple[int, list[int]]:
        try:
            response = self._client.get_item(TableName=self._table, Key=item_key, ConsistentRead=True)
        except (ClientError, BotoCoreError) as error:
            raise RecordsUnavailable(log_aws_error("get_item", error)) from None
        item = response.get("Item")
        if item is None:
            return 0, []
        try:
            return int(item["version"]["N"]), [int(hit["N"]) for hit in item["hits"]["L"]]
        except KeyError, ValueError, TypeError:
            raise RecordsUnavailable("UnexpectedItem") from None

    def _write(self, item_key: keys.AttributeMap, version: int, hits: list[int], ttl: int) -> bool:
        """False when another hit wrote the item first."""
        try:
            self._client.put_item(
                TableName=self._table,
                Item={
                    **item_key,
                    "type": {"S": keys.RATE},
                    "version": {"N": str(version + 1)},
                    "hits": {"L": [{"N": str(hit)} for hit in hits]},
                    "ttl": {"N": str(ttl)},
                },
                ConditionExpression="attribute_not_exists(PK) OR #v = :v",
                ExpressionAttributeNames={"#v": "version"},
                ExpressionAttributeValues={":v": {"N": str(version)}},
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == _LOST_RACE:
                return False
            raise RecordsUnavailable(log_aws_error("put_item", error)) from None
        except BotoCoreError as error:
            raise RecordsUnavailable(log_aws_error("put_item", error)) from None
        return True
