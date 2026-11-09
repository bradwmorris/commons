-- Explicit installation migration. Compose provisions the extension as postgres;
-- native disposable tests use their isolated owner. No startup migration.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE retrieval_generations (
  id uuid PRIMARY KEY,
  space text NOT NULL,
  state text NOT NULL CHECK (state IN ('building','active','retired')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX retrieval_one_active ON retrieval_generations(state) WHERE state='active';
CREATE UNIQUE INDEX retrieval_one_build ON retrieval_generations(state) WHERE state='building';
CREATE TABLE retrieval_sources (
  generation uuid NOT NULL REFERENCES retrieval_generations(id) ON DELETE CASCADE,
  object_id uuid NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
  revision bigint NOT NULL,
  PRIMARY KEY (generation,object_id)
);
CREATE TABLE retrieval_passages (
  generation uuid NOT NULL,
  object_id uuid NOT NULL,
  ordinal integer NOT NULL,
  reference text NOT NULL,
  body text NOT NULL,
  embedding vector(768) NOT NULL,
  PRIMARY KEY (generation,object_id,ordinal),
  FOREIGN KEY (generation,object_id) REFERENCES retrieval_sources(generation,object_id) ON DELETE CASCADE
);
CREATE TABLE retrieval_jobs (
  generation uuid NOT NULL REFERENCES retrieval_generations(id) ON DELETE CASCADE,
  object_id uuid NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
  revision bigint NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  available_at timestamptz NOT NULL DEFAULT now(),
  claim uuid,
  error text,
  PRIMARY KEY (generation,object_id)
);
-- Transactional invalidation includes rollback/dry-run and every mutation path.
-- Never retain a current-looking old vector when a source becomes ineligible.
CREATE FUNCTION retrieval_invalidate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM retrieval_sources WHERE object_id=NEW.id;
  DELETE FROM retrieval_jobs WHERE object_id=NEW.id;
  IF NEW.kind <> 'chat' THEN
    INSERT INTO retrieval_jobs(generation,object_id,revision)
      SELECT id,NEW.id,NEW.revision FROM retrieval_generations WHERE state IN ('active','building');
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER retrieval_object_change AFTER INSERT OR UPDATE ON objects
  FOR EACH ROW EXECUTE FUNCTION retrieval_invalidate();
