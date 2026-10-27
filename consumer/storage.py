import abc
import json
import logging
from .models import WidgetRequest

logger = logging.getLogger(__name__)

class WidgetStorageStrategy(abc.ABC):
    @abc.abstractmethod
    def store_widget(self, request: WidgetRequest) -> None:
        pass

class S3WidgetStorage(WidgetStorageStrategy):
    def __init__(self, s3_client, bucket_name: str):
        self.s3_client = s3_client
        self.bucket_name = bucket_name

    def store_widget(self, request: WidgetRequest) -> None:
        key = request.get_s3_key()
        body = json.dumps(request.to_widget_dict(), indent=2)
        logger.info(f"Writing widget {request.widget_id} to S3 bucket '{self.bucket_name}' key '{key}'")
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json"
        )

class DynamoDbWidgetStorage(WidgetStorageStrategy):
    def __init__(self, dynamodb_resource, table_name: str):
        self.table = dynamodb_resource.Table(table_name)
        self.table_name = table_name

    def store_widget(self, request: WidgetRequest) -> None:
        logger.info(f"Writing widget {request.widget_id} to DynamoDB table '{self.table_name}'")
        item = {
            "id": request.widget_id,
            "owner": request.owner
        }
        if request.label:
            item["label"] = request.label
        if request.description:
            item["description"] = request.description
        
        if request.other_attributes:
            for attr in request.other_attributes:
                k = attr.get("name")
                v = attr.get("value")
                if k and v is not None:
                    item[k] = v

        self.table.put_item(Item=item)