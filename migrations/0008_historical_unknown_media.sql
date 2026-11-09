-- Historical Context captures may have no declared media type. Preserve that
-- absence; ordinary new captures still require a type at the API boundary.
ALTER TABLE artifacts ALTER COLUMN media_type DROP NOT NULL;
