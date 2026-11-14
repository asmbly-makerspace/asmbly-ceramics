"""`DynamoDbRecords`' requests and failures, on botocore's `Stubber` (and moto where a real
table answers better). The contract suite (`tests/adapters/contract/`) covers behavior."""

import logging
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from botocore.exceptions import ConnectTimeoutError, NoCredentialsError, ReadTimeoutError
from botocore.stub import ANY, Stubber

from asmbly_ceramics.adapters.aws import keys
from asmbly_ceramics.adapters.aws.records import DynamoDbRecords
from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus, new_email
from asmbly_ceramics.domain.ids import DropOffId, LoadId
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import CommitOutcomeUnknown, Conflict, Put, Update
from tests.adapters.conftest import TABLE, a_client, assert_nothing_holds
from tests.domain.builders import NOW, TEST_EMAIL, TEST_NAME, a_drop_off, a_load

AWS_TEXT = "The conditional request failed for an item holding " + TEST_EMAIL


@pytest.fixture
def stubbed() -> Iterator[tuple[DynamoDbRecords, Stubber]]:
    client = a_client("dynamodb")
    with Stubber(client) as stubber:
        yield DynamoDbRecords(client, TABLE), stubber
        stubber.assert_no_pending_responses()


def item_of(entity: Any, version: int | None = 1) -> dict[str, Any]:
    return keys.to_item(entity, keys.item_key(entity), version)


def test_get_uses_consistent_reads(stubbed: tuple[DynamoDbRecords, Stubber]) -> None:
    records, stubber = stubbed
    stubber.add_response(
        "get_item",
        {"Item": item_of(a_drop_off(12))},
        {"TableName": TABLE, "Key": keys.drop_off_key(DropOffId(12)), "ConsistentRead": True},
    )
    stubber.add_response(
        "get_item", {}, {"TableName": TABLE, "Key": keys.load_key(LoadId(4)), "ConsistentRead": True}
    )
    assert records.drop_off(DropOffId(12)) == replace(a_drop_off(12), version=1)
    assert records.load(LoadId(4)) is None


def test_a_read_of_another_kind_under_a_key_is_none(stubbed: tuple[DynamoDbRecords, Stubber]) -> None:
    records, stubber = stubbed
    stubber.add_response("get_item", {"Item": item_of(a_load(1))})
    assert records.drop_off(DropOffId(1)) is None


