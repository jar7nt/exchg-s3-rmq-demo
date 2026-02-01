-- Objects stored in S3
CREATE TABLE IF NOT EXISTS objects (
    pointer_id       TEXT PRIMARY KEY,
    bucket           TEXT,
    object_key       TEXT,
    recipients_total INT,
    created_at       TIMESTAMPTZ,
    deleted_at       TIMESTAMPTZ,
    pointer_received_at TIMESTAMPTZ
);

-- Business ACKs from recipients (idempotent via PK)
CREATE TABLE IF NOT EXISTS acks (
    pointer_id   TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (pointer_id, recipient_id)
);

CREATE INDEX IF NOT EXISTS idx_acks_pointer_id ON acks(pointer_id);
CREATE INDEX IF NOT EXISTS idx_objects_deleted_at ON objects(deleted_at);
