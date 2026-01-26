FROM python:3.12.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/common/src /app/common_src
COPY services/branch_consumer/src /app/consumer_src

ENV PYTHONPATH=/app/common_src:/app/consumer_src

ENTRYPOINT ["python", "-m", "branch_consumer.main"]
