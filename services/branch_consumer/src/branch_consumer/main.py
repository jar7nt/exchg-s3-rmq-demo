import json
import os
import time
import hashlib
from datetime import datetime, timezone

import boto3
import pika

from botocore.exceptions import ClientError

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_s3_client(endpoint: str, access: str, secret: str, region: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=region,
    )


def main():
    consumer_id = os.getenv("CONSUMER_ID", "branch1")

    # MinIO
    endpoint = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
    access = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    region = os.getenv("MINIO_REGION", "us-east-1")

    # RabbitMQ
    amqp_url = os.getenv("AMQP_URL", "amqp://guest:guest@rabbitmq:5672/")
    exchange = os.getenv("RMQ_EXCHANGE", "ex.msg")
    routing_key = os.getenv("RMQ_ROUTING_KEY", "branch1")
    queue_name = os.getenv("RMQ_QUEUE", "q.branch1")
    ack_exchange = os.getenv("RMQ_ACK_EXCHANGE", "ex.ack")
    ack_routing_key = os.getenv("RMQ_ACK_ROUTING_KEY", "ack")
    ack_queue = os.getenv("RMQ_ACK_QUEUE", "q.ack")
    prefetch = int(os.getenv("PREFETCH", "10"))

    s3 = make_s3_client(endpoint, access, secret, region)

    params = pika.URLParameters(amqp_url)
    conn = pika.BlockingConnection(params)
    ch = conn.channel()

    # idempotent topology
    # main exchange/queue
    ch.exchange_declare(exchange=exchange, exchange_type="direct", durable=True)
    ch.queue_declare(
        queue=queue_name, 
        durable=True,
        arguments={
        "x-queue-type": "quorum"
        }
    )
    ch.queue_bind(queue=queue_name, exchange=exchange, routing_key=routing_key)
    # ACK exchange/queue
    ch.exchange_declare(exchange=ack_exchange, exchange_type="direct", durable=True)
    ch.queue_declare(
        queue=ack_queue, 
        durable=True,
        arguments={
        "x-queue-type": "quorum"
        }
    )
    ch.queue_bind(queue=ack_queue, exchange=ack_exchange, routing_key=ack_routing_key)

    ch.basic_qos(prefetch_count=prefetch)

    print(f"[{consumer_id}] consuming from queue={queue_name} exchange={exchange} rk={routing_key}")

    def on_message(channel, method, properties, body: bytes):
        try:
            msg = json.loads(body.decode("utf-8"))
            if msg.get("schema") != "s3-pointer-v1":
                print(f"[{consumer_id}] skip schema={msg.get('schema')}")
                channel.basic_ack(delivery_tag=method.delivery_tag)
                return

            bucket = msg["bucket"]
            key = msg["key"]
            expected = msg.get("sha256")

            try:
                obj = s3.get_object(Bucket=bucket, Key=key)
                data = obj["Body"].read()

            except ClientError as e:
                status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                code = e.response.get("Error", {}).get("Code")

                # MinIO/S3: missing object often looks like 404 / NotFound
                if status == 404 or code in ("404", "NotFound", "NoSuchKey", "NoSuchObject"):
                    print(f"[branch1] S3 object missing {bucket}/{key} (ack, no requeue)")
                    channel.basic_ack(method.delivery_tag)
                    return

                # Anything else: keep retrying
                print(f"[branch1] S3 error {bucket}/{key}: status={status} code={code} (requeue)")
                channel.basic_nack(method.delivery_tag, requeue=True)
                return

            actual = sha256_bytes(data)
            if expected and actual != expected:
                raise RuntimeError(f"sha mismatch key={key} expected={expected} actual={actual}")

            size_gz = len(data)
            pointer_id = msg.get("pointer_id")
            print(f"[{consumer_id}] OK pointer_id={pointer_id} size_gz={size_gz} key={key}")

            # Acknowledge message
            recipients_total = int(msg.get("recipients_total", 1))

            ack_msg = {
                "schema": "s3-ack-v1",
                "pointer_id": pointer_id,
                "bucket": bucket,
                "key": key,
                "recipient_id": consumer_id,
                "status": "processed",
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "recipients_total": recipients_total,
            }

            ack_body = json.dumps(ack_msg, ensure_ascii=False).encode("utf-8")

            ack_props = pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                message_id=f"{pointer_id}:{consumer_id}",
                timestamp=int(time.time()),
            )

            ch.basic_publish(
                exchange=ack_exchange,
                routing_key=ack_routing_key,
                body=ack_body,
                properties=ack_props,
            )

            # Here would be: decompress + deserialize + persist (later)
            channel.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            print(f"[{consumer_id}] ERROR: {e!r} (requeue)")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            time.sleep(1.0)

    ch.basic_consume(queue=queue_name, on_message_callback=on_message, auto_ack=False)
    try:
        ch.start_consuming()
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
    