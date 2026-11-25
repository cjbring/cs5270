import abc
from collections import deque
import logging
from typing import Deque, Optional, Tuple
from .models import WidgetRequest

logger = logging.getLogger(__name__)


class RequestRetriever(abc.ABC):
    @abc.abstractmethod
    def poll_request(self) -> Optional[WidgetRequest]:
        pass

    def acknowledge_request(self, request: WidgetRequest) -> None:
        """Hook called after a request is processed (used by SQS to delete via ReceiptHandle)."""
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


class SqsRequestRetriever(RequestRetriever):
    def __init__(self, sqs_client, queue_name_or_url: str, wait_time_seconds: int = 10):
        self.sqs_client = sqs_client
        self.wait_time_seconds = wait_time_seconds
        if queue_name_or_url.startswith("https://") or queue_name_or_url.startswith("http://"):
            self.queue_url = queue_name_or_url
        else:
            resp = self.sqs_client.get_queue_url(QueueName=queue_name_or_url)
            self.queue_url = resp["QueueUrl"]
            
        self._buffer: Deque[Tuple[str, str, str]] = deque()
        self._in_flight_handles: dict[str, str] = {}

    def poll_request(self) -> Optional[WidgetRequest]:
        if not self._buffer:
            response = self.sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=self.wait_time_seconds,
            )
            messages = response.get("Messages", [])
            if not messages:
                return None

            logger.info(f"Fetched {len(messages)} message(s) from SQS queue '{self.queue_url}'")
            for msg in messages:
                self._buffer.append((msg["MessageId"], msg["ReceiptHandle"], msg["Body"]))

        message_id, receipt_handle, raw_body = self._buffer.popleft()
        logger.info(f"Dequeued SQS message '{message_id}'")
        req = WidgetRequest.from_json(raw_body)
        self._in_flight_handles[req.request_id] = receipt_handle
        return req

    def acknowledge_request(self, request: WidgetRequest) -> None:
        receipt_handle = self._in_flight_handles.pop(request.request_id, None)
        if receipt_handle:
            self.sqs_client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
            )
            logger.info(f"Deleted SQS message for request '{request.request_id}'")