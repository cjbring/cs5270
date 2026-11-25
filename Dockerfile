FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY consumer/ ./consumer/

CMD ["python", "-m", "consumer.main", "--source-queue", "https://sqs.us-east-1.amazonaws.com/293507255092/cs5270-requests", "--target", "dynamodb", "--table-name", "widgets"]
