-- Capture items are bounded, but a single tsvector for a large body can exceed
-- PostgreSQL's vector-size limit. Collect lexemes from bounded overlapping
-- windows into an array; the GIN index is a candidate prefilter, and retrieval
-- still checks exact current representation windows before returning a match.
CREATE FUNCTION public.commons_visible_lexemes(input_text text) RETURNS text[]
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE COST 1000 SET search_path=pg_catalog AS $$
 SELECT COALESCE(array_agg(DISTINCT lexeme ORDER BY lexeme),'{}'::text[])
 FROM generate_series(1,greatest(char_length(input_text),1),31000) AS starts(position)
 CROSS JOIN LATERAL unnest(tsvector_to_array(to_tsvector('pg_catalog.english'::regconfig,
  substring(input_text FROM starts.position FOR 32000)))) AS words(lexeme)
$$;
CREATE INDEX trace_items_visible_lexemes ON trace_items USING gin
 (public.commons_visible_lexemes(payload->>'body'))
 WHERE thread_id IS NOT NULL AND kind IN('message','tool_call','tool_result','log')
 AND jsonb_typeof(payload->'body')='string';
