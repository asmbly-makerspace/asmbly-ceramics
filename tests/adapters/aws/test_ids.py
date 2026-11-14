"""`DynamoDbIdNumbers`' requests and failures, on `Stubber`."""

import logging

import pytest
from botocore.stub import Stubber

from asmbly_ceramics.adapters.aws.ids import DynamoDbIdNumbers
from asmbly_ceramics.domain.ids import LoadId
from asmbly_ceramics.ports.errors import IdsUnavailable
from tests.adapters.conftest import TABLE, a_client, assert_nothing_holds

AWS_TEXT = "Throughput exceeded for a request from somebody"


def expected(which: str) -> dict[str, object]:
    return {
        "TableName": TABLE,
        "Key": {"PK": {"S": f"COUNTER#{which}"}, "SK": {"S": "META"}},
        "UpdateExpression": "ADD next_number :one SET #t = :type",
        "ExpressionAttributeNames": {"#t": "type"},
        "ExpressionAttributeValues": {":one": {"N": "1"}, ":type": {"S": "counter"}},
        "ReturnValues": "UPDATED_NEW",
    }


def test_next_drop_off_id_adds_one_and_formats_ac_n() -> None:
    client = a_client("dynamodb")
    with Stubber(client) as stubber:
        stubber.add_response("update_item", {"Attributes": {"next_number": {"N": "12"}}}, expected("dropoff"))
        assert str(DynamoDbIdNumbers(client, TABLE).next_drop_off_id()) == "AC-12"


def test_next_load_id_uses_its_own_counter() -> None:
    client = a_client("dynamodb")
    with Stubber(client) as stubber:
        stubber.add_response("update_item", {"Attributes": {"next_number": {"N": "4"}}}, expected("load"))
        assert DynamoDbIdNumbers(client, TABLE).next_load_id() == LoadId(4)


def test_counter_failure_raises_ids_unavailable(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    client = a_client("dynamodb")
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "update_item",
            service_error_code="ProvisionedThroughputExceededException",
            service_message=AWS_TEXT,
        )
        stubber.add_response("update_item", {"Attributes": {}})
        ids = DynamoDbIdNumbers(client, TABLE)
        with pytest.raises(IdsUnavailable) as raised:
            ids.next_drop_off_id()
        assert raised.value.code == "ProvisionedThroughputExceededException"
        with pytest.raises(IdsUnavailable, match="UnexpectedResponse"):
            ids.next_drop_off_id()
    assert_nothing_holds(caplog.records, AWS_TEXT)
