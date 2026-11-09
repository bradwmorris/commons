ALTER TABLE objects ADD COLUMN archived_at timestamptz, ADD COLUMN protected boolean NOT NULL DEFAULT false,
  ADD COLUMN provenance jsonb NOT NULL DEFAULT '{}', ADD COLUMN import_provenance jsonb,
  ADD COLUMN explicitly_corrected boolean NOT NULL DEFAULT false;
ALTER TABLE connections ADD COLUMN archived_at timestamptz, ADD COLUMN protected boolean NOT NULL DEFAULT false,
  ADD COLUMN revision bigint NOT NULL DEFAULT 1, ADD COLUMN provenance jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN import_provenance jsonb, ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE artifacts ADD COLUMN import_provenance jsonb;
ALTER TABLE artifacts ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE connections ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE artifacts DROP CONSTRAINT artifacts_created_by_fkey;
ALTER TABLE artifacts ADD FOREIGN KEY(created_by) REFERENCES objects(id);
ALTER TABLE connections DROP CONSTRAINT connections_created_by_fkey;
ALTER TABLE connections ADD FOREIGN KEY(created_by) REFERENCES objects(id);
CREATE UNIQUE INDEX theme_slug ON objects((fields->>'slug')) WHERE kind='theme';
CREATE TABLE entity_categories (
  id uuid PRIMARY KEY, slug text UNIQUE NOT NULL, label text NOT NULL, definition text NOT NULL,
  aliases jsonb NOT NULL DEFAULT '[]', legacy_kind text NOT NULL, revision bigint NOT NULL DEFAULT 1,
  archived_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES objects(id), updated_by uuid REFERENCES objects(id), import_provenance jsonb
);
CREATE TABLE record_history (
  id uuid PRIMARY KEY, object_id uuid REFERENCES objects(id), target_type text NOT NULL,
  target_id uuid NOT NULL, action text NOT NULL, revision bigint NOT NULL,
  before_state jsonb, after_state jsonb NOT NULL, actor_id uuid REFERENCES objects(id),
  occurred_at timestamptz NOT NULL DEFAULT now(), import_provenance jsonb
);
CREATE INDEX history_object ON record_history(object_id,occurred_at,id);
CREATE TABLE evidence_corrections (
  id uuid PRIMARY KEY, object_id uuid NOT NULL REFERENCES objects(id), target_type text NOT NULL CHECK(target_type IN ('object','artifact')),
  target_id uuid NOT NULL, reason text NOT NULL, representation jsonb NOT NULL,
  supersedes_correction_id uuid REFERENCES evidence_corrections(id), actor_id uuid REFERENCES objects(id),
  object_revision bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), import_provenance jsonb
);
CREATE UNIQUE INDEX correction_successor ON evidence_corrections(supersedes_correction_id) WHERE supersedes_correction_id IS NOT NULL;
CREATE TABLE import_items (
  source_store text NOT NULL, record_type text NOT NULL, source_id uuid NOT NULL,
  request_hash text NOT NULL, destination_id uuid NOT NULL, importer_id uuid NOT NULL REFERENCES accounts(id),
  imported_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source_store,record_type,source_id)
);
-- Archive state fences stale work in the same transaction as the change.
CREATE OR REPLACE FUNCTION retrieval_invalidate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM retrieval_sources WHERE object_id=NEW.id;
  DELETE FROM retrieval_jobs WHERE object_id=NEW.id;
  IF NEW.kind <> 'chat' AND NEW.archived_at IS NULL THEN
    INSERT INTO retrieval_jobs(generation,object_id,revision)
      SELECT id,NEW.id,NEW.revision FROM retrieval_generations WHERE state IN ('active','building');
  END IF;
  RETURN NEW;
END $$;
-- Existing vectors used an older eligibility contract. Canonical records are unchanged.
DELETE FROM retrieval_generations;
CREATE VIEW active_objects AS SELECT o.* FROM objects o WHERE o.archived_at IS NULL AND o.kind<>'chat';
CREATE VIEW active_connections AS SELECT c.* FROM connections c
  JOIN active_objects f ON f.id=c.from_id JOIN active_objects t ON t.id=c.to_id WHERE c.archived_at IS NULL;
CREATE VIEW retrieval_objects AS SELECT o.* FROM active_objects o WHERE o.kind<>'note' OR o.fields->>'intent' IS DISTINCT FROM 'excerpt'
  OR EXISTS(SELECT 1 FROM artifacts a JOIN active_objects source ON source.id=a.object_id
    WHERE a.id::text=o.fields->>'source_artifact_id' AND a.semantic_indexing_enabled AND a.capture_outcome='complete'
    AND NOT EXISTS(SELECT 1 FROM evidence_corrections c WHERE c.target_type='artifact' AND c.target_id=a.id));
-- Only the privileged import path can set import_provenance on INSERT.
-- Ordinary edits, including imported Tasks, still cannot create duplicate Issue links.
CREATE OR REPLACE FUNCTION reserve_task_issue() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  next_url text := lower(NEW.fields->>'github_issue_url'); old_url text; lock_url text;
BEGIN
  IF TG_OP='UPDATE' THEN
    old_url := lower(OLD.fields->>'github_issue_url');
    IF old_url IS NOT DISTINCT FROM next_url THEN RETURN NEW; END IF;
  END IF;
  FOR lock_url IN SELECT DISTINCT u FROM unnest(ARRAY[old_url,next_url]) u WHERE u IS NOT NULL ORDER BY u LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended('task-issue:' || lock_url,0));
  END LOOP;
  IF old_url IS NOT NULL THEN DELETE FROM task_issues WHERE issue_url=old_url; END IF;
  IF next_url IS NOT NULL THEN
    IF TG_OP='INSERT' AND NEW.import_provenance IS NOT NULL THEN
      INSERT INTO task_issues(issue_url,task_id) VALUES(next_url,NEW.id)
        ON CONFLICT(issue_url) DO UPDATE SET task_id=NULL;
    ELSE INSERT INTO task_issues(issue_url,task_id) VALUES(next_url,NEW.id);
    END IF;
  END IF;
  IF old_url IS NOT NULL THEN
    INSERT INTO task_issues(issue_url,task_id)
      SELECT old_url,CASE WHEN count(*)=1 THEN min(id::text)::uuid END FROM objects
      WHERE kind='task' AND lower(fields->>'github_issue_url')=old_url HAVING count(*)>0;
  END IF;
  RETURN NEW;
END $$;
