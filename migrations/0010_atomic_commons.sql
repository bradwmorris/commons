-- One explicit upgrade to the atomic model. Old rows are mapped inside this
-- transaction; no parallel production schema remains after the conversion.
CREATE SCHEMA atomic_upgrade;
DO $$ DECLARE r record; BEGIN
 FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'_sqlx_migrations' LOOP
  EXECUTE format('ALTER TABLE public.%I SET SCHEMA atomic_upgrade',r.tablename);
 END LOOP;
END $$;
DROP VIEW IF EXISTS public.retrieval_objects, public.active_connections, public.active_objects CASCADE;

CREATE TABLE users (
 id uuid PRIMARY KEY, title text NOT NULL, user_kind text NOT NULL CHECK(user_kind IN('human','agent','system','unknown')),
 username text UNIQUE, password_hash text, role text NOT NULL DEFAULT 'reader' CHECK(role IN('admin','member','reader')),
 active boolean NOT NULL DEFAULT false, revision bigint NOT NULL DEFAULT 1,
 profile jsonb NOT NULL DEFAULT '{}', metadata jsonb NOT NULL DEFAULT '{}', provenance jsonb NOT NULL DEFAULT '{}',
 avatar_content_type text, avatar_image bytea,
 CHECK(password_hash IS NULL OR user_kind='human'),
 CHECK(avatar_image IS NULL OR octet_length(avatar_image) BETWEEN 1 AND 262144)
);
CREATE TABLE objects (
 id uuid PRIMARY KEY, kind text NOT NULL CHECK(kind IN('task','note','entity','source','theme','event','thread')),
 title text NOT NULL, description text NOT NULL, body text NOT NULL DEFAULT '', fields jsonb NOT NULL DEFAULT '{}',
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0), metadata jsonb NOT NULL DEFAULT '{}', provenance jsonb NOT NULL DEFAULT '{}',
 CHECK(jsonb_typeof(fields)='object'), CHECK(jsonb_typeof(metadata)='object'), CHECK(jsonb_typeof(provenance)='object')
);
COMMENT ON TABLE objects IS 'commons:atomic-packets:pending';
CREATE TABLE credentials (
 id uuid PRIMARY KEY, account_id uuid NOT NULL REFERENCES users(id), secret_hash text UNIQUE NOT NULL,
 mode text NOT NULL CHECK(mode IN('session','agent')), label text NOT NULL, write_kinds text[] NOT NULL DEFAULT '{}',
 expires_at timestamptz NOT NULL, revoked boolean NOT NULL DEFAULT false
);
CREATE TABLE artifacts (
 id uuid PRIMARY KEY, object_id uuid REFERENCES objects(id), user_id uuid REFERENCES users(id),
 body text, origin text NOT NULL DEFAULT 'caller_supplied', created_by uuid REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(),
 kind text NOT NULL DEFAULT 'other', title text, uri text, media_type text, language text,
 sha256 text NOT NULL, size_bytes bigint NOT NULL, capture_outcome text NOT NULL DEFAULT 'complete', capture_reason text,
 expected_size_bytes bigint, semantic_indexing_enabled boolean NOT NULL DEFAULT true, metadata jsonb NOT NULL DEFAULT '{}',
 supersedes_artifact_id uuid REFERENCES artifacts(id) DEFERRABLE INITIALLY DEFERRED, captured_at timestamptz, deleted_at timestamptz,
 provenance jsonb NOT NULL DEFAULT '{}', bytes bytea, width integer, height integer,
 CHECK(num_nonnulls(object_id,user_id)=1), CHECK(body IS NULL OR bytes IS NULL)
);
CREATE TABLE changes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), kind text NOT NULL, object_id uuid REFERENCES objects(id),
 target_type text NOT NULL, target_id uuid NOT NULL, revision bigint,
 actor_id uuid REFERENCES users(id), credential_id uuid REFERENCES credentials(id), occurred_at timestamptz,
 payload jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE traces (
 id uuid PRIMARY KEY, thread_id uuid REFERENCES objects(id), parent_id uuid REFERENCES traces(id) DEFERRABLE INITIALLY DEFERRED,
 source_id text, kind text NOT NULL, status text NOT NULL, actor_id uuid REFERENCES users(id),
 primary_object_id uuid REFERENCES objects(id), revision bigint NOT NULL DEFAULT 1,
 started_at timestamptz, completed_at timestamptz, received_at timestamptz NOT NULL DEFAULT now(),
 details jsonb NOT NULL DEFAULT '{}', deleted_at timestamptz, UNIQUE(thread_id,source_id), CHECK(parent_id IS DISTINCT FROM id)
);
CREATE TABLE trace_items (
 id uuid PRIMARY KEY, thread_id uuid REFERENCES objects(id), trace_id uuid REFERENCES traces(id),
 source_item_id text NOT NULL, turn_id text, position bigint NOT NULL CHECK(position>=0), kind text NOT NULL,
 role text, speaker_id uuid REFERENCES users(id), source_created_at timestamptz, source_ingested_at timestamptz,
 received_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL, payload_hash text NOT NULL,
 provenance jsonb NOT NULL DEFAULT '{}', CHECK(thread_id IS NOT NULL OR trace_id IS NOT NULL),
 UNIQUE(thread_id,source_item_id), UNIQUE(thread_id,position), UNIQUE(trace_id,source_item_id)
);
CREATE TABLE connections (
 id uuid PRIMARY KEY, from_id uuid REFERENCES objects(id), to_id uuid REFERENCES objects(id), kind text NOT NULL,
 explanation text NOT NULL, revision bigint NOT NULL DEFAULT 1, metadata jsonb NOT NULL DEFAULT '{}', provenance jsonb NOT NULL DEFAULT '{}',
 from_user_id uuid REFERENCES users(id), to_user_id uuid REFERENCES users(id),
 from_artifact_id uuid REFERENCES artifacts(id), to_artifact_id uuid REFERENCES artifacts(id),
 from_trace_id uuid REFERENCES traces(id), to_trace_id uuid REFERENCES traces(id),
 CHECK(num_nonnulls(from_id,from_user_id,from_artifact_id,from_trace_id)=1),
 CHECK(num_nonnulls(to_id,to_user_id,to_artifact_id,to_trace_id)=1),
 CHECK(COALESCE(from_id,from_user_id,from_artifact_id,from_trace_id)<>COALESCE(to_id,to_user_id,to_artifact_id,to_trace_id))
);
CREATE TABLE request_receipts (
 namespace text NOT NULL CHECK(namespace IN('write','capture')), owner_id uuid NOT NULL, request_key text NOT NULL,
 request_hash text NOT NULL, result jsonb NOT NULL, credential_id uuid REFERENCES credentials(id),
 thread_id uuid REFERENCES objects(id), actor_id uuid REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(namespace,owner_id,request_key),
 CHECK((namespace='write' AND owner_id=credential_id) OR (namespace='capture' AND owner_id=thread_id))
);
CREATE TABLE chunks (
 id uuid PRIMARY KEY, object_id uuid NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
 artifact_id uuid REFERENCES artifacts(id) ON DELETE CASCADE, ordinal integer NOT NULL CHECK(ordinal>=0),
 reference text NOT NULL, body text NOT NULL, input_hash text NOT NULL, object_revision bigint NOT NULL,
 space text NOT NULL, embedding vector(768), status text NOT NULL DEFAULT 'pending' CHECK(status IN('pending','processing','ready','failed')),
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(), claim uuid, claimed_at timestamptz,
 error text, updated_at timestamptz NOT NULL DEFAULT now(), CHECK(artifact_id IS NOT NULL OR ordinal=0),
 CHECK(status<>'ready' OR embedding IS NOT NULL)
);
CREATE UNIQUE INDEX chunk_object_packet ON chunks(object_id,ordinal) WHERE artifact_id IS NULL;
CREATE UNIQUE INDEX chunk_artifact_position ON chunks(artifact_id,ordinal) WHERE artifact_id IS NOT NULL;
CREATE INDEX chunk_work ON chunks(status,available_at);
CREATE INDEX chunk_object ON chunks(object_id);
CREATE INDEX connections_from ON connections(from_id);
CREATE INDEX connections_to ON connections(to_id);
CREATE INDEX connections_from_user ON connections(from_user_id);
CREATE INDEX connections_to_user ON connections(to_user_id);
CREATE INDEX connections_from_artifact ON connections(from_artifact_id);
CREATE INDEX connections_to_artifact ON connections(to_artifact_id);
CREATE INDEX connections_from_trace ON connections(from_trace_id);
CREATE INDEX connections_to_trace ON connections(to_trace_id);
CREATE INDEX changes_object ON changes(object_id,occurred_at,id);
CREATE INDEX changes_target ON changes(target_type,target_id,occurred_at);
CREATE INDEX trace_items_thread ON trace_items(thread_id,position);
CREATE INDEX trace_items_trace ON trace_items(trace_id,position);
CREATE INDEX artifacts_owner ON artifacts(object_id);
CREATE INDEX objects_search ON objects USING gin(to_tsvector('english',title||' '||description));

