-- Domain schema (plan section 6.4).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE originals (
    id          uuid PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('video', 'photo')),
    title       text NOT NULL,
    s3_key      text NOT NULL,
    duration_ms int,
    status      text NOT NULL DEFAULT 'ingesting',   -- ingesting | indexed | failed
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE original_frames (
    original_id uuid NOT NULL REFERENCES originals(id) ON DELETE CASCADE,
    t_ms        int  NOT NULL,
    phash       bit(64) NOT NULL,
    PRIMARY KEY (original_id, t_ms)
);
CREATE INDEX ON original_frames USING hnsw (phash bit_hamming_ops);

CREATE TABLE original_photos (
    original_id uuid PRIMARY KEY REFERENCES originals(id) ON DELETE CASCADE,
    phash       bit(64) NOT NULL,
    orb_s3_key  text NOT NULL
);
CREATE INDEX ON original_photos USING hnsw (phash bit_hamming_ops);

CREATE TABLE original_audio (
    original_id uuid PRIMARY KEY REFERENCES originals(id) ON DELETE CASCADE,
    fp_s3_key   text NOT NULL
);

CREATE TABLE scans (
    id          uuid PRIMARY KEY,
    kind        text NOT NULL,
    s3_key      text NOT NULL,
    source_url  text,
    workflow_id uuid NOT NULL UNIQUE,
    verdict     text,                               -- null | clear | flagged
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence (
    id              uuid PRIMARY KEY,
    scan_id         uuid NOT NULL REFERENCES scans(id),
    original_id     uuid NOT NULL REFERENCES originals(id),
    score           real NOT NULL,
    offset_ms       int,
    details         jsonb NOT NULL,                  -- matched frames, S3 thumbnail keys, homography
    reviewer        text,
    idempotency_key text NOT NULL UNIQUE,            -- "{workflow_id}:{seq}"
    created_at      timestamptz NOT NULL DEFAULT now()
);
