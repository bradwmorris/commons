-- Preserve old records, including duplicate demo Issue links. A null task_id
-- reserves an ambiguous legacy Issue; callers must reconcile it explicitly.
CREATE TABLE task_issues (
  issue_url text PRIMARY KEY,
  task_id uuid UNIQUE REFERENCES objects(id)
);
INSERT INTO task_issues(issue_url, task_id)
SELECT lower(fields->>'github_issue_url'),
       CASE WHEN count(*) = 1 THEN min(id::text)::uuid END
FROM objects WHERE kind='task'
GROUP BY lower(fields->>'github_issue_url');
CREATE INDEX tasks_issue_lookup ON objects (lower(fields->>'github_issue_url')) WHERE kind='task';

-- The reservation's primary key enforces uniqueness even across generic writes.
-- Serialize relinking with ensure_task and maintain the old reservation too.
CREATE FUNCTION reserve_task_issue() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  next_url text := lower(NEW.fields->>'github_issue_url');
  old_url text;
  lock_url text;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    old_url := lower(OLD.fields->>'github_issue_url');
    IF old_url = next_url THEN RETURN NEW; END IF;
  END IF;
  FOR lock_url IN SELECT DISTINCT u FROM unnest(ARRAY[old_url,next_url]) u WHERE u IS NOT NULL ORDER BY u LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended('task-issue:' || lock_url,0));
  END LOOP;
  DELETE FROM task_issues WHERE issue_url=old_url;
  INSERT INTO task_issues(issue_url,task_id) VALUES(next_url,NEW.id);
  IF old_url IS NOT NULL THEN
    INSERT INTO task_issues(issue_url,task_id)
    SELECT old_url, CASE WHEN count(*)=1 THEN min(id::text)::uuid END
    FROM objects WHERE kind='task' AND lower(fields->>'github_issue_url')=old_url
    HAVING count(*)>0;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER task_issue_reservation AFTER INSERT OR UPDATE OF fields ON objects
FOR EACH ROW WHEN (NEW.kind='task') EXECUTE FUNCTION reserve_task_issue();

-- Agent accounts authenticate by scoped credentials, never a shared password.
ALTER TABLE accounts ALTER COLUMN password_hash DROP NOT NULL;
CREATE TABLE user_avatars (
  user_id uuid PRIMARY KEY REFERENCES accounts(id),
  content_type text NOT NULL CHECK (content_type IN ('image/png','image/jpeg','image/webp')),
  image bytea NOT NULL CHECK (octet_length(image) BETWEEN 1 AND 262144)
);
