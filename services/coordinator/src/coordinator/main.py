import json
import os
import time
from datetime import datetime, timezone

import pika

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

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # 1️⃣ Ensure placeholder object exists (ACK-before-pointer allowed)
                    cur.execute(
                        """
                        INSERT INTO objects (pointer_id, created_at)
                        VALUES (%s, NOW())
                        ON CONFLICT (pointer_id) DO NOTHING
                        """,
                        (pointer_id,),
                    )

                    # 2️⃣ Idempotent ACK insert
                    cur.execute(
                        """
                        INSERT INTO acks (pointer_id, recipient_id, processed_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (pointer_id, recipient_id) DO NOTHING
                        """,
                        (pointer_id, recipient_id, processed_at),
                    )

                    # 3️⃣ Count ACKs
                    cur.execute(
                        "SELECT COUNT(*) FROM acks WHERE pointer_id = %s",
                        (pointer_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        # Should never happen, but stay defensive
                        channel.basic_ack(method.delivery_tag)
                        return
                    ack_count = row[0]

                    # 4️⃣ Fetch object state
                    cur.execute(
                        """
                        SELECT recipients_total,
                            bucket,
                            object_key,
                            pointer_received_at,
                            deleted_at
                        FROM objects
                        WHERE pointer_id = %s
                        """,
                        (pointer_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        # Should never happen, but stay defensive
                        channel.basic_ack(method.delivery_tag)
                        return

                    (
                        recipients_total,
                        bucket,
                        object_key,
                        pointer_received_at,
                        deleted_at,
                    ) = row

            print(
                f"[coordinator] ACK stored pointer_id={pointer_id} "
                f"recipient={recipient_id} ({ack_count}/{recipients_total})"
            )

            # 5️⃣ Deletion gate
            if (
                recipients_total is None
                or pointer_received_at is None
                or deleted_at is not None
                or ack_count < recipients_total
            ):
                channel.basic_ack(method.delivery_tag)
                return

            # 6️⃣ Acquire deletion lock (pointer must be real!)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE objects
                        SET deleted_at = NOW()
                        WHERE pointer_id = %s
                        AND deleted_at IS NULL
                        AND pointer_received_at IS NOT NULL
                        """,
                        (pointer_id,),
                    )

                    if cur.rowcount == 0:
                        channel.basic_ack(method.delivery_tag)
                        return

                    cur.execute(
                        "SELECT bucket, object_key FROM objects WHERE pointer_id = %s",
                        (pointer_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        channel.basic_ack(method.delivery_tag)
                        return
                    bucket, object_key = row

            # 7️⃣ Perform S3 delete outside transaction
            try:
                delete_object(bucket, object_key)
                print(f"[coordinator] deleted S3 object {bucket}/{object_key}")
            except Exception as e:
                print(f"[coordinator] S3 delete failed: {bucket=} {e!r}")
                # do NOT rollback deleted_at

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

            # Prefer pointer's created_at if provided, else now (UTC aware)
            created_at = msg.get("created_at")
            if created_at is None:
                created_at = datetime.now(timezone.utc).isoformat()

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO objects
                        (pointer_id, bucket, object_key, recipients_total, created_at, pointer_received_at)
                        VALUES
                        (%s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (pointer_id) DO UPDATE
                        SET bucket = EXCLUDED.bucket,
                            object_key = EXCLUDED.object_key,
                            recipients_total = EXCLUDED.recipients_total,
                            pointer_received_at = NOW(),
                            -- created_at: keep existing unless it looks like placeholder
                            created_at = CASE
                                WHEN objects.pointer_received_at IS NULL THEN EXCLUDED.created_at
                                ELSE objects.created_at
                            END
                        """,
                        (
                            pointer_id,
                            bucket,
                            object_key,
                            recipients_total,
                            created_at,
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
