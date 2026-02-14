![CI](../../actions/workflows/ci.yml/badge.svg)

# S3 Pointer + ACK Refcount Demo

Demo of large message offloading from RabbitMQ to S3-compatible storage (MinIO),
with ACK-based refcount tracking and cleanup coordinator.

Tested with Python 3.12

---

## Goal

Keep RabbitMQ lightweight by sending only S3 pointers,
while large payloads are stored in MinIO.

Delete S3 objects only after all recipients confirm processing.

The repository evolves in minimal vertical slices.
Each iteration remains runnable and preserved in Git history.

---

## Iterations roadmap

- [x] 0: Repo skeleton + UML placeholders
- [x] 1: MinIO + basic PUT/GET/DELETE
- [x] 2: RabbitMQ (single node) + pointer flow
- [x] 3: Business ACK messages
- [x] 4: Refcount DB + cleanup coordinator
- [x] 5: RabbitMQ cluster (3 nodes) + quorum queues + HAProxy
- [ ] 6: Multiple consumers + recipients_total logic
- [ ] 7: Prometheus + Grafana monitoring

---

## Current iteration

### RabbitMQ cluster

- 3 nodes (rmq-1, rmq-2, rmq-3)
- Shared Erlang cookie (hardcoded for demo stability)
- Cluster formed via init container
- Quorum queues
- HAProxy as single AMQP + Management endpoint

### PostgreSQL

- Stores pointer metadata
- Tracks ACK refcount
- Guarantees exactly-once deletion

---

## How to run

### 1. Start infrastructure

<pre>
make up
</pre>

Endpoints:

- MinIO API: http://localhost:9000
- MinIO Console: http://localhost:9001
- RabbitMQ UI (via HAProxy): http://localhost:15672

---

### 2. Start coordinator

<pre>
make coordinator
</pre>

Coordinator:

- consumes ACK messages
- updates refcount
- deletes S3 object when all recipients processed

---

### 3. Start branch consumer

<pre>
make consumer
</pre>

Consumer:

- consumes S3 pointers
- downloads payload from MinIO
- verifies checksum
- sends business ACK

---

### 4. Run producer

<pre>
make producer MSG_SIZE=1MB COUNT=5 VERIFY=1
</pre>

Producer:

- generates JSON payload
- compresses with gzip
- uploads object to MinIO
- publishes pointer message

---

## Failover test

You can simulate node failure:

1. Start traffic (producer + consumer running)
2. Stop one RabbitMQ node:

<pre>
docker stop s3-rmq-ack-demo-rmq-1-1
</pre>

Expected behaviour:

- Quorum elects new leader
- HAProxy routes to healthy nodes
- Existing AMQP connections to the stopped node are closed by broker (expected)
- Clients must reconnect (automatic retry is not implemented in this demo)

---

## Idempotency guarantees

This demo supports:

- Duplicate pointers
- Duplicate ACKs
- ACK before pointer
- Out-of-order delivery
- Exactly-once S3 deletion

See:

- tests/integration/test_idempotency.py

---

## Notes

- Clients run as jobs (not services)
- Healthchecks enabled
- Quorum queues used instead of classic mirrored queues
- Designed as architecture demonstration, not a production-ready retry implementation

---

## License

MIT
