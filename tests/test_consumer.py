import pytest
from consumer.models import WidgetRequest
from consumer.storage import DynamoDbWidgetStorage
from unittest.mock import MagicMock
import json
from unittest.mock import MagicMock
import pytest
from consumer.models import WidgetRequest
from consumer.storage import S3WidgetStorage, DynamoDbWidgetStorage
from consumer.processor import RequestProcessor
from consumer.retriever import S3RequestRetriever

def test_s3_key_formatting():
    req = WidgetRequest(
        type="WidgetCreateRequest",
        request_id="r-101",
        widget_id="w-999",
        owner="John Doe Smith"
    )
    assert req.get_s3_key() == "widgets/john-doe-smith/w-999"

def test_json_parsing_success():
    raw_json = '''{
        "type": "WidgetCreateRequest",
        "requestId": "req-1",
        "widgetId": "wid-1",
        "owner": "Alice Wonderland",
        "label": "Test Widget",
        "description": "A demo widget",
        "otherAttributes": [{"name": "color", "value": "red"}]
    }'''
    req = WidgetRequest.from_json(raw_json)
    assert req.type == "WidgetCreateRequest"
    assert req.widget_id == "wid-1"
    assert req.other_attributes[0]["value"] == "red"

def test_missing_required_field_raises():
    invalid_json = '{"type": "WidgetCreateRequest", "requestId": "r-1"}'
    with pytest.raises(ValueError):
        WidgetRequest.from_json(invalid_json)

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
        other_attributes=[{"name": "size", "value": "large"}, {"name": "weight", "value": "10lbs"}]
    )
    storage.store_widget(req)

    mock_table.put_item.assert_called_once()
    called_item = mock_table.put_item.call_args[1]["Item"]
    assert called_item["id"] == "w-2"
    assert called_item["owner"] == "Bob"
    assert called_item["size"] == "large"
    assert called_item["weight"] == "10lbs"

def test_s3_storage_puts_expected_object():
    mock_s3 = MagicMock()
    storage = S3WidgetStorage(mock_s3, "target-web-bucket")
    
    req = WidgetRequest(
        type="create",
        request_id="req-123",
        widget_id="wid-456",
        owner="Alice Doe",
        label="Test",
        description="Desc"
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

def test_processor_handles_ignored_and_unknown_types(caplog):
    mock_storage = MagicMock()
    processor = RequestProcessor(mock_storage)
    
    # Test update ignored
    update_req = WidgetRequest(type="update", request_id="1", widget_id="2", owner="Bob")
    processor.process(update_req)
    mock_storage.store_widget.assert_not_called()
    
    # Test unknown type error log
    bad_req = WidgetRequest(type="invalid_action", request_id="1", widget_id="2", owner="Bob")
    processor.process(bad_req)
    mock_storage.store_widget.assert_not_called()

def test_retriever_empty_bucket():
    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.return_value = {}
    retriever = S3RequestRetriever(mock_s3, "test-bucket")
    assert retriever.poll_request() is None

def test_retriever_reads_and_deletes():
    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.return_value = {"Contents": [{"Key": "req-1.json"}]}
    sample_json = json.dumps({
        "type": "create",
        "requestId": "req-1",
        "widgetId": "wid-1",
        "owner": "Charlie Brown"
    }).encode("utf-8")
    
    mock_body = MagicMock()
    mock_body.read.return_value = sample_json
    mock_s3.get_object.return_value = {"Body": mock_body}
    
    retriever = S3RequestRetriever(mock_s3, "source-bucket")
    req = retriever.poll_request()
    
    assert req.widget_id == "wid-1"
    mock_s3.delete_object.assert_called_once_with(Bucket="source-bucket", Key="req-1.json")