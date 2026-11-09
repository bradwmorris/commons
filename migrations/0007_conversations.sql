-- Conversations are canonical Objects, with transport identity independent of credentials.
-- A deleted source row is a payload-free replay barrier, not an archived transcript.
CREATE TABLE capture_sources (
  chat_id uuid PRIMARY KEY REFERENCES objects(id),
  provider text NOT NULL,
  namespace text NOT NULL,
  thread_id text NOT NULL,
  owner_id uuid NOT NULL REFERENCES accounts(id),
  parent_chat_id uuid REFERENCES objects(id),
  coverage jsonb NOT NULL DEFAULT '{}',
  import_provenance jsonb,
  deleted_at timestamptz,
  UNIQUE(provider, namespace, thread_id)
);
CREATE TABLE chat_messages (
  id uuid PRIMARY KEY,
  chat_object_id uuid NOT NULL REFERENCES capture_sources(chat_id),
  source_item_id text NOT NULL,
  turn_id text,
  position bigint NOT NULL CHECK(position >= 0),
  kind text NOT NULL CHECK(kind IN ('message','tool_call','tool_result','log')),
  role text NOT NULL CHECK(role IN ('human','agent','tool','system')),
  speaker_id uuid REFERENCES objects(id),
  source_created_at timestamptz,
  source_ingested_at timestamptz,
  received_at timestamptz NOT NULL DEFAULT now(),
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  import_provenance jsonb,
  UNIQUE(chat_object_id,source_item_id),
  UNIQUE(chat_object_id,position)
);
CREATE TABLE runs (
  id uuid PRIMARY KEY,
  parent_run_id uuid REFERENCES runs(id) DEFERRABLE INITIALLY DEFERRED,
  chat_object_id uuid REFERENCES capture_sources(chat_id),
  source_run_id text,
  kind text NOT NULL,
  status text NOT NULL,
  actor_id uuid REFERENCES objects(id),
  primary_object_id uuid REFERENCES objects(id),
  input jsonb NOT NULL DEFAULT '{}',
  trace jsonb NOT NULL DEFAULT '[]',
  result jsonb NOT NULL DEFAULT '{}',
  error text,
  review jsonb NOT NULL DEFAULT '{}',
  consulted_object_ids uuid[] NOT NULL DEFAULT '{}',
  historical_references jsonb NOT NULL DEFAULT '[]',
  source_created_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  received_at timestamptz NOT NULL DEFAULT now(),
  revision bigint NOT NULL DEFAULT 1,
  import_provenance jsonb,
  deleted_at timestamptz,
  CHECK(parent_run_id IS DISTINCT FROM id),
  UNIQUE(chat_object_id,source_run_id)
);
ALTER TABLE record_history ADD COLUMN run_id uuid REFERENCES runs(id);
CREATE INDEX history_linked_run ON record_history(run_id,occurred_at,id) WHERE run_id IS NOT NULL;
CREATE TABLE capture_receipts (
  chat_id uuid NOT NULL REFERENCES capture_sources(chat_id),
  batch_id text NOT NULL,
  actor_id uuid NOT NULL REFERENCES accounts(id),
  credential_id uuid NOT NULL REFERENCES credentials(id),
  request_hash text NOT NULL,
  result jsonb NOT NULL,
  PRIMARY KEY(chat_id,batch_id)
);
-- Explicitly registered raw copies share the source's deletion lifetime.
-- Independent authored knowledge is not a managed raw copy.
CREATE TABLE capture_artifacts (
  artifact_id uuid NOT NULL REFERENCES artifacts(id),
  chat_id uuid NOT NULL REFERENCES capture_sources(chat_id),
  PRIMARY KEY(artifact_id,chat_id)
);
ALTER TABLE artifacts ADD COLUMN deleted_at timestamptz;
CREATE TABLE capture_excerpt_objects (
  chat_id uuid NOT NULL REFERENCES capture_sources(chat_id),
  object_id uuid NOT NULL REFERENCES objects(id),
  PRIMARY KEY(chat_id,object_id)
);
ALTER TABLE evidence_corrections DROP CONSTRAINT evidence_corrections_target_type_check;
ALTER TABLE evidence_corrections ADD CHECK(target_type IN ('object','artifact','message','event','run'));
-- Reference admission and copy registration cover ordinary edits and privileged imports.
-- Historical lineage remains registered when a Note later changes its evidence pointer.
CREATE FUNCTION capture_note_reference() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_chat uuid; removed boolean;
BEGIN
  FOR source_chat IN
    WITH RECURSIVE lineage(object_id) AS (
      SELECT a.object_id FROM artifacts a WHERE a.id::text=NEW.fields->>'source_artifact_id'
      UNION
      SELECT a.object_id FROM lineage l JOIN objects o ON o.id=l.object_id
        JOIN artifacts a ON a.id::text=o.fields->>'source_artifact_id'
        WHERE o.kind='note' AND o.fields->>'intent'='excerpt'
    )
    SELECT ca.chat_id FROM capture_artifacts ca WHERE ca.artifact_id::text=NEW.fields->>'source_artifact_id'
    UNION SELECT c.chat_id FROM lineage l JOIN capture_sources c ON c.chat_id=l.object_id
    UNION SELECT e.chat_id FROM lineage l JOIN capture_excerpt_objects e ON e.object_id=l.object_id
    ORDER BY chat_id LOOP
    SELECT deleted_at IS NOT NULL INTO removed FROM capture_sources WHERE chat_id=source_chat FOR SHARE;
    IF removed THEN RAISE EXCEPTION 'conversation evidence deleted' USING ERRCODE='23514'; END IF;
    IF NEW.kind='note' AND NEW.fields->>'intent'='excerpt' THEN
      INSERT INTO capture_excerpt_objects VALUES(source_chat,NEW.id) ON CONFLICT DO NOTHING;
      INSERT INTO capture_artifacts SELECT id,source_chat FROM artifacts WHERE object_id=NEW.id ON CONFLICT DO NOTHING;
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER capture_note_reference AFTER INSERT OR UPDATE ON objects
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_note_reference();
CREATE FUNCTION capture_artifact_reference() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_chat uuid; removed boolean;
BEGIN
  FOR source_chat IN SELECT chat_id FROM capture_sources WHERE chat_id=NEW.object_id
    UNION SELECT chat_id FROM capture_excerpt_objects WHERE object_id=NEW.object_id LOOP
    SELECT deleted_at IS NOT NULL INTO removed FROM capture_sources WHERE chat_id=source_chat FOR SHARE;
    IF removed THEN RAISE EXCEPTION 'conversation evidence deleted' USING ERRCODE='23514'; END IF;
    INSERT INTO capture_artifacts VALUES(NEW.id,source_chat) ON CONFLICT DO NOTHING;
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER capture_artifact_reference AFTER INSERT ON artifacts
  FOR EACH ROW EXECUTE FUNCTION capture_artifact_reference();