def test_commit_new_uses_attribute_not_exists(stubbed: tuple[DynamoDbRecords, Stubber]) -> None:
    records, stubber = stubbed
    drop_off = a_drop_off(12)
    stubber.add_response(
        "transact_write_items",
        {},
        {
            "TransactItems": [
                {
                    "Put": {
                        "TableName": TABLE,
                        "Item": item_of(drop_off, 1),
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                }
            ],
            "ClientRequestToken": ANY,
        },
    )
    records.commit([Put(drop_off)])


def test_commit_update_checks_and_bumps_version(stubbed: tuple[DynamoDbRecords, Stubber]) -> None:
    records, stubber = stubbed
    load = replace(a_load(4), version=3)
    stubber.add_response(
        "transact_write_items",
        {},
        {
            "TransactItems": [
                {
                    "Put": {
                        "TableName": TABLE,
                        "Item": item_of(load, 4),
                        "ConditionExpression": "#v = :expected",
                        "ExpressionAttributeNames": {"#v": "version"},
                        "ExpressionAttributeValues": {":expected": {"N": "3"}},
                    }
                }
            ],
            "ClientRequestToken": ANY,
        },
    )
    records.commit([Update(load)])


def test_each_commit_sends_its_own_request_token() -> None:
    client = a_client("dynamodb")
    tokens: list[str] = []
    with Stubber(client) as stubber:
        for _ in range(2):
            stubber.add_response("transact_write_items", {})
        client.meta.events.register(
            "provide-client-params.dynamodb.TransactWriteItems",
            lambda params, **_: tokens.append(params["ClientRequestToken"]),
        )
        records = DynamoDbRecords(client, TABLE)
        records.commit([Put(a_drop_off(1))])
        records.commit([Put(a_drop_off(1))])
    assert len(tokens) == 2
    assert tokens[0] != tokens[1]
    assert all(len(token) == 36 for token in tokens)  # a UUID, within the 36 allowed


def test_commit_close_removes_personal_attributes() -> None:
    closed = replace(a_drop_off(1, DropOffState.CLOSED), version=2)
    item = item_of(closed, 3)
    for name in ("contact_name", "contact_email", "contact_phone", "rejection_message"):
        assert name not in item
    assert "rejection_reason" in item  # what the counts and `is_item_used` need stays
    assert TEST_EMAIL not in repr(item)
    assert TEST_NAME not in repr(item)


def test_commit_refuses_more_than_100_changes_before_calling_aws(
    stubbed: tuple[DynamoDbRecords, Stubber],
) -> None:
    records, _ = stubbed  # no response queued: any call would fail the test
    with pytest.raises(ValueError, match="100"):
        records.commit([Put(a_drop_off(n)) for n in range(1, 102)])


def test_commit_refuses_two_changes_on_one_key(stubbed: tuple[DynamoDbRecords, Stubber]) -> None:
    records, _ = stubbed
    with pytest.raises(ValueError, match="one key"):
        records.commit([Put(a_drop_off(1)), Update(replace(a_drop_off(1), version=1))])


def test_transaction_cancelled_maps_reasons_to_the_ids_that_conflicted(
    stubbed: tuple[DynamoDbRecords, Stubber], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    records, stubber = stubbed
    email = new_email(DropOffId(3), EmailKind.RECEIVED, NOW)
    stubber.add_client_error(
        "transact_write_items",
        service_error_code="TransactionCanceledException",
        service_message=AWS_TEXT,
        http_status_code=400,
        modeled_fields={
            "CancellationReasons": [
                {"Code": "None"},
                {"Code": "ConditionalCheckFailed", "Message": AWS_TEXT},
                {"Code": "TransactionConflict"},
            ]
        },
    )
    with pytest.raises(Conflict) as refused:
        records.commit([Put(a_drop_off(1)), Put(a_drop_off(2)), Put(email)])
    assert refused.value.ids == ("AC-2", "AC-3")
    assert AWS_TEXT not in str(refused.value)
    assert_nothing_holds(caplog.records, TEST_EMAIL)


def test_a_cancellation_for_another_reason_wrote_nothing_and_is_unavailable(
    stubbed: tuple[DynamoDbRecords, Stubber],
) -> None:
    records, stubber = stubbed
    stubber.add_client_error(
        "transact_write_items",
        service_error_code="TransactionCanceledException",
        modeled_fields={"CancellationReasons": [{"Code": "ThrottlingError"}]},
    )
    with pytest.raises(RecordsUnavailable) as raised:
        records.commit([Put(a_drop_off(1))])
    assert not isinstance(raised.value, CommitOutcomeUnknown)
    assert raised.value.code == "TransactionCanceledException"


@pytest.mark.parametrize(
    "code", ["ProvisionedThroughputExceededException", "ThrottlingException", "RequestLimitExceeded"]
)
def test_throttling_becomes_records_unavailable_and_logs_the_code_only(
    stubbed: tuple[DynamoDbRecords, Stubber], caplog: pytest.LogCaptureFixture, code: str
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    records, stubber = stubbed
    stubber.add_client_error("transact_write_items", service_error_code=code, service_message=AWS_TEXT)
    with pytest.raises(RecordsUnavailable) as raised:
        records.commit([Put(a_drop_off(1))])
    assert not isinstance(raised.value, CommitOutcomeUnknown)  # nothing was written
    assert raised.value.code == code
    [record] = [r for r in caplog.records if getattr(r, "event", "") == "aws_call_failed"]
    assert (vars(record)["kind"], vars(record)["error_code"]) == ("transact_write_items", code)
    assert_nothing_holds(caplog.records, TEST_EMAIL, AWS_TEXT)


@pytest.mark.parametrize("code", ["TransactionInProgressException", "InternalServerError"])
def test_an_answer_that_leaves_the_outcome_open_is_commit_outcome_unknown(
    stubbed: tuple[DynamoDbRecords, Stubber], code: str
) -> None:
    records, stubber = stubbed
    stubber.add_client_error("transact_write_items", service_error_code=code, http_status_code=500)
    with pytest.raises(CommitOutcomeUnknown) as raised:
        records.commit([Put(a_drop_off(1))])
    assert raised.value.code == code
    assert isinstance(raised.value, RecordsUnavailable)  # every caller of RecordsUnavailable copes


def test_an_error_after_botocores_retries_is_commit_outcome_unknown(
    stubbed: tuple[DynamoDbRecords, Stubber],
) -> None:
    # An earlier try may have timed out after DynamoDB took it.
    records, stubber = stubbed
    stubber.add_client_error(
        "transact_write_items",
        service_error_code="ThrottlingException",
        response_meta={"RetryAttempts": 2},
    )
    with pytest.raises(CommitOutcomeUnknown):
        records.commit([Put(a_drop_off(1))])


def raising(error: Exception) -> Any:
    def handler(**_: Any) -> None:
        raise error

    return handler


def test_a_timed_out_commit_is_commit_outcome_unknown() -> None:
    # TransactWriteItems' page: a timed-out request can be repeated with the same token;
    # until then it may land, even after a strongly consistent read found nothing.
    client = a_client("dynamodb")
    client.meta.events.register(
        "before-send.dynamodb.TransactWriteItems",
        raising(ReadTimeoutError(endpoint_url="https://dynamodb.us-east-2.amazonaws.com")),
    )
    with pytest.raises(CommitOutcomeUnknown) as raised:
        DynamoDbRecords(client, TABLE).commit([Put(a_drop_off(1))])
    assert raised.value.code == "ReadTimeoutError"


def test_a_connect_timeout_may_follow_a_retried_timeout_so_is_unknown() -> None:
    client = a_client("dynamodb")
    client.meta.events.register(
        "before-send.dynamodb.TransactWriteItems",
        raising(ConnectTimeoutError(endpoint_url="https://dynamodb.us-east-2.amazonaws.com")),
    )
    with pytest.raises(CommitOutcomeUnknown):
        DynamoDbRecords(client, TABLE).commit([Put(a_drop_off(1))])


def test_a_commit_without_credentials_wrote_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = a_client("dynamodb")
    client.meta.events.register("before-send.dynamodb.TransactWriteItems", raising(NoCredentialsError()))
    with pytest.raises(RecordsUnavailable) as raised:
        DynamoDbRecords(client, TABLE).commit([Put(a_drop_off(1))])
    assert not isinstance(raised.value, CommitOutcomeUnknown)
    assert raised.value.code == "NoCredentialsError"


def test_queries_follow_last_evaluated_key(stubbed: tuple[DynamoDbRecords, Stubber]) -> None:
    records, stubber = stubbed
    first, second = a_drop_off(2), a_drop_off(1)
    page_key = keys.drop_off_key(first.id)
    stubber.add_response(
        "query",
        {"Items": [item_of(first)], "LastEvaluatedKey": page_key},
        {
            "TableName": TABLE,
            "IndexName": "GSI1",
            "KeyConditionExpression": "GSI1PK = :pk",
            "ExpressionAttributeValues": {":pk": {"S": "DROPOFF#waiting"}},
        },
    )
    stubber.add_response(
        "query",
        {"Items": [item_of(second)]},
        {
            "TableName": TABLE,
            "IndexName": "GSI1",
            "KeyConditionExpression": "GSI1PK = :pk",
            "ExpressionAttributeValues": {":pk": {"S": "DROPOFF#waiting"}},
            "ExclusiveStartKey": page_key,
        },
    )
    assert [d.id for d in records.drop_offs_in({DropOffState.WAITING})] == [DropOffId(1), DropOffId(2)]


def test_base_table_queries_are_consistent(stubbed: tuple[DynamoDbRecords, Stubber]) -> None:
    records, stubber = stubbed
    stubber.add_response(
        "query",
        {"Items": []},
        {
            "TableName": TABLE,
            "KeyConditionExpression": "PK = :pk",
            "ExpressionAttributeValues": {":pk": {"S": "EMAIL#AC-1"}},
            "ConsistentRead": True,
        },
    )
    stubber.add_response(
        "query",
        {"Items": []},
        {
            "TableName": TABLE,
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :prefix)",
            "ExpressionAttributeValues": {":pk": {"S": "STUDIO"}, ":prefix": {"S": "HISTORY#"}},
            "ScanIndexForward": False,
            "ConsistentRead": True,
            "Limit": 7,
        },
    )
    assert records.emails_for(DropOffId(1)) == []
    assert records.history(5).changes == ()


def test_history_refuses_a_malformed_cursor_before_calling_aws(
    stubbed: tuple[DynamoDbRecords, Stubber],
) -> None:
    from asmbly_ceramics.ports.records import BadCursor

    records, _ = stubbed
    with pytest.raises(BadCursor):
        records.history(5, before="2026-11-13T18:30:00.000000Z#NOT-HEX-AT-ALL!")


@pytest.mark.parametrize(
    "call",
    [
        lambda r: r.drop_off(DropOffId(1)),
        lambda r: r.drop_offs_in({DropOffState.WAITING}),
        lambda r: r.emails_in({EmailStatus.PENDING}),
    ],
)
def test_a_read_failure_is_records_unavailable_with_the_code(
    stubbed: tuple[DynamoDbRecords, Stubber], call: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    records, stubber = stubbed
    operation = "get_item" if call.__code__.co_names[0] == "drop_off" else "query"
    stubber.add_client_error(operation, service_error_code="InternalServerError", service_message=AWS_TEXT)
    with pytest.raises(RecordsUnavailable) as raised:
        call(records)
    assert raised.value.code == "InternalServerError"
    assert AWS_TEXT not in str(raised.value)
    assert_nothing_holds(caplog.records, AWS_TEXT, TEST_EMAIL)


def test_an_unexpected_item_in_a_list_is_records_unavailable(
    stubbed: tuple[DynamoDbRecords, Stubber],
) -> None:
    records, stubber = stubbed
    stubber.add_response("query", {"Items": [item_of(a_load(1))]})
    with pytest.raises(RecordsUnavailable, match="UnexpectedItem"):
        records.drop_offs_in({DropOffState.WAITING})


def test_an_item_that_doesnt_parse_is_records_unavailable_not_a_crash(
    stubbed: tuple[DynamoDbRecords, Stubber],
) -> None:
    records, stubber = stubbed
    broken = item_of(a_drop_off(1))
    del broken["created_at"]
    stubber.add_response("get_item", {"Item": broken})
    with pytest.raises(RecordsUnavailable, match="UnexpectedItem") as raised:
        records.drop_off(DropOffId(1))
    assert raised.value.__suppress_context__
