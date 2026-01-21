# S3 Pointer + ACK Refcount Demo

Demo of large message offloading from RabbitMQ to S3-compatible storage (MinIO),
with ACK-based refcount tracking and cleanup coordinator.

## Goal
Show how to keep RabbitMQ lightweight by sending only pointers to large payloads,
stored in S3 (MinIO), and delete objects safely after all consumers confirm processing.

## Iterations roadmap
- [x] 0: repo skeleton + UML placeholders
- [ ] 1: MinIO + basic PUT/GET/DELETE
- [ ] 2: RabbitMQ single node + pointer flow
- [ ] 3: ACK flow
- [ ] 4: Refcount DB + cleanup coordinator
- [ ] 5: 3 consumers + recipients_total logic
- [ ] 6: RabbitMQ cluster (3 nodes) + quorum + HAProxy
- [ ] 7: Prometheus + Grafana monitoring

## Docs
See `docs/ARCHITECTURE.md` and diagrams in `docs/uml/`.

## License
MIT