INSERT INTO users(id,title,user_kind,username,password_hash,role,active,revision,profile,metadata,provenance,avatar_content_type,avatar_image)
SELECT o.id,o.title,CASE WHEN o.fields->>'user_kind' IN('human','agent','system') THEN o.fields->>'user_kind' ELSE 'unknown' END,
 a.username,a.password_hash,COALESCE(a.role,'reader'),COALESCE(a.active,false),o.revision,o.fields,
 jsonb_build_object('created_by',o.created_by,'updated_by',o.updated_by,'created_at',o.created_at,'updated_at',o.updated_at),
 o.provenance||jsonb_build_object('import',o.import_provenance),v.content_type,v.image
FROM atomic_upgrade.objects o LEFT JOIN atomic_upgrade.accounts a ON a.id=o.id LEFT JOIN atomic_upgrade.user_avatars v ON v.user_id=o.id WHERE o.kind='user';
INSERT INTO objects(id,kind,title,description,body,fields,revision,metadata,provenance)
SELECT id,CASE kind WHEN 'memory' THEN 'note' WHEN 'chat' THEN 'thread' ELSE kind END,title,description,
 CASE kind WHEN 'task' THEN COALESCE(fields->>'brief_markdown','') WHEN 'note' THEN COALESCE(fields->>'content','') ELSE '' END,
 (fields-'content'-'brief_markdown'-'category_ids'-'primary_category_id') ||
 CASE WHEN kind='task' AND fields->>'brief_markdown' ~ '(?m)^Project: [a-zA-Z][a-zA-Z0-9-]*\s*$'
 THEN jsonb_build_object('project',substring(fields->>'brief_markdown' from '(?m)^Project: ([a-zA-Z][a-zA-Z0-9-]*)')) ELSE '{}'::jsonb END,
 revision,jsonb_build_object('created_by',created_by,'updated_by',updated_by,'created_at',created_at,'updated_at',updated_at),
 provenance||jsonb_strip_nulls(jsonb_build_object('import',import_provenance,'legacy_kind',CASE WHEN kind='memory' THEN kind END,'historical_only',CASE WHEN archived_at IS NOT NULL THEN true END))
