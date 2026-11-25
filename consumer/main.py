import argparse
import logging
import os
import time
import boto3
from .retriever import S3RequestRetriever, SqsRequestRetriever
from .storage import S3WidgetStorage, DynamoDbWidgetStorage
from .processor import RequestProcessor


def setup_logging(log_filename: str = "consumer.log"):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_filename),
            logging.StreamHandler()
        ]
    )


def main():
    parser = argparse.ArgumentParser(description="HW7 Widget Consumer")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source-bucket", help="Bucket 2 (S3 Request bucket)")
    source_group.add_argument("--source-queue", help="SQS queue name or URL (e.g., cs5270-requests)")

    parser.add_argument("--target", choices=["s3", "dynamodb"], required=True, help="Target storage")
    parser.add_argument("--target-bucket", help="Bucket 3 (Widget storage bucket for S3)")
    parser.add_argument("--table-name", help="DynamoDB table name")
    parser.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"), help="AWS region")
    parser.add_argument("--log-file", default="consumer.log", help="Path to log file")
    args = parser.parse_args()

    setup_logging(args.log_file)
    logger = logging.getLogger("Consumer")

    source_desc = args.source_queue if args.source_queue else args.source_bucket
    logger.info(f"Consumer starting. Source: {source_desc}, Target: {args.target}, Region: {args.region}")

    s3_client = boto3.client("s3", region_name=args.region)

    if args.source_queue:
        sqs_client = boto3.client("sqs", region_name=args.region)
        retriever = SqsRequestRetriever(sqs_client, args.source_queue)
    else:
        retriever = S3RequestRetriever(s3_client, args.source_bucket)

    if args.target == "s3":
        if not args.target_bucket:
            parser.error("--target-bucket required for s3 target")
        storage = S3WidgetStorage(s3_client, args.target_bucket)
    else:
        if not args.table_name:
            parser.error("--table-name required for dynamodb target")
        dynamodb = boto3.resource("dynamodb", region_name=args.region)
        storage = DynamoDbWidgetStorage(dynamodb, args.table_name)

    processor = RequestProcessor(storage)
    logger.info("Entering polling loop (Ctrl+C to stop)...")

    try:
        while True:
            request = retriever.poll_request()
            if request:
                processor.process(request)
                retriever.acknowledge_request(request)
            else:
                if not args.source_queue:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Consumer stopped.")


if __name__ == "__main__":
    main()