CREATE INDEX chat_messages_order ON chat_messages(chat_object_id,position);
CREATE INDEX runs_chat_order ON runs(chat_object_id,source_created_at,id);
CREATE INDEX capture_artifacts_chat ON capture_artifacts(chat_id);
CREATE INDEX capture_excerpt_owner ON capture_excerpt_objects(object_id);
CREATE INDEX history_run ON record_history(target_id,occurred_at,id) WHERE target_type='run';
-- A registered raw copy does not become general context when its pointer/intent
-- changes or another excerpt quotes its artifact. Authenticated explicit reads remain.
CREATE OR REPLACE VIEW retrieval_objects AS SELECT o.* FROM active_objects o
  WHERE NOT EXISTS(SELECT 1 FROM capture_excerpt_objects e WHERE e.object_id=o.id)
  AND (o.kind<>'note' OR o.fields->>'intent' IS DISTINCT FROM 'excerpt'
    OR EXISTS(SELECT 1 FROM artifacts a JOIN active_objects source ON source.id=a.object_id
      WHERE a.id::text=o.fields->>'source_artifact_id' AND a.semantic_indexing_enabled AND a.capture_outcome='complete'
      AND NOT EXISTS(SELECT 1 FROM evidence_corrections c WHERE c.target_type='artifact' AND c.target_id=a.id)));