FROM atomic_upgrade.objects WHERE kind<>'user';
-- Archive/protection preferences retire; preserve their original state in changes.
INSERT INTO changes(kind,object_id,target_type,target_id,revision,occurred_at,payload)
SELECT 'migration_original',CASE WHEN kind='user' THEN NULL ELSE id END,CASE WHEN kind='user' THEN 'user' ELSE 'object' END,id,revision,now(),to_jsonb(o)
FROM atomic_upgrade.objects o;
INSERT INTO credentials SELECT id,account_id,secret_hash,mode,label,ARRAY(SELECT DISTINCT CASE k WHEN 'memory' THEN 'note' WHEN 'chat' THEN 'thread' ELSE k END FROM unnest(write_kinds) k WHERE k NOT IN('eval','user')),expires_at,revoked FROM atomic_upgrade.credentials;
INSERT INTO artifacts(id,object_id,user_id,body,origin,created_by,created_at,kind,title,uri,media_type,language,sha256,size_bytes,capture_outcome,capture_reason,expected_size_bytes,semantic_indexing_enabled,metadata,supersedes_artifact_id,captured_at,deleted_at,provenance,bytes,width,height)
SELECT a.id,CASE WHEN o.kind<>'user' THEN a.object_id END,CASE WHEN o.kind='user' THEN a.object_id END,a.body,a.origin,a.created_by,a.created_at,a.kind,a.title,a.uri,a.media_type,a.language,a.sha256,a.size_bytes,a.capture_outcome,a.capture_reason,a.expected_size_bytes,
 a.semantic_indexing_enabled AND o.kind<>'chat',a.metadata,a.supersedes_artifact_id,a.captured_at,a.deleted_at,jsonb_build_object('import',a.import_provenance),b.bytes,b.width,b.height
