import json
from unittest.mock import MagicMock
from botocore.exceptions import ClientError
import pytest

from consumer.models import WidgetRequest
from consumer.processor import RequestProcessor
from consumer.retriever import S3RequestRetriever, SqsRequestRetriever
from consumer.storage import DynamoDbWidgetStorage, S3WidgetStorage


# ==========================================
# 1. Models & Input Validation Tests
# ==========================================

def test_s3_key_formatting():
    req = WidgetRequest(
        type="WidgetCreateRequest",
        request_id="r-101",
        widget_id="w-999",
        owner="John Doe Smith",
    )
    assert req.get_s3_key() == "widgets/john-doe-smith/w-999"


def test_s3_key_formatting_whitespace_edge_cases():
    req = WidgetRequest(
        type="create",
        request_id="r-102",
        widget_id="w-123",
        owner="   Mary   Jane   Watson   ",
    )
    assert req.get_s3_key() == "widgets/mary-jane-watson/w-123"


def test_json_parsing_full_payload():
    raw_json = """{
        "type": "WidgetCreateRequest",
        "requestId": "req-1",
        "widgetId": "wid-1",
        "owner": "Alice Wonderland",
        "label": "Test Widget",
        "description": "A demo widget",
        "otherAttributes": [{"name": "color", "value": "red"}]
    }"""
    req = WidgetRequest.from_json(raw_json)
    assert req.type == "WidgetCreateRequest"
    assert req.request_id == "req-1"
    assert req.widget_id == "wid-1"
    assert req.owner == "Alice Wonderland"
    assert req.label == "Test Widget"
    assert req.description == "A demo widget"
    assert req.other_attributes == [{"name": "color", "value": "red"}]


def test_json_parsing_minimal_payload():
    raw_json = """{
        "type": "create",
        "requestId": "req-minimal",
        "widgetId": "wid-minimal",
        "owner": "Bob Builder"
    }"""
    req = WidgetRequest.from_json(raw_json)
    assert req.widget_id == "wid-minimal"
    assert req.label is None
    assert req.description is None
    assert req.other_attributes == []


def test_malformed_json_raises():
    with pytest.raises(json.JSONDecodeError):
        WidgetRequest.from_json("{not valid json")


def test_missing_required_field_raises():
    invalid_json = '{"type": "WidgetCreateRequest", "requestId": "r-1"}'
    with pytest.raises(ValueError):
        WidgetRequest.from_json(invalid_json)


# ==========================================
# 2. Storage Strategy Tests (Create, Update, Delete)
# ==========================================

def test_s3_storage_puts_expected_object():
    mock_s3 = MagicMock()
    storage = S3WidgetStorage(mock_s3, "target-web-bucket")

    req = WidgetRequest(
        type="create",
        request_id="req-123",
        widget_id="wid-456",
        owner="Alice Doe",
        label="Test",
        description="Desc",
    )
    storage.store_widget(req)

    mock_s3.put_object.assert_called_once()
    kwargs = mock_s3.put_object.call_args[1]
    assert kwargs["Bucket"] == "target-web-bucket"
    assert kwargs["Key"] == "widgets/alice-doe/wid-456"
    assert kwargs["ContentType"] == "application/json"

    body = json.loads(kwargs["Body"].decode("utf-8"))
    assert body["id"] == "wid-456"
    assert body["owner"] == "Alice Doe"


def test_s3_storage_delete_existing_and_missing():
    mock_s3 = MagicMock()
    storage = S3WidgetStorage(mock_s3, "target-web-bucket")
    req = WidgetRequest(type="delete", request_id="r-1", widget_id="w-1", owner="Alice Doe")

    # 1. Existing object
    storage.delete_widget(req)
    mock_s3.delete_object.assert_called_once_with(
        Bucket="target-web-bucket", Key="widgets/alice-doe/w-1"
    )

    # 2. Missing object (404) logs warning without raising
    mock_s3.reset_mock()
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
    )
    storage.delete_widget(req)
    mock_s3.delete_object.assert_not_called()


