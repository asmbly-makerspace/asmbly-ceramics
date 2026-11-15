"""`Records` on one DynamoDB table (decision 0002), keyed as `keys` says.

Reads by key are strongly consistent. Lists query an index (eventually consistent: the
use cases re-read by key before they change anything) or the base table (consistent).
`commit` is one `TransactWriteItems`; what its failures mean is AWS's TransactWriteItems
page (https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html):

- a cancelled transaction writes nothing; a `ConditionalCheckFailed` or
  `TransactionConflict` reason is `Conflict`, naming the IDs whose items failed (the
  reasons come in the request's order);
- a call repeated with the same `ClientRequestToken` after it succeeded "returns
  successfully without making any changes", and botocore repeats a call with the same
  token when it retries, so a timeout it retried through isn't a second write;
- a timeout or lost connection (any botocore error but missing credentials or bad
  parameters, since botocore's own retries can hide a timed-out try),
  `TransactionInProgressException` (the first call is still
  running), `InternalServerError`, or any error that came after botocore retried may
  still land, even after a strongly consistent read finds nothing: `CommitOutcomeUnknown`.
"""

import logging
import uuid
from collections.abc import Collection, Iterator, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, ParamValidationError

from asmbly_ceramics import deadline
from asmbly_ceramics.adapters.aws import keys
from asmbly_ceramics.adapters.aws.deadline import DeadlinePassed
from asmbly_ceramics.adapters.aws.errors import log_aws_error, retry_attempts
from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.load import LIVE_STATUSES, Load, LoadStatus
from asmbly_ceramics.domain.studio import CatalogList, SettingChange, Studio
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import (
    MAX_CHANGES,
    BadCursor,
    Change,
    CommitOutcomeUnknown,
    Conflict,
    HistoryPage,
    Item,
    Put,
    Submission,
    Update,
)
from asmbly_ceramics.use_cases.log import log_event

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import TransactWriteItemTypeDef
else:
    DynamoDBClient = Any

_CONFLICT_REASONS = frozenset({"ConditionalCheckFailed", "TransactionConflict"})
# Answers that leave the outcome open (see the module's docstring).
_UNKNOWN_CODES = frozenset({"TransactionInProgressException", "InternalServerError"})
# botocore errors raised before any request left: nothing was sent. Any other botocore
# error may follow a retried timeout (botocore's retries hide the earlier tries), so it
# leaves the outcome open.
_NOT_SENT = (NoCredentialsError, ParamValidationError, DeadlinePassed)  # refused before sending
_ALL_STATES = tuple(DropOffState)
_REJECTION_STATES = (DropOffState.REJECTED, DropOffState.CLOSED)  # a rejection is kept on close
_ALL_STATUSES = tuple(LoadStatus)


