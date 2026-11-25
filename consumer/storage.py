import abc
import json
import logging
from botocore.exceptions import ClientError
from .models import WidgetRequest

logger = logging.getLogger(__name__)


class WidgetStorageStrategy(abc.ABC):
    @abc.abstractmethod
    def store_widget(self, request: WidgetRequest) -> None:
        pass

    @abc.abstractmethod
    def delete_widget(self, request: WidgetRequest) -> None:
        pass

    @abc.abstractmethod
    def update_widget(self, request: WidgetRequest) -> None:
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

    def delete_widget(self, request: WidgetRequest) -> None:
        key = request.get_s3_key()
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                logger.warning(f"Cannot delete widget {request.widget_id}: key '{key}' does not exist in S3.")
                return
            raise

        self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
        logger.info(f"Deleted widget {request.widget_id} from S3 bucket '{self.bucket_name}' key '{key}'")

    def update_widget(self, request: WidgetRequest) -> None:
        key = request.get_s3_key()
        try:
            resp = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                logger.warning(f"Cannot update widget {request.widget_id}: key '{key}' does not exist in S3.")
                return
            raise

        widget_data = json.loads(resp["Body"].read().decode("utf-8"))

        # Update top-level fields (id and owner cannot be changed)
        if request.label is not None:
            widget_data["label"] = None if request.label == "" else request.label
        if request.description is not None:
            widget_data["description"] = None if request.description == "" else request.description

        # Merge otherAttributes
        if request.other_attributes:
            attr_map = {
                item["name"]: item["value"]
                for item in widget_data.get("otherAttributes", [])
                if "name" in item
            }
            for attr in request.other_attributes:
                name = attr.get("name")
                val = attr.get("value")
                if not name or val is None:
                    continue
                if val == "":
                    attr_map.pop(name, None)
                else:
                    attr_map[name] = val
            widget_data["otherAttributes"] = [{"name": k, "value": v} for k, v in attr_map.items()]

        body = json.dumps(widget_data, indent=2)
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json"
        )
        logger.info(f"Updated widget {request.widget_id} in S3 bucket '{self.bucket_name}' key '{key}'")


class DynamoDbWidgetStorage(WidgetStorageStrategy):
    def __init__(self, dynamodb_resource, table_name: str):
        self.table = dynamodb_resource.Table(table_name)
        self.table_name = table_name

    def store_widget(self, request: WidgetRequest) -> None:
        logger.info(f"Writing widget {request.widget_id} to DynamoDB table '{self.table_name}'")
        item = {
            "id": request.widget_id,
            "owner": request.owner,
        }
        if request.label:
            item["label"] = request.label
        if request.description:
            item["description"] = request.description

        if request.other_attributes:
            for attr in request.other_attributes:
                k = attr.get("name")
                v = attr.get("value")
                if k and v is not None and v != "":
                    item[k] = v

        self.table.put_item(Item=item)

    def delete_widget(self, request: WidgetRequest) -> None:
        resp = self.table.delete_item(
            Key={"id": request.widget_id},
            ReturnValues="ALL_OLD"
        )
        if "Attributes" not in resp:
            logger.warning(f"Cannot delete widget {request.widget_id}: item does not exist in DynamoDB.")
        else:
            logger.info(f"Deleted widget {request.widget_id} from DynamoDB table '{self.table_name}'")

    def update_widget(self, request: WidgetRequest) -> None:
        resp = self.table.get_item(Key={"id": request.widget_id})
        item = resp.get("Item")
        if not item:
            logger.warning(f"Cannot update widget {request.widget_id}: item does not exist in DynamoDB.")
            return

        # id and owner are immutable
        if request.label is not None:
            if request.label == "":
                item.pop("label", None)
            else:
                item["label"] = request.label

        if request.description is not None:
            if request.description == "":
                item.pop("description", None)
            else:
                item["description"] = request.description

        if request.other_attributes:
            for attr in request.other_attributes:
                k = attr.get("name")
                v = attr.get("value")
                if not k or k in ("id", "owner") or v is None:
                    continue
                if v == "":
                    item.pop(k, None)
                else:
                    item[k] = v

        self.table.put_item(Item=item)
        logger.info(f"Updated widget {request.widget_id} in DynamoDB table '{self.table_name}'")