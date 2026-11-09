-- Ordinary Tasks may be unlinked. Issue-linked Tasks retain their unique,
-- case-insensitive reservation for retry-safe ensure_task pairing.
CREATE OR REPLACE FUNCTION reserve_task_issue() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  next_url text := lower(NEW.fields->>'github_issue_url');
  old_url text;
  lock_url text;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    old_url := lower(OLD.fields->>'github_issue_url');
    IF old_url IS NOT DISTINCT FROM next_url THEN RETURN NEW; END IF;
  END IF;
  FOR lock_url IN SELECT DISTINCT u FROM unnest(ARRAY[old_url,next_url]) u WHERE u IS NOT NULL ORDER BY u LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended('task-issue:' || lock_url,0));
  END LOOP;
  IF old_url IS NOT NULL THEN
    DELETE FROM task_issues WHERE issue_url=old_url;
  END IF;
  IF next_url IS NOT NULL THEN
    INSERT INTO task_issues(issue_url,task_id) VALUES(next_url,NEW.id);
  END IF;
  IF old_url IS NOT NULL THEN
    INSERT INTO task_issues(issue_url,task_id)
    SELECT old_url, CASE WHEN count(*)=1 THEN min(id::text)::uuid END
    FROM objects WHERE kind='task' AND lower(fields->>'github_issue_url')=old_url
    HAVING count(*)>0;
  END IF;
  RETURN NEW;
END $$;