FROM atomic_upgrade.artifacts a JOIN atomic_upgrade.objects o ON o.id=a.object_id LEFT JOIN atomic_upgrade.artifact_binary_payloads b ON b.artifact_id=a.id;
INSERT INTO changes(id,kind,object_id,target_type,target_id,revision,actor_id,occurred_at,payload)
SELECT h.id,'history',CASE WHEN o.kind<>'user' THEN h.object_id END,h.target_type,h.target_id,h.revision,h.actor_id,h.occurred_at,to_jsonb(h) FROM atomic_upgrade.record_history h LEFT JOIN atomic_upgrade.objects o ON o.id=h.object_id;
INSERT INTO changes(kind,object_id,target_type,target_id,revision,actor_id,credential_id,occurred_at,payload)
SELECT 'audit',CASE WHEN o.kind<>'user' THEN a.object_id END,CASE WHEN o.kind='user' THEN 'user' ELSE 'object' END,a.object_id,a.revision,a.actor_id,a.credential_id,a.occurred_at,to_jsonb(a) FROM atomic_upgrade.audit_events a JOIN atomic_upgrade.objects o ON o.id=a.object_id;
INSERT INTO changes(id,kind,object_id,target_type,target_id,revision,actor_id,occurred_at,payload)
SELECT c.id,'correction',CASE WHEN o.kind<>'user' THEN c.object_id END,c.target_type,c.target_id,c.object_revision,c.actor_id,c.created_at,to_jsonb(c) FROM atomic_upgrade.evidence_corrections c LEFT JOIN atomic_upgrade.objects o ON o.id=c.object_id;
INSERT INTO changes(kind,target_type,target_id,actor_id,occurred_at,payload)
SELECT 'import','import',destination_id,importer_id,imported_at,to_jsonb(i) FROM atomic_upgrade.import_items i;
INSERT INTO changes(kind,target_type,target_id,occurred_at,payload)
SELECT 'category_original','category',id,now(),to_jsonb(c) FROM atomic_upgrade.entity_categories c;
-- Existing category identities become Themes, with original labels/definitions retained.
INSERT INTO objects(id,kind,title,description,body,fields,revision,metadata,provenance)
SELECT id,'theme',label,'A theme used to group records about '||label||'.',definition,
 jsonb_build_object('slug','category-'||slug),revision,jsonb_build_object('created_by',created_by,'updated_by',updated_by,'created_at',created_at,'updated_at',updated_at),jsonb_strip_nulls(jsonb_build_object('migrated_from','category','aliases',aliases,'legacy_kind',legacy_kind,'historical_only',CASE WHEN archived_at IS NOT NULL THEN true END))
