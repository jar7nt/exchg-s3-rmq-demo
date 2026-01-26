# S3 Pointer + ACK Refcount Demo

Demo of large message offloading from RabbitMQ to S3-compatible storage (MinIO),
with ACK-based refcount tracking and cleanup coordinator.

Tested with python 3.12.12

## Goal

Show how to keep RabbitMQ lightweight by sending only pointers to large payloads,
stored in S3 (MinIO), and delete objects safely after all consumers confirm processing.

This repository is built incrementally using **minimal vertical slices**. Each iteration results in a runnable system and is preserved in Git history.

## Iterations roadmap

* [x] 0: Repo skeleton + UML placeholders
* [x] 1: MinIO + basic PUT/GET/DELETE
* [x] 2: RabbitMQ (single node) + pointer flow (producer → RMQ → consumer → S3)
* [ ] 3: Business ACK messages
* [ ] 4: Refcount DB + cleanup coordinator
* [ ] 5: Multiple consumers + recipients_total logic
* [ ] 6: RabbitMQ cluster (3 nodes) + quorum queues + HAProxy
* [ ] 7: Prometheus + Grafana monitoring

## Architecture

High-level architecture and message flow diagrams are available here:

* `docs/ARCHITECTURE.md`
* `docs/uml/components.puml`
* `docs/uml/sequence.puml`

---

## Current iteration: Iteration 2

Iteration 2 introduces **RabbitMQ as a transport layer**. Large payloads are stored in MinIO, while RabbitMQ carries only lightweight S3 pointers.

### Components involved

* MinIO (S3-compatible object storage)
* RabbitMQ (single node, management enabled)
* Producer (one-shot job, emulates central 1C)
* Branch consumer (long-running job, emulates a филиал)

---

## How to run (Iteration 2)

### 1. Start infrastructure (MinIO + RabbitMQ)

```bash
make up
```

Services:

* MinIO API: [http://localhost:9000](http://localhost:9000)
* MinIO Console: [http://localhost:9001](http://localhost:9001)
* RabbitMQ UI: [http://localhost:15672](http://localhost:15672) (guest / guest)

---

### 2. Start branch consumer (terminal A)

```bash
make consumer
```

The consumer:

* subscribes to RabbitMQ queue
* receives S3 pointers
* downloads payloads from MinIO
* verifies SHA-256 checksum
* acknowledges messages to RabbitMQ

Stop with `Ctrl+C`.

---

### 3. Run producer job (terminal B)

```bash
make producer MSG_SIZE=1MB COUNT=5 VERIFY=1
```

Producer behavior:

* generates large JSON payloads
* compresses them with gzip
* uploads objects to MinIO
* publishes `s3-pointer-v1` messages to RabbitMQ

Optional cleanup:

```bash
make producer MSG_SIZE=1MB COUNT=5 VERIFY=1 DELETE=1
```

---

### 4. Inspect system state

```bash
make ps
make logs
```

---

### 5. Stop or reset

Stop infrastructure (keep data):

```bash
make down
```

Full cleanup (remove volumes and orphan containers):

```bash
make clean
```

---

## Notes

* Producer and consumer are executed as **jobs**, not long-running services.
* Healthchecks are enabled for infrastructure components.
* This iteration focuses on transport and integration only. Business-level ACK and refcount logic will be added in the next iterations.

## License

MIT
