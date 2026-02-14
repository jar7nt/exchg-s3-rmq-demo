import argparse
import gzip
import json
import os
import time
import uuid
import hashlib
from datetime import datetime, timezone

import boto3
import pika


def parse_size(s: str) -> int:
    s = s.strip().lower()
    mult = 1
    if s.endswith("kb"):
        mult = 1024
        s = s[:-2]
    elif s.endswith("mb"):
        mult = 1024 * 1024
        s = s[:-2]
    elif s.endswith("gb"):
        mult = 1024 * 1024 * 1024
        s = s[:-2]
    return int(float(s) * mult)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_payload_approx(target_bytes: int, idx: int) -> dict:
    import secrets
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    def rand_ascii(n: int) -> str:
        return "".join(alphabet[secrets.randbelow(len(alphabet))] for _ in range(n))

    base = {
        "schema": "demo-1c-object-v1",
        "id": str(uuid.uuid4()),
        "idx": idx,
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": []
    }

    raw0 = json.dumps(base, ensure_ascii=False).encode("utf-8")
    remaining = max(0, target_bytes - len(raw0))

    chunk = 1024
    chunks, tail = divmod(remaining, chunk)
    for _ in range(chunks):
        base["data"].append(rand_ascii(chunk))
    if tail:
        base["data"].append(rand_ascii(tail))
    return base


def make_s3_client(endpoint: str, access: str, secret: str, region: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=region,
    )


def rmq_publish_pointer(pointer: dict, exchange: str, routing_key: str, queue_name: str):
    amqp_url = os.getenv("AMQP_URL")
    if not amqp_url:
        return False

    params = pika.URLParameters(amqp_url)
    conn = pika.BlockingConnection(params)
    ch = conn.channel()

    # idempotent topology (demo-friendly)
    ch.exchange_declare(exchange=exchange, exchange_type="direct", durable=True)
    ch.queue_declare(
        queue=queue_name, 
        durable=True,
        arguments={
        "x-queue-type": "quorum"
        }
    )
    ch.queue_bind(queue=queue_name, exchange=exchange, routing_key=routing_key)

    body = json.dumps(pointer, ensure_ascii=False).encode("utf-8")
    props = pika.BasicProperties(
        content_type="application/json",
        delivery_mode=2,  # persistent
        message_id=pointer.get("pointer_id"),
        timestamp=int(time.time()),
    )
    ch.basic_publish(exchange=exchange, routing_key=routing_key, body=body, properties=props)
    conn.close()
    return True


def main():
    p = argparse.ArgumentParser(description="Iteration 2: upload to MinIO and publish pointer via RabbitMQ.")
    p.add_argument("--msg-size", required=True, help="Approx raw JSON size, e.g. 1MB, 500KB")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--prefix", default="demo")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--delete", action="store_true")
    args = p.parse_args()

    endpoint = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
    access = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    bucket = os.getenv("MINIO_BUCKET", "1c-exchange")
    region = os.getenv("MINIO_REGION", "us-east-1")
    recipients_total = int(os.getenv("RECIPIENTS_TOTAL", "1"))

    exchange = os.getenv("RMQ_EXCHANGE", "ex.msg")
    routing_key = os.getenv("RMQ_ROUTING_KEY", "branch1")
    queue_name = os.getenv("RMQ_QUEUE", "q.branch1")

    s3 = make_s3_client(endpoint, access, secret, region)

    target = parse_size(args.msg_size)
    t0 = time.time()

    pointers = []
    published = 0

    for i in range(1, args.count + 1):
        payload = build_payload_approx(target, i)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        gz = gzip.compress(raw)

        pointer_id = payload["id"]
        now = datetime.now(timezone.utc)
        key = f"{args.prefix}/{now:%Y/%m/%d}/{pointer_id}.json.gz"
        digest = sha256_bytes(gz)

        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=gz,
            ContentType="application/json",
            ContentEncoding="gzip",
            Metadata={"sha256": digest, "created_at": now.isoformat()},
        )

        pointer = {
            "schema": "s3-pointer-v1",
            "pointer_id": pointer_id,
            "bucket": bucket,
            "key": key,
            "encoding": "gzip",
            "content_type": "application/json",
            "size_raw": len(raw),
            "size_gz": len(gz),
            "sha256": digest,
            "recipients_total": recipients_total,
            "created_at": now.isoformat(),
        }
        pointers.append(pointer)

        if args.verify:
            obj = s3.get_object(Bucket=bucket, Key=key)
            data = obj["Body"].read()
            if sha256_bytes(data) != digest:
                raise RuntimeError(f"SHA mismatch for {key}")

        # publish pointer to RMQ if configured
        if rmq_publish_pointer(pointer, exchange, routing_key, queue_name):
            published += 1

        if args.delete:
            s3.delete_object(Bucket=bucket, Key=key)

        if i % 10 == 0 or i == args.count:
            elapsed = time.time() - t0
            print(f"[{i}/{args.count}] uploaded, published={published}, elapsed={elapsed:.1f}s")

    elapsed = time.time() - t0
    print("\n=== SUMMARY ===")
    print(f"endpoint={endpoint}")
    print(f"bucket={bucket}")
    print(f"published={published}/{args.count}")
    print(f"elapsed={elapsed:.2f}s")
    print("\nExample pointer:")
    print(json.dumps(pointers[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
