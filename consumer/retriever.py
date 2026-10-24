import abc
import logging
from typing import Optional
from .models import WidgetRequest

logger = logging.getLogger(__name__)

class RequestRetriever(abc.ABC):
    @abc.abstractmethod
    def poll_request(self) -> Optional[WidgetRequest]:
        pass

class S3RequestRetriever(RequestRetriever):
    def __init__(self, s3_client, source_bucket: str):
        self.s3_client = s3_client
        self.source_bucket = source_bucket

    def poll_request(self) -> Optional[WidgetRequest]:
        response = self.s3_client.list_objects_v2(
            Bucket=self.source_bucket,
            MaxKeys=1
        )
        contents = response.get("Contents", [])
        if not contents:
            return None

        request_key = contents[0]["Key"]
        logger.info(f"Reading request '{request_key}' from bucket '{self.source_bucket}'")

        get_resp = self.s3_client.get_object(Bucket=self.source_bucket, Key=request_key)
        raw_body = get_resp["Body"].read().decode("utf-8")

        self.s3_client.delete_object(Bucket=self.source_bucket, Key=request_key)
        logger.info(f"Deleted request '{request_key}' from bucket '{self.source_bucket}'")

        return WidgetRequest.from_json(raw_body)