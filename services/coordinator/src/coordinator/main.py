import json
import os
import time
from datetime import datetime
from collections import defaultdict

import pika
from psycopg.errors import UniqueViolation

from coordinator.db import get_conn
from coordinator.s3 import delete_object

def main():
    amqp_url = os.getenv("AMQP_URL", "amqp://guest:guest@rabbitmq:5672/")
    ack_exchange = os.getenv("RMQ_ACK_EXCHANGE", "ex.ack")
    ack_routing_key = os.getenv("RMQ_ACK_ROUTING_KEY", "ack")
    ack_queue = os.getenv("RMQ_ACK_QUEUE", "q.ack")
    prefetch = int(os.getenv("PREFETCH", "50"))
    ptr_exchange = os.getenv("RMQ_POINTER_EXCHANGE", "ex.msg")
    ptr_routing_key = os.getenv("RMQ_POINTER_ROUTING_KEY", "branch1")
    ptr_queue = os.getenv("RMQ_POINTER_QUEUE", "q.pointer")

    params = pika.URLParameters(amqp_url)
    conn = pika.BlockingConnection(params)
    ch = conn.channel()

    # idempotent topology
    ch.exchange_declare(exchange=ack_exchange, exchange_type="direct", durable=True)
    ch.queue_declare(queue=ack_queue, durable=True)
    ch.queue_bind(queue=ack_queue, exchange=ack_exchange, routing_key=ack_routing_key)

    ch.exchange_declare(exchange=ptr_exchange, exchange_type="direct", durable=True)
    ch.queue_declare(queue=ptr_queue, durable=True)
    ch.queue_bind(queue=ptr_queue, exchange=ptr_exchange, routing_key=ptr_routing_key)
    
    ch.basic_qos(prefetch_count=prefetch)

    # In-memory state for iteration 3
    acks = defaultdict(set)          # pointer_id -> set(recipient_id)
    totals = {}                      # pointer_id -> recipients_total
    completed = set()                # pointer_ids already completed

    print(f"[coordinator] consuming ACKs from queue={ack_queue} exchange={ack_exchange} rk={ack_routing_key}")

    def on_ack(channel, method, properties, body: bytes):
        try:
            msg = json.loads(body.decode("utf-8"))
            if msg.get("schema") != "s3-ack-v1":
                channel.basic_ack(method.delivery_tag)
                return

            pointer_id = msg["pointer_id"]
            recipient_id = msg["recipient_id"]
            processed_at = msg["processed_at"]
            recipients_total = int(msg.get("recipients_total", 1))

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # idempotent insert
                    cur.execute(
                        """
                        INSERT INTO acks (pointer_id, recipient_id, processed_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (pointer_id, recipient_id) DO NOTHING
                        """,
                        (pointer_id, recipient_id, processed_at),
                    )

                    # count ACKs so far
                    cur.execute(
                        "SELECT COUNT(*) FROM acks WHERE pointer_id = %s",
                        (pointer_id,),
                    )
                    row = cur.fetchone()
                    ack_count = row[0] if row else 0

                    # ensure object exists (pointer may arrive slightly later)
                    cur.execute(
                        """
                        INSERT INTO objects (pointer_id, bucket, object_key, recipients_total, created_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (pointer_id) DO NOTHING
                        """,
                        (
                            pointer_id,
                            msg.get("bucket", "unknown"),
                            msg.get("key", "unknown"),
                            recipients_total,
                        ),
                    )

                    cur.execute(
                        "SELECT recipients_total FROM objects WHERE pointer_id = %s",
                        (pointer_id,),
                    )
                    row = cur.fetchone()
                    total = row[0] if row else recipients_total

            print(
                f"[coordinator] ACK stored pointer_id={pointer_id} "
                f"recipient={recipient_id} ({ack_count}/{total})"
            )

            # all recipients processed?
            if ack_count < total:
                channel.basic_ack(method.delivery_tag)
                return

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # try to acquire deletion lock
                    cur.execute(
                        """
                        UPDATE objects
                        SET deleted_at = NOW()
                        WHERE pointer_id = %s
                        AND deleted_at IS NULL
                        """,
                        (pointer_id,),
                    )

                    if cur.rowcount == 0:
                        # already deleted by someone else
                        channel.basic_ack(method.delivery_tag)
                        return

                    # fetch S3 location
                    cur.execute(
                        "SELECT bucket, object_key FROM objects WHERE pointer_id = %s",
                        (pointer_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise RuntimeError("Object row disappeared unexpectedly")

                    bucket, object_key = row

            # outside transaction: do the actual delete
            try:
                delete_object(bucket, object_key)
                print(f"[coordinator] deleted S3 object {bucket}/{object_key}")
            except Exception as e:
                print(f"[coordinator] S3 delete failed: {e!r}")
                # IMPORTANT: do NOT rollback deleted_at
                # lifecycle policy + idempotent delete save us

            channel.basic_ack(method.delivery_tag)

        except Exception as e:
            print(f"[coordinator] ACK error: {e!r}")
            channel.basic_nack(method.delivery_tag, requeue=True)
            time.sleep(1)


    def on_pointer(channel, method, properties, body: bytes):
        try:
            msg = json.loads(body.decode("utf-8"))
            if msg.get("schema") != "s3-pointer-v1":
                channel.basic_ack(method.delivery_tag)
                return

            pointer_id = msg["pointer_id"]
            bucket = msg["bucket"]
            object_key = msg["key"]
            recipients_total = int(msg.get("recipients_total", 1))
            created_at = msg.get("created_at")

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO objects
                        (pointer_id, bucket, object_key, recipients_total, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (pointer_id) DO NOTHING
                        """,
                        (
                            pointer_id,
                            bucket,
                            object_key,
                            recipients_total,
                            created_at or datetime.utcnow(),
                        ),
                    )

            print(f"[coordinator] stored pointer {pointer_id}")
            channel.basic_ack(method.delivery_tag)

        except Exception as e:
            print(f"[coordinator] pointer error: {e!r}")
            channel.basic_nack(method.delivery_tag, requeue=True)
            time.sleep(1)


    ch.basic_consume(queue=ack_queue, on_message_callback=on_ack, auto_ack=False)
    ch.basic_consume(queue=ptr_queue, on_message_callback=on_pointer, auto_ack=False)

    try:
        ch.start_consuming()
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