FROM atomic_upgrade.entity_categories;
INSERT INTO connections(id,from_id,to_id,kind,explanation,revision,metadata,provenance,from_user_id,to_user_id)
SELECT c.id,CASE WHEN f.kind<>'user' THEN c.from_id END,CASE WHEN t.kind<>'user' THEN c.to_id END,c.kind,c.explanation,c.revision,
 jsonb_build_object('created_by',c.created_by,'created_at',c.created_at,'updated_at',c.updated_at,'updated_by',NULL),c.provenance||jsonb_build_object('import',c.import_provenance),CASE WHEN f.kind='user' THEN c.from_id END,CASE WHEN t.kind='user' THEN c.to_id END
FROM atomic_upgrade.connections c JOIN atomic_upgrade.objects f ON f.id=c.from_id JOIN atomic_upgrade.objects t ON t.id=c.to_id WHERE c.archived_at IS NULL;
INSERT INTO changes(kind,target_type,target_id,revision,occurred_at,payload)
SELECT 'connection_original','connection',id,revision,now(),to_jsonb(c) FROM atomic_upgrade.connections c;
INSERT INTO connections(id,from_id,to_id,kind,explanation,metadata,provenance)
SELECT gen_random_uuid(),o.id,c.id,'themed','Grouped under '||c.label||'.',jsonb_build_object('created_at',now()),jsonb_build_object('migrated_from','category_membership','was_primary',o.fields->>'primary_category_id'=c.id::text)
FROM atomic_upgrade.objects o JOIN atomic_upgrade.entity_categories c ON o.fields->'category_ids' ? c.id::text WHERE o.kind<>'user';
INSERT INTO changes(kind,object_id,target_type,target_id,occurred_at,payload) SELECT 'capture_source_original',chat_id,'thread',chat_id,now(),to_jsonb(s) FROM atomic_upgrade.capture_sources s;
UPDATE objects o SET provenance=o.provenance||jsonb_build_object('capture',to_jsonb(s)-'chat_id'-'import_provenance') FROM atomic_upgrade.capture_sources s WHERE s.chat_id=o.id;
INSERT INTO traces(id,thread_id,parent_id,source_id,kind,status,actor_id,primary_object_id,revision,started_at,completed_at,received_at,details,deleted_at)
SELECT id,chat_object_id,parent_run_id,source_run_id,kind,status,actor_id,primary_object_id,revision,started_at,completed_at,received_at,to_jsonb(r)-'trace'-'input'-'result'||jsonb_build_object('input',input,'result',result),deleted_at FROM atomic_upgrade.runs r;
INSERT INTO trace_items(id,thread_id,source_item_id,turn_id,position,kind,role,speaker_id,source_created_at,source_ingested_at,received_at,payload,payload_hash,provenance)
SELECT id,chat_object_id,source_item_id,turn_id,position,kind,role,speaker_id,source_created_at,source_ingested_at,received_at,payload,payload_hash,jsonb_build_object('import',import_provenance) FROM atomic_upgrade.chat_messages;
INSERT INTO trace_items(id,thread_id,trace_id,source_item_id,position,kind,payload,payload_hash)
SELECT gen_random_uuid(),NULL,r.id,'legacy-step:'||e.ordinality,e.ordinality-1,'step',e.value,encode(sha256(convert_to(e.value::text,'UTF8')),'hex') FROM atomic_upgrade.runs r CROSS JOIN LATERAL jsonb_array_elements(r.trace) WITH ORDINALITY e;
INSERT INTO connections(id,from_id,to_artifact_id,kind,explanation,provenance)
SELECT gen_random_uuid(),chat_id,artifact_id,'managed_copy','Captured material shares this Thread deletion lifetime.',jsonb_build_object('migration','capture_artifacts') FROM atomic_upgrade.capture_artifacts;
INSERT INTO connections(id,from_id,to_id,kind,explanation,provenance)
SELECT gen_random_uuid(),chat_id,object_id,'managed_copy','Raw excerpt shares this Thread deletion lifetime.',jsonb_build_object('migration','capture_excerpt_objects') FROM atomic_upgrade.capture_excerpt_objects WHERE chat_id<>object_id;
INSERT INTO connections(id,from_trace_id,to_id,kind,explanation,provenance)
SELECT gen_random_uuid(),r.id,o.id,'consulted','Object recorded as consulted by this historical execution.',jsonb_build_object('historical',true,'operation','read','object_revision',NULL)
FROM atomic_upgrade.runs r CROSS JOIN LATERAL unnest(r.consulted_object_ids) x JOIN objects o ON o.id=x;
INSERT INTO request_receipts(namespace,owner_id,request_key,request_hash,result,credential_id)
SELECT 'write',credential_id,request_key,request_hash,result,credential_id FROM atomic_upgrade.receipts;
INSERT INTO request_receipts(namespace,owner_id,request_key,request_hash,result,credential_id,thread_id,actor_id)
SELECT 'capture',chat_id,batch_id,request_hash,result,credential_id,chat_id,actor_id FROM atomic_upgrade.capture_receipts;
-- Retired eval history remains exact and non-indexed; capabilities are not revived.
INSERT INTO changes(kind,target_type,target_id,occurred_at,payload)
SELECT 'retired_eval','eval',id,created_at,to_jsonb(e) FROM atomic_upgrade.eval_tests e;
INSERT INTO changes(kind,target_type,target_id,occurred_at,payload)
SELECT 'retired_eval_version','eval',test_id,created_at,to_jsonb(e) FROM atomic_upgrade.eval_versions e;
INSERT INTO changes(kind,target_type,target_id,occurred_at,payload)
SELECT 'retired_eval_comparison','eval_run',id,created_at,to_jsonb(e) FROM atomic_upgrade.eval_comparisons e;
INSERT INTO changes(kind,target_type,target_id,occurred_at,payload)
SELECT 'retired_eval_attempt','eval_run',run_id,created_at,to_jsonb(e) FROM atomic_upgrade.eval_attempts e;
-- Case-insensitive direct uniqueness; ambiguous links are retained for explicit
-- reconciliation instead of choosing a random canonical Task.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM objects WHERE kind='task' AND fields->>'github_issue_url' IS NOT NULL AND COALESCE(provenance->>'historical_only','false')<>'true' GROUP BY lower(fields->>'github_issue_url') HAVING count(*)>1) THEN
  RAISE EXCEPTION 'duplicate Task Issue links require explicit reconciliation before upgrade';
 END IF;
