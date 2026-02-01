-- Objects stored in S3
CREATE TABLE IF NOT EXISTS objects (
    pointer_id       TEXT PRIMARY KEY,
    bucket           TEXT NOT NULL,
    object_key       TEXT NOT NULL,
    recipients_total INT  NOT NULL CHECK (recipients_total > 0),
    created_at       TIMESTAMPTZ NOT NULL,
    deleted_at       TIMESTAMPTZ
);

-- Business ACKs from recipients (idempotent via PK)
CREATE TABLE IF NOT EXISTS acks (
    pointer_id   TEXT NOT NULL REFERENCES objects(pointer_id) ON DELETE CASCADE,
    recipient_id TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (pointer_id, recipient_id)
);

CREATE INDEX IF NOT EXISTS idx_acks_pointer_id ON acks(pointer_id);
CREATE INDEX IF NOT EXISTS idx_objects_deleted_at ON objects(deleted_at);