class DynamoDbRecords:
    def __init__(self, client: DynamoDBClient, table: str) -> None:
        self._client = client
        self._table = table

    # Commit ---------------------------------------------------------------------------

    def commit(self, changes: Sequence[Change]) -> None:
        changes = tuple(changes)
        if not changes:
            return  # DynamoDB refuses an empty transaction; the contract's no-op
        if len(changes) > MAX_CHANGES:
            raise ValueError(f"at most {MAX_CHANGES} changes in one commit")
        stored_keys = [keys.item_key(change.item) for change in changes]
        seen = {(k["PK"]["S"], k["SK"]["S"]) for k in stored_keys}
        if len(seen) != len(stored_keys):
            raise ValueError("two changes on one key in one commit")
        actions = [_action(self._table, change, k) for change, k in zip(changes, stored_keys, strict=True)]
        try:
            self._client.transact_write_items(
                TransactItems=cast("list[TransactWriteItemTypeDef]", actions),
                ClientRequestToken=str(uuid.uuid4()),
            )
        except ClientError as error:
            raise _commit_error(error, changes) from None
        except BotoCoreError as error:
            code = log_aws_error("transact_write_items", error)
            if isinstance(error, _NOT_SENT):
                raise RecordsUnavailable(code) from None
            raise CommitOutcomeUnknown(code) from None

    # Reads by key ---------------------------------------------------------------------

    def drop_off(self, id: DropOffId) -> DropOff | None:
        return self._get(keys.drop_off_key(id), DropOff)

    def load(self, id: LoadId) -> Load | None:
        return self._get(keys.load_key(id), Load)

    def studio(self) -> Studio | None:
        return self._get(keys.studio_key(), Studio)

    def email(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> Email | None:
        return self._get(keys.email_key(drop_off_id, kind, occasion), Email)

    def submission(self, token_hash: str) -> Submission | None:
        # Under the cleanup deadline: a submit whose commit timed out re-reads it to
        # learn whether to delete the photos it kept (decision 0004).
        with deadline.cleanup():
            return self._get(keys.submission_key(token_hash), Submission)

    # Lists ----------------------------------------------------------------------------

    def drop_offs_in(self, states: Collection[DropOffState]) -> list[DropOff]:
        found = [
            d
            for state in _in_order(states, _ALL_STATES)
            for d in self._entities(DropOff, self._gsi1(keys.drop_off_partition(state)))
        ]
        return _by_created(found)

    def drop_offs_created_between(self, start: datetime, end: datetime) -> list[DropOff]:
        low, high = keys.iso(start), keys.iso(end)  # aware, else ValueError
        found = [
            d
            for state in _ALL_STATES
            for d in self._entities(DropOff, self._gsi1(keys.drop_off_partition(state), between=(low, high)))
            if start <= d.created_at < end
        ]
        return _by_created(found)

    def drop_offs_rejected_between(self, start: datetime, end: datetime) -> list[DropOff]:
        low, high = keys.iso(start), keys.iso(end)
        found = [
            d
            for state in _REJECTION_STATES
            for d in self._entities(
                DropOff,
                self._query(
                    IndexName=keys.GSI1,
                    KeyConditionExpression="GSI1PK = :pk",
                    FilterExpression="#at BETWEEN :low AND :high",
                    ExpressionAttributeNames={"#at": "rejection_at"},
                    ExpressionAttributeValues={
                        ":pk": {"S": keys.drop_off_partition(state)},
                        ":low": {"S": low},
                        ":high": {"S": high},
                    },
                ),
            )
            if d.rejection is not None and start <= d.rejection.at < end
        ]
        return _by_created(found)

    def loads_in(self, statuses: Collection[LoadStatus]) -> list[Load]:
        found = [
            load
            for status in _in_order(statuses, _ALL_STATUSES)
            for load in self._entities(Load, self._gsi1(keys.load_partition(status)))
        ]
        return sorted(found, key=lambda load: (load.date, load.id))

    def emails_for(self, drop_off_id: DropOffId) -> list[Email]:
        found = self._entities(
            Email,
            self._query(
                KeyConditionExpression="PK = :pk",
                ExpressionAttributeValues={":pk": {"S": keys.email_pk(drop_off_id)}},
                ConsistentRead=True,
            ),
        )
        return sorted(found, key=lambda e: e.created_at)

    def emails_in(self, statuses: Collection[EmailStatus]) -> list[Email]:
        found = [
            e
            for status in _in_order(statuses, tuple(EmailStatus))
            for e in self._entities(
                Email,
                self._query(
                    IndexName=keys.GSI2,
                    KeyConditionExpression="GSI2PK = :pk",
                    ExpressionAttributeValues={":pk": {"S": keys.email_partition(status)}},
                ),
            )
        ]
        return sorted(found, key=lambda e: e.created_at)

    def history(self, limit: int, before: str | None = None) -> HistoryPage:
        """Newest first by sort key. The cursor is the last change's sort key without
        `HISTORY#`, so changes at one instant (one save writes up to three) are never
        split or skipped: the next page starts strictly below it."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("history's limit is at least 1")
        if before is not None and not keys.is_history_cursor(before):
            raise BadCursor()
        if before is None:
            condition = "PK = :pk AND begins_with(SK, :prefix)"
            values = {":pk": {"S": keys.STUDIO_PK}, ":prefix": {"S": keys.HISTORY_PREFIX}}
        else:
            condition = "PK = :pk AND SK BETWEEN :prefix AND :below"
            values = {
                ":pk": {"S": keys.STUDIO_PK},
                ":prefix": {"S": keys.HISTORY_PREFIX},
                # BETWEEN is inclusive; the cursor's own item is the only key equal to it.
                ":below": {"S": keys.HISTORY_PREFIX + before},
            }
        items: list[Mapping[str, Any]] = []
        for item in self._query(
            KeyConditionExpression=condition,
            ExpressionAttributeValues=values,
            ScanIndexForward=False,
            ConsistentRead=True,
            Limit=limit + 2,  # a page, one more to know about older ones, and the cursor's own
        ):
            if before is not None and item["SK"]["S"] == keys.HISTORY_PREFIX + before:
                continue
            items.append(item)
            if len(items) > limit:
                break
        page = items[:limit]
        older = page[-1]["SK"]["S"].removeprefix(keys.HISTORY_PREFIX) if len(items) > limit else None
        changes = tuple(_entity(SettingChange, item) for item in page)
        return HistoryPage(changes, older)

    def is_item_used(self, which: CatalogList, id: ItemId) -> bool:
        drop_off_partitions = [keys.drop_off_partition(s) for s in _ALL_STATES]
        load_partitions = [keys.load_partition(s) for s in _ALL_STATUSES if s in LIVE_STATUSES]
        match which:
            case CatalogList.KILNS:
                searches = [(load_partitions, "kiln")]
            case CatalogList.FIRING_TYPES:
                searches = [(drop_off_partitions, "firing_type"), (load_partitions, "firing_type")]
            case CatalogList.GLAZE_TYPES:
                searches = [(drop_off_partitions, "glaze_type")]
            case CatalogList.REASONS:
                searches = [([keys.drop_off_partition(s) for s in _REJECTION_STATES], "rejection_reason")]
        return any(
            self._any_with(partition, attribute, id)
            for partitions, attribute in searches
            for partition in partitions
        )

    # Helpers --------------------------------------------------------------------------

    def _any_with(self, partition: str, attribute: str, value: str) -> bool:
        pages = self._pages(
            IndexName=keys.GSI1,
            KeyConditionExpression="GSI1PK = :pk",
            FilterExpression="#a = :v",
            ExpressionAttributeNames={"#a": attribute},
            ExpressionAttributeValues={":pk": {"S": partition}, ":v": {"S": value}},
            Select="COUNT",
        )
        return any(page.get("Count", 0) > 0 for page in pages)

    def _get[T](self, key: keys.AttributeMap, kind: type[T]) -> T | None:
        try:
            response = self._client.get_item(TableName=self._table, Key=key, ConsistentRead=True)
        except (ClientError, BotoCoreError) as error:
            raise RecordsUnavailable(log_aws_error("get_item", error)) from None
        item = response.get("Item")
        if item is None:
            return None
        entity = _parsed(item)
        return entity if isinstance(entity, kind) else None

    def _gsi1(self, partition: str, *, between: tuple[str, str] | None = None) -> Iterator[Mapping[str, Any]]:
        if between is None:
            return self._query(
                IndexName=keys.GSI1,
                KeyConditionExpression="GSI1PK = :pk",
                ExpressionAttributeValues={":pk": {"S": partition}},
            )
        low, high = between
        # `<time>#AC-n` sorts after `<time>`: BETWEEN keeps `start`'s items and drops
        # `end`'s, the half-open range; the caller filters again anyway.
        return self._query(
            IndexName=keys.GSI1,
            KeyConditionExpression="GSI1PK = :pk AND GSI1SK BETWEEN :low AND :high",
            ExpressionAttributeValues={":pk": {"S": partition}, ":low": {"S": low}, ":high": {"S": high}},
        )

    def _query(self, **kwargs: Any) -> Iterator[Mapping[str, Any]]:
        for page in self._pages(**kwargs):
            yield from page.get("Items", [])

    def _pages(self, **kwargs: Any) -> Iterator[Mapping[str, Any]]:
        """Every page of a query, following `LastEvaluatedKey` until it is gone."""
        start: Mapping[str, Any] | None = None
        while True:
            request = {"TableName": self._table, **kwargs}
            if start is not None:
                request["ExclusiveStartKey"] = start
            try:
                page = self._client.query(**request)
            except (ClientError, BotoCoreError) as error:
                raise RecordsUnavailable(log_aws_error("query", error)) from None
            yield page
            start = page.get("LastEvaluatedKey")
            if not start:
                return

    @staticmethod
    def _entities[T](kind: type[T], items: Iterator[Mapping[str, Any]]) -> list[T]:
        return [_entity(kind, item) for item in items]


def _parsed(item: Mapping[str, Any]) -> Item:
    """The item's entity; an item that doesn't parse is `RecordsUnavailable`, never a crash
    whose traceback could quote the item."""
    try:
        return keys.from_item(item)
    except KeyError, ValueError, TypeError:
        log_event("unexpected_item", level=logging.ERROR, error_code="UnexpectedItem")
        raise RecordsUnavailable("UnexpectedItem") from None


def _entity[T](kind: type[T], item: Mapping[str, Any]) -> T:
    entity = _parsed(item)
    if not isinstance(entity, kind):
        raise RecordsUnavailable("UnexpectedItem")
    return entity


def _action(table: str, change: Change, stored_key: keys.AttributeMap) -> dict[str, Any]:
    """A `Put` creates under `attribute_not_exists(PK)`; an `Update` puts the whole item
    under its version check. Either stores an entity at `version + 1`."""
    match change:
        case Put(item=item):
            version = item.version + 1 if isinstance(item, DropOff | Load | Email | Studio) else None
            return {
                "Put": {
                    "TableName": table,
                    "Item": keys.to_item(item, stored_key, version),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            }
        case Update(item=updated):
            return {
                "Put": {
                    "TableName": table,
                    "Item": keys.to_item(updated, stored_key, updated.version + 1),
                    "ConditionExpression": "#v = :expected",
                    "ExpressionAttributeNames": {"#v": "version"},
                    "ExpressionAttributeValues": {":expected": {"N": str(updated.version)}},
                }
            }


def _commit_error(error: ClientError, changes: Sequence[Change]) -> Exception:
    code = log_aws_error("transact_write_items", error)
    if code == "TransactionCanceledException":
        reasons = error.response.get("CancellationReasons", [])
        refused = [
            change
            for change, reason in zip(changes, reasons, strict=False)
            if reason.get("Code") in _CONFLICT_REASONS
        ]
        if refused:
            ids = dict.fromkeys(_conflict_id(change.item) for change in refused)  # in order, once each
            return Conflict([known for known in ids if known])
    if code in _UNKNOWN_CODES or retry_attempts(error) > 0:
        return CommitOutcomeUnknown(code)
    return RecordsUnavailable(code)


def _conflict_id(item: Item) -> str:
    """The drop-off or load ID a refused change names, as the fake gives it."""
    match item:
        case DropOff() | Load():
            return str(item.id)
        case Email() | Submission():
            return str(item.drop_off_id)
        case Studio() | SettingChange():
            return ""


def _in_order[T](wanted: Collection[T], every: tuple[T, ...]) -> list[T]:
    return [value for value in every if value in wanted]


def _by_created(drop_offs: list[DropOff]) -> list[DropOff]:
    return sorted(drop_offs, key=lambda d: (d.created_at, d.id))
