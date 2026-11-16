"""`IdNumbers` on the records table: one atomic counter per kind.

`ADD` on a number creates it at the added value, so the first call returns 1 (`AC-1`).
An atomic counter isn't idempotent (AWS's "Working with items and attributes"): a call
retried after DynamoDB applied it skips a number. #2 asks for IDs that are never shared,
not for no gaps, and uniqueness doesn't rest on the counter alone: a drop-off is written
under `attribute_not_exists(PK)`, so even a reset counter can't overwrite one.
"""

from typing import TYPE_CHECKING, Any

from botocore.exceptions import BotoCoreError, ClientError

from asmbly_ceramics.adapters.aws import keys
from asmbly_ceramics.adapters.aws.errors import log_aws_error
from asmbly_ceramics.domain.ids import DropOffId, LoadId, NoteId
from asmbly_ceramics.ports.errors import IdsUnavailable

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
else:
    DynamoDBClient = Any

DROP_OFF_COUNTER = "dropoff"
"""The drop-off counter's name (`COUNTER#dropoff`); the form's IAM grant names it too."""
LOAD_COUNTER = "load"
"""The load counter's name (`COUNTER#load`); the console's IAM grant names it too."""
NOTE_COUNTER = "note"
"""The note counter's name (`COUNTER#note`); the console's IAM grant names it too."""


class DynamoDbIdNumbers:
    def __init__(self, client: DynamoDBClient, table: str) -> None:
        self._client = client
        self._table = table

    def next_drop_off_id(self) -> DropOffId:
        return DropOffId(self._next(DROP_OFF_COUNTER))

    def next_load_id(self) -> LoadId:
        return LoadId(self._next(LOAD_COUNTER))

    def next_note_id(self) -> NoteId:
        return NoteId(self._next(NOTE_COUNTER))

    def _next(self, which: str) -> int:
        try:
            response = self._client.update_item(
                TableName=self._table,
                Key=keys.counter_key(which),
                UpdateExpression="ADD next_number :one SET #t = :type",
                ExpressionAttributeNames={"#t": "type"},
                ExpressionAttributeValues={":one": {"N": "1"}, ":type": {"S": keys.COUNTER}},
                ReturnValues="UPDATED_NEW",
            )
        except (ClientError, BotoCoreError) as error:
            raise IdsUnavailable(log_aws_error("update_item", error)) from None
        try:
            return int(response["Attributes"]["next_number"]["N"])
        except KeyError, ValueError:
            raise IdsUnavailable("UnexpectedResponse") from None
