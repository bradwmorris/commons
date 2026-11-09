-- Long visible Thread bodies use bounded chunks owned by the Thread, without
-- inventing Artifacts or turning native telemetry into conversation evidence.
DO $$
DECLARE constraint_name text;
BEGIN
 FOR constraint_name IN SELECT conname FROM pg_constraint
 WHERE conrelid='chunks'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%artifact_id IS NOT NULL%ordinal = 0%'
 LOOP
  EXECUTE format('ALTER TABLE chunks DROP CONSTRAINT %I',constraint_name);
 END LOOP;
END $$;