END $$;
CREATE UNIQUE INDEX task_issue_unique ON objects(lower(fields->>'github_issue_url')) WHERE kind='task' AND fields->>'github_issue_url' IS NOT NULL AND COALESCE(provenance->>'historical_only','false')<>'true';
CREATE UNIQUE INDEX theme_slug ON objects((fields->>'slug')) WHERE kind='theme';
CREATE UNIQUE INDEX capture_identity ON objects((provenance->'capture'->>'provider'),(provenance->'capture'->>'namespace'),(provenance->'capture'->>'thread_id')) WHERE kind='thread';

DROP SCHEMA atomic_upgrade CASCADE;
-- Obsolete trigger functions have no remaining users after the old tables drop.
DROP FUNCTION IF EXISTS public.reserve_task_issue(),public.capture_note_reference(),public.capture_artifact_reference(),public.retrieval_invalidate() CASCADE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='commons_app') THEN
  GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO commons_app;
  REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON _sqlx_migrations FROM commons_app;
 END IF;
END $$;

CREATE FUNCTION endpoint_json(oid uuid,uid uuid,aid uuid,tid uuid) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT CASE
 WHEN oid IS NOT NULL THEN (SELECT to_jsonb(o)||jsonb_build_object('endpoint_type','object') FROM objects o WHERE id=oid)
 WHEN uid IS NOT NULL THEN (SELECT jsonb_build_object('id',u.id,'kind','user','endpoint_type','user','title',u.title,'revision',u.revision,'metadata',u.metadata) FROM users u WHERE id=uid)
 WHEN aid IS NOT NULL THEN (SELECT jsonb_build_object('id',a.id,'kind','artifact','endpoint_type','artifact','title',COALESCE(a.title,'Artifact'),'object_id',a.object_id,'deleted',a.deleted_at IS NOT NULL) FROM artifacts a WHERE id=aid)
 ELSE (SELECT jsonb_build_object('id',t.id,'kind','trace','endpoint_type','trace','title',t.kind,'revision',t.revision) FROM traces t WHERE id=tid) END
