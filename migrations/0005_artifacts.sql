-- Canonical evidence stays in PostgreSQL. Versions append; original bytes remain readable.
ALTER TABLE artifacts ALTER COLUMN body DROP NOT NULL;
ALTER TABLE artifacts
  ADD COLUMN kind text NOT NULL DEFAULT 'other',
  ADD COLUMN title text,
  ADD COLUMN uri text,
  ADD COLUMN media_type text NOT NULL DEFAULT 'text/plain',
  ADD COLUMN language text,
  ADD COLUMN sha256 text,
  ADD COLUMN size_bytes bigint,
  ADD COLUMN capture_outcome text NOT NULL DEFAULT 'complete',
  ADD COLUMN capture_reason text,
  ADD COLUMN expected_size_bytes bigint,
  ADD COLUMN semantic_indexing_enabled boolean NOT NULL DEFAULT true,
  ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN supersedes_artifact_id uuid REFERENCES artifacts(id),
  ADD COLUMN captured_at timestamptz;
UPDATE artifacts SET sha256=encode(sha256(convert_to(body,'UTF8')),'hex'), size_bytes=octet_length(body);
ALTER TABLE artifacts ALTER COLUMN sha256 SET NOT NULL, ALTER COLUMN size_bytes SET NOT NULL;
CREATE UNIQUE INDEX artifact_successor ON artifacts(supersedes_artifact_id) WHERE supersedes_artifact_id IS NOT NULL;
CREATE INDEX artifacts_owner ON artifacts(object_id);
CREATE TABLE artifact_binary_payloads (
  artifact_id uuid PRIMARY KEY REFERENCES artifacts(id),
  media_type text NOT NULL CHECK (media_type IN ('image/png','image/jpeg')),
  width integer NOT NULL CHECK (width > 0),
  height integer NOT NULL CHECK (height > 0),
  bytes bytea NOT NULL CHECK (octet_length(bytes) BETWEEN 1 AND 20971520)
);
