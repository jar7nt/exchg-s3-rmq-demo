FROM python:3.12-slim

WORKDIR /app

# system deps for healthchecks/debug (optional)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

COPY services/common/src /app/common_src
COPY services/producer/src /app/producer_src

RUN pip install --no-cache-dir boto3

ENV PYTHONPATH=/app/common_src:/app/producer_src

ENTRYPOINT ["python", "-m", "producer.main"]
