import argparse
import logging
import time
import boto3
from .retriever import S3RequestRetriever
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
    parser = argparse.ArgumentParser(description="HW6 Widget Consumer")
    parser.add_argument("--source-bucket", required=True, help="Bucket 2 (Request queue bucket)")
    parser.add_argument("--target", choices=["s3", "dynamodb"], required=True, help="Target storage")
    parser.add_argument("--target-bucket", help="Bucket 3 (Widget storage bucket for S3)")
    parser.add_argument("--table-name", help="DynamoDB table name")
    parser.add_argument("--log-file", default="consumer.log", help="Path to log file")
    args = parser.parse_args()

    setup_logging(args.log_file)
    logger = logging.getLogger("Consumer")
    logger.info(f"Consumer starting. Source: {args.source_bucket}, Target: {args.target}")

    s3_client = boto3.client("s3")
    retriever = S3RequestRetriever(s3_client, args.source_bucket)

    if args.target == "s3":
        if not args.target_bucket:
            parser.error("--target-bucket required for s3 target")
        storage = S3WidgetStorage(s3_client, args.target_bucket)
    else:
        if not args.table_name:
            parser.error("--table-name required for dynamodb target")
        dynamodb = boto3.resource("dynamodb")
        storage = DynamoDbWidgetStorage(dynamodb, args.table_name)

    processor = RequestProcessor(storage)
    logger.info("Entering polling loop (Ctrl+C to stop)...")

    try:
        while True:
            request = retriever.poll_request()
            if request:
                processor.process(request)
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Consumer stopped.")

if __name__ == "__main__":
    main()