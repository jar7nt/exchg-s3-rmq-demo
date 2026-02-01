import json
import time
import uuid
import random
from datetime import datetime, UTC

import pika
import psycopg
import boto3
import botocore
from botocore.exceptions import ClientError


RMQ_URL = "amqp://guest:guest@localhost:5672/"
DB_DSN = "postgresql://ack:ackpass@localhost:15432/ackdb"
S3_ENDPOINT = "http://localhost:9000"
S3_BUCKET = "1c-exchange"


def publish(exchange, routing_key, message):
    conn = pika.BlockingConnection(pika.URLParameters(RMQ_URL))
    ch = conn.channel()
    ch.basic_publish(
        exchange=exchange,
        routing_key=routing_key,
        body=json.dumps(message).encode("utf-8"),
        properties=pika.BasicProperties(delivery_mode=2),
    )
    conn.close()


def test_idempotent_pointer_and_acks():
    pointer_id = str(uuid.uuid4())
    recipients = ["branch-1", "branch-2", "branch-3"]

    pointer = {
        "schema": "s3-pointer-v1",
        "pointer_id": pointer_id,
        "bucket": S3_BUCKET,
        "key": f"test/{pointer_id}",
        "recipients_total": len(recipients),
        "created_at": datetime.now(UTC).isoformat(),
    }

    # ACKs (intentionally duplicated & shuffled)
    acks = []
    for r in recipients:
        acks.append({
            "schema": "s3-ack-v1",
            "pointer_id": pointer_id,
            "recipient_id": r,
            "processed_at": datetime.now(UTC).isoformat(),
        })
        acks.append({
            "schema": "s3-ack-v1",
            "pointer_id": pointer_id,
            "recipient_id": r,
            "processed_at": datetime.now(UTC).isoformat(),
        })

    random.shuffle(acks)

    # 1️⃣ Send ACKs before pointer
    for ack in acks:
        publish("ex.ack", "ack", ack)

    # 2️⃣ Send pointer twice
    publish("ex.msg", "branch1", pointer)
    publish("ex.msg", "branch1", pointer)

    # 3️⃣ Send ACKs again
    for ack in acks:
        publish("ex.ack", "ack", ack)

    # Give system time to converge
    time.sleep(5)

    # 4️⃣ Assert DB state
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM objects WHERE pointer_id = %s",
                (pointer_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 1

            cur.execute(
                "SELECT COUNT(*) FROM acks WHERE pointer_id = %s",
                (pointer_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == len(recipients)

            cur.execute(
                "SELECT deleted_at FROM objects WHERE pointer_id = %s",
                (pointer_id,),
            )
            row = cur.fetchone()
            assert row is not None
            deleted_at = row[0]
            assert deleted_at is not None

    # 5️⃣ Assert S3 object is gone (idempotent delete)
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id="minioadmin",
        aws_secret_access_key="minioadmin",
        region_name="us-east-1",
    )

    key = f"test/{pointer_id}"

    try:
        s3.head_object(Bucket=S3_BUCKET, Key=key)
        assert False, f"S3 object still exists: {S3_BUCKET}/{key}"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        # MinIO often returns 404 with Code=NotFound for HEAD
        assert status == 404 or code in ("404", "NotFound", "NoSuchKey"), (status, code)