def test_s3_storage_update_merges_and_clears_empty_strings():
    mock_s3 = MagicMock()
    existing_payload = json.dumps({
        "id": "w-1",
        "owner": "Alice Doe",
        "label": "Old Label",
        "description": "Keep Me",
        "otherAttributes": [
            {"name": "color", "value": "blue"},
            {"name": "size", "value": "small"},
        ],
    }).encode("utf-8")

    mock_body = MagicMock()
    mock_body.read.return_value = existing_payload
    mock_s3.get_object.return_value = {"Body": mock_body}

    storage = S3WidgetStorage(mock_s3, "target-web-bucket")
    update_req = WidgetRequest(
        type="update",
        request_id="r-2",
        widget_id="w-1",
        owner="Alice Doe",
        label="",  # Empty string -> clear to None
        description=None,  # None -> leave unchanged ("Keep Me")
        other_attributes=[
            {"name": "color", "value": "green"},  # Update existing
            {"name": "size", "value": ""},  # Empty string -> remove attribute
        ],
    )
    storage.update_widget(update_req)

    mock_s3.put_object.assert_called_once()
    updated = json.loads(mock_s3.put_object.call_args[1]["Body"].decode("utf-8"))
    assert updated["id"] == "w-1"
    assert updated["owner"] == "Alice Doe"
    assert updated["label"] is None
    assert updated["description"] == "Keep Me"
    assert updated["otherAttributes"] == [{"name": "color", "value": "green"}]


def test_dynamodb_storage_flattening():
    mock_resource = MagicMock()
    mock_table = MagicMock()
    mock_resource.Table.return_value = mock_table

    storage = DynamoDbWidgetStorage(mock_resource, "widgets")
    req = WidgetRequest(
        type="create",
        request_id="r-2",
        widget_id="w-2",
        owner="Bob",
        other_attributes=[{"name": "size", "value": "large"}, {"name": "weight", "value": "10lbs"}],
    )
    storage.store_widget(req)

    mock_table.put_item.assert_called_once()
    called_item = mock_table.put_item.call_args[1]["Item"]
    assert called_item["id"] == "w-2"
    assert called_item["owner"] == "Bob"
    assert called_item["size"] == "large"
    assert called_item["weight"] == "10lbs"


def test_dynamodb_storage_delete_existing_and_missing():
    mock_resource = MagicMock()
    mock_table = MagicMock()
    mock_resource.Table.return_value = mock_table

    storage = DynamoDbWidgetStorage(mock_resource, "widgets")
    req = WidgetRequest(type="delete", request_id="r-1", widget_id="w-2", owner="Bob")

    # 1. Existing item deleted
    mock_table.delete_item.return_value = {"Attributes": {"id": "w-2"}}
    storage.delete_widget(req)
    mock_table.delete_item.assert_called_once_with(Key={"id": "w-2"}, ReturnValues="ALL_OLD")

    # 2. Missing item does not crash
    mock_table.delete_item.return_value = {}
    storage.delete_widget(req)


def test_dynamodb_storage_update_modifies_and_removes_empty():
    mock_resource = MagicMock()
    mock_table = MagicMock()
    mock_resource.Table.return_value = mock_table

    mock_table.get_item.return_value = {
        "Item": {
            "id": "w-2",
            "owner": "Bob",
            "label": "Old",
            "description": "Unchanged",
            "color": "red",
            "temp": "remove-me",
        }
    }

    storage = DynamoDbWidgetStorage(mock_resource, "widgets")
    update_req = WidgetRequest(
        type="update",
        request_id="r-3",
        widget_id="w-2",
        owner="Bob",
        label="New",
        description=None,
        other_attributes=[
            {"name": "color", "value": "blue"},
            {"name": "temp", "value": ""},
        ],
    )
    storage.update_widget(update_req)

    mock_table.put_item.assert_called_once()
    saved_item = mock_table.put_item.call_args[1]["Item"]
    assert saved_item["id"] == "w-2"
    assert saved_item["owner"] == "Bob"
    assert saved_item["label"] == "New"
    assert saved_item["description"] == "Unchanged"
    assert saved_item["color"] == "blue"
    assert "temp" not in saved_item


