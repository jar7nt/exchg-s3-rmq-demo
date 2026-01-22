# S3 Pointer + ACK Refcount Demo

Demo of large message offloading from RabbitMQ to S3-compatible storage (MinIO),
with ACK-based refcount tracking and cleanup coordinator.

## Goal
Show how to keep RabbitMQ lightweight by sending only pointers to large payloads,
stored in S3 (MinIO), and delete objects safely after all consumers confirm processing.

## Iterations roadmap
- [x] 0: repo skeleton + UML placeholders
- [x] 1: MinIO + basic PUT/GET/DELETE
- [ ] 2: RabbitMQ single node + pointer flow
- [ ] 3: ACK flow
- [ ] 4: Refcount DB + cleanup coordinator
- [ ] 5: 3 consumers + recipients_total logic
- [ ] 6: RabbitMQ cluster (3 nodes) + quorum + HAProxy
- [ ] 7: Prometheus + Grafana monitoring

## Docs
See `docs/ARCHITECTURE.md` and diagrams in `docs/uml/`.

## Iteration 1: MinIO PUT/GET/DELETE

### Start MinIO
```bash
make i1-up
```
- MinIO API: http://localhost:9000
- MinIO Console: http://localhost:9001

### Run producer job (upload + optional verify/delete)
```bash
make i1-run MSG_SIZE=1MB COUNT=20 VERIFY=1
```

#### Delete uploaded objects:
```bash
make i1-run MSG_SIZE=1MB COUNT=20 VERIFY=1 DELETE=1
```

### Check status/logs
```bash
make i1-ps
make i1-logs
```

### Stop
#### (keeps volumes) 
```bash
make i1-down
```

#### (cleans volumes)
```bash
make i1-clean
```


## License
MIT
