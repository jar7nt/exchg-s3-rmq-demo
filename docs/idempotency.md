# Idempotency and Out-of-Order Guarantees

This demo intentionally models a distributed integration environment where
message delivery order is **not guaranteed** and duplicates are expected.

The system is designed to converge to a correct final state under the following conditions:
- ACK messages may arrive before the corresponding pointer message
- ACK messages may be duplicated
- Pointer messages may be duplicated
- Messages may be delivered out of order
- Consumers and coordinator may be restarted at any time

---

## Problem Statement

In an asynchronous message-based system (RabbitMQ + S3 + database), the following
scenario is unavoidable:

1. A consumer processes a message and sends an ACK
2. The ACK reaches the coordinator **before** the pointer metadata
3. The coordinator cannot yet know:
   - where the S3 object is stored
   - how many recipients are expected
   - whether deletion is safe

Naive implementations typically:
- reject such ACKs
- requeue indefinitely
- or attempt deletion using incomplete metadata

All of these approaches lead to instability.

---

## Design Principles

The coordinator follows these principles:

- **ACKs are not authoritative**  
  They only indicate that a recipient claims completion.

- **Pointers are authoritative**  
  Only pointer messages define:
  - S3 bucket and object key
  - total number of expected recipients

- **Deletion is state-based, not time-based**  
  Deletion decisions depend on persisted state, not message order.

---

## State Model

The coordinator uses a single `objects` table with explicit state markers.

### Placeholder state
Created when ACKs arrive before the pointer:

- `pointer_id` is known
- `bucket`, `object_key` may be NULL or unknown
- `pointer_received_at` is NULL

### Complete pointer state
Created or upgraded when a pointer message arrives:

- `bucket`, `object_key` are known
- `recipients_total` is known
- `pointer_received_at` is set

### Deleted state
Reached only when all conditions are met:

- ACK count ≥ `recipients_total`
- `pointer_received_at` IS NOT NULL
- `deleted_at` is set exactly once

---

## Deletion Invariant

An S3 object may be deleted **if and only if**:

- pointer_received_at IS NOT NULL
- AND ack_count >= recipients_total
- AND deleted_at IS NULL


This invariant guarantees:
- no deletion with incomplete metadata
- exactly-once deletion
- safety under duplicate messages

---

## Idempotency Guarantees

The system guarantees:

- Duplicate ACKs do not increase ACK count
- Duplicate pointers overwrite placeholder metadata safely
- ACKs arriving before pointers are preserved
- Deletion happens at most once
- Missing S3 objects are handled gracefully

All database writes use idempotent operations (`INSERT ... ON CONFLICT DO NOTHING / UPDATE`).

---

## Integration Test

The guarantees above are validated by an integration test:

`tests/integration/test_idempotency.py`

The test intentionally:
- sends ACKs before pointers
- duplicates and shuffles messages
- sends pointers multiple times
- verifies database convergence
- verifies S3 object deletion

The test passes only if the system converges to the correct final state
regardless of message ordering.

---

## Summary

This design embraces the realities of distributed systems:
- message duplication
- out-of-order delivery
- partial knowledge

Correctness is achieved through explicit state modeling and invariants,
not by relying on delivery order or timing assumptions.
