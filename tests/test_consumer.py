import pytest
from consumer.models import WidgetRequest
from consumer.storage import DynamoDbWidgetStorage
from unittest.mock import MagicMock

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