# ==========================================
# 3. Request Processor Branch Tests
# ==========================================

@pytest.mark.parametrize("create_type", ["create", "WidgetCreateRequest"])
def test_processor_routes_create(create_type):
    mock_storage = MagicMock()
    processor = RequestProcessor(mock_storage)
    req = WidgetRequest(type=create_type, request_id="1", widget_id="w-1", owner="Bob")
    processor.process(req)
    mock_storage.store_widget.assert_called_once_with(req)


@pytest.mark.parametrize("delete_type", ["delete", "WidgetDeleteRequest"])
def test_processor_routes_delete(delete_type):
    mock_storage = MagicMock()
    processor = RequestProcessor(mock_storage)
    req = WidgetRequest(type=delete_type, request_id="1", widget_id="w-1", owner="Bob")
    processor.process(req)
    mock_storage.delete_widget.assert_called_once_with(req)


@pytest.mark.parametrize("update_type", ["update", "WidgetUpdateRequest"])
def test_processor_routes_update(update_type):
    mock_storage = MagicMock()
    processor = RequestProcessor(mock_storage)
    req = WidgetRequest(type=update_type, request_id="1", widget_id="w-1", owner="Bob")
    processor.process(req)
    mock_storage.update_widget.assert_called_once_with(req)


def test_processor_handles_unknown_type():
    mock_storage = MagicMock()
    processor = RequestProcessor(mock_storage)
    bad_req = WidgetRequest(type="invalid_action", request_id="1", widget_id="2", owner="Bob")
    processor.process(bad_req)
    mock_storage.store_widget.assert_not_called()
    mock_storage.delete_widget.assert_not_called()
    mock_storage.update_widget.assert_not_called()


# ==========================================
# 4. S3 & SQS Retriever Tests
# ==========================================

def test_s3_retriever_empty_and_read():
    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.return_value = {}
    retriever = S3RequestRetriever(mock_s3, "test-bucket")
    assert retriever.poll_request() is None


def test_sqs_retriever_batches_caches_and_deletes():
    mock_sqs = MagicMock()
    mock_sqs.get_queue_url.return_value = {"QueueUrl": "https://sqs.us-east-1.amazonaws.com/123/cs5270-requests"}

    msg1_body = json.dumps({"type": "create", "requestId": "req-1", "widgetId": "w-1", "owner": "A"})
    msg2_body = json.dumps({"type": "delete", "requestId": "req-2", "widgetId": "w-2", "owner": "B"})

    mock_sqs.receive_message.return_value = {
        "Messages": [
            {"MessageId": "m-1", "ReceiptHandle": "rh-1", "Body": msg1_body},
            {"MessageId": "m-2", "ReceiptHandle": "rh-2", "Body": msg2_body},
        ]
    }

    retriever = SqsRequestRetriever(mock_sqs, "cs5270-requests")

    # First poll calls receive_message once, returns req-1
    r1 = retriever.poll_request()
    assert r1.request_id == "req-1"
    assert mock_sqs.receive_message.call_count == 1

    # Acknowledge req-1 deletes via rh-1
    retriever.acknowledge_request(r1)
    mock_sqs.delete_message.assert_called_once_with(
        QueueUrl="https://sqs.us-east-1.amazonaws.com/123/cs5270-requests",
        ReceiptHandle="rh-1",
    )

    # Second poll pulls from local cache without calling receive_message again
    r2 = retriever.poll_request()
    assert r2.request_id == "req-2"
    assert mock_sqs.receive_message.call_count == 1

    retriever.acknowledge_request(r2)
    assert mock_sqs.delete_message.call_count == 2