$$;

CREATE FUNCTION register_managed_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE sid uuid;
BEGIN
 FOR sid IN SELECT id FROM objects WHERE id=NEW.object_id AND kind='thread'
  UNION SELECT from_id FROM connections WHERE kind='managed_copy' AND to_id=NEW.object_id AND from_id IS NOT NULL
 LOOP
  IF EXISTS(SELECT 1 FROM objects WHERE id=sid AND (provenance->>'deleted_at' IS NOT NULL OR provenance->'capture'->>'deleted_at' IS NOT NULL)) THEN
   RAISE EXCEPTION 'conversation evidence deleted' USING ERRCODE='23514';
  END IF;
  INSERT INTO connections(id,from_id,to_artifact_id,kind,explanation)
  SELECT gen_random_uuid(),sid,NEW.id,'managed_copy','Captured material shares the source Thread deletion lifetime.'
  WHERE NOT EXISTS(SELECT 1 FROM connections WHERE from_id=sid AND to_artifact_id=NEW.id AND kind='managed_copy');
 END LOOP; RETURN NEW;
END $$;
CREATE TRIGGER artifact_managed_lineage AFTER INSERT ON artifacts FOR EACH ROW EXECUTE FUNCTION register_managed_artifact();
CREATE FUNCTION register_managed_excerpt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE sid uuid; aid uuid;
BEGIN
 IF NEW.kind<>'note' OR NEW.fields->>'intent' IS DISTINCT FROM 'excerpt' OR NEW.fields->>'source_artifact_id' IS NULL THEN RETURN NEW; END IF;
 aid:=(NEW.fields->>'source_artifact_id')::uuid;
 FOR sid IN SELECT a.object_id FROM artifacts a JOIN objects o ON o.id=a.object_id WHERE a.id=aid AND o.kind='thread'
  UNION SELECT from_id FROM connections WHERE kind='managed_copy' AND to_artifact_id=aid AND from_id IS NOT NULL
 LOOP
  IF EXISTS(SELECT 1 FROM objects WHERE id=sid AND (provenance->>'deleted_at' IS NOT NULL OR provenance->'capture'->>'deleted_at' IS NOT NULL)) THEN
   RAISE EXCEPTION 'conversation evidence deleted' USING ERRCODE='23514';
  END IF;
  INSERT INTO connections(id,from_id,to_id,kind,explanation)
  SELECT gen_random_uuid(),sid,NEW.id,'managed_copy','Raw excerpt shares the source Thread deletion lifetime.'
  WHERE NOT EXISTS(SELECT 1 FROM connections WHERE from_id=sid AND to_id=NEW.id AND kind='managed_copy');
  INSERT INTO connections(id,from_id,to_artifact_id,kind,explanation)
  SELECT gen_random_uuid(),sid,a.id,'managed_copy','Captured material shares the source Thread deletion lifetime.' FROM artifacts a
  WHERE a.object_id=NEW.id AND NOT EXISTS(SELECT 1 FROM connections c WHERE c.from_id=sid AND c.to_artifact_id=a.id AND c.kind='managed_copy');
 END LOOP; RETURN NEW;
END $$;
CREATE TRIGGER note_managed_lineage AFTER INSERT OR UPDATE ON objects FOR EACH ROW EXECUTE FUNCTION register_managed_excerpt();
