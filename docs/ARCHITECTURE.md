# Architecture Overview

This demo models message exchange between distributed 1C systems
using RabbitMQ, MinIO (S3-compatible storage), and an ACK-based
refcount mechanism for safe cleanup of large payloads.

## Core ideas
- Large messages are stored in S3 (MinIO).
- RabbitMQ transports only lightweight pointers.
- Each consumer sends ACK after successful processing.
- A coordinator tracks ACKs in DB and deletes objects from S3
  when all recipients have confirmed.
- S3 lifecycle policy acts as a safety net.

## Message types
- `s3-pointer-v1` — pointer to object in S3.
- `s3-store-v1` — initialization of refcount for object.
- `s3-ack-v1` — confirmation from consumer.

## Components
- Producer (emulates central 1C)
- Branch consumers (emulate филиалы)
- RabbitMQ cluster + HAProxy
- MinIO (S3)
- Refcount DB
- ACK Coordinator
- Monitoring (Prometheus + Grafana)

See UML diagrams in `docs/uml/`.
