//! Atomic Object retrieval and chunked Artifact evidence; no generation/job tables.
use super::*;
use std::{sync::Arc, time::Duration};
use tokio::sync::Semaphore;

const MODEL: &str = "embeddinggemma-2:270m-q8_0-text";
const MODEL_DIGEST: &str = "c21dd30c1e38444d3b4faa091407b6fa97221447b4965d74931d43d7f09bbbfd";
const SPACE: &str = "embeddinggemma2-c21dd30c-768-atomic500-artifact500-v2";
const CLAIM_SECONDS: i64 = 120;
// Current authored knowledge only. A historical record remains explicitly readable.
const ELIGIBLE: &str = r#"
SELECT o.id,o.kind,o.title,o.description,o.body,o.revision FROM objects o
WHERE COALESCE(o.provenance->>'historical_only','false') <> 'true'
 AND o.provenance->>'deleted_at' IS NULL
 AND o.provenance->'capture'->>'deleted_at' IS NULL
 AND o.id NOT IN(SELECT c.to_id FROM connections c WHERE c.kind='managed_copy' AND c.to_id IS NOT NULL)
 AND (o.kind<>'note' OR o.fields->>'intent' IS DISTINCT FROM 'excerpt' OR EXISTS(
  SELECT 1 FROM artifacts a JOIN objects parent ON parent.id=a.object_id
  WHERE a.id=CASE WHEN (o.fields->>'source_artifact_id') ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' THEN (o.fields->>'source_artifact_id')::uuid END AND a.deleted_at IS NULL
   AND a.capture_outcome='complete' AND a.semantic_indexing_enabled
   AND parent.kind<>'thread' AND parent.provenance->>'deleted_at' IS NULL
   AND parent.provenance->'capture'->>'deleted_at' IS NULL
   AND COALESCE(parent.provenance->>'historical_only','false')<>'true'
   AND NOT EXISTS(SELECT 1 FROM connections c WHERE c.kind='managed_copy' AND (c.to_id=parent.id OR c.to_artifact_id=a.id))
   AND NOT EXISTS(SELECT 1 FROM artifacts next WHERE next.supersedes_artifact_id=a.id)
   AND NOT EXISTS(SELECT 1 FROM changes ch WHERE ch.kind='correction' AND ch.target_type='artifact' AND ch.target_id=a.id
    AND ch.payload->'representation'<>'{}'::jsonb AND ch.id=(SELECT id FROM changes WHERE kind='correction' AND target_type='artifact' AND target_id=a.id ORDER BY revision DESC NULLS LAST,occurred_at DESC NULLS LAST,id DESC LIMIT 1))))
"#;
// No audit/history/trace/credential JSON is a search document. Only the current
// Artifact correction representation may replace original evidence for matching.
const OBJECT_SOURCE: &str = r#"
 SELECT o.id AS object_id,NULL::uuid AS artifact_id,o.kind,o.title,o.description,o.revision,
  'title: '||o.title||' | text: '||o.description||E'\n\n'||o.body AS body,o.body AS packet_body,
  'object:'||o.id::text AS reference FROM eligible o WHERE o.kind<>'thread'
"#;
// Only visible captured bodies, never native span attributes, audit or arbitrary JSON.
// Current explicit message corrections replace the matching representation.
const THREAD_ITEM_BODIES: &str = r#"
SELECT i.id,i.position,CASE
 WHEN correction.payload->'representation' IS NOT NULL AND correction.payload->'representation'<>'{}'::jsonb
 THEN COALESCE(correction.payload->'representation'->>'body',correction.payload->'representation'->>'text','')
 ELSE i.payload->>'body' END AS body
FROM trace_items i
LEFT JOIN LATERAL(SELECT payload FROM changes WHERE kind='correction' AND target_id=i.id
 AND target_type='message' AND object_id=o.id
 ORDER BY revision DESC NULLS LAST,occurred_at DESC NULLS LAST,id DESC LIMIT 1) correction ON true
WHERE i.thread_id=o.id AND i.kind IN('message','tool_call','tool_result','log')
 AND jsonb_typeof(i.payload->'body')='string'
"#;
fn thread_body() -> String {
    format!(
        "SELECT COALESCE(string_agg(body,E'\\n' ORDER BY position,id),'') AS text FROM ({THREAD_ITEM_BODIES}) current_items"
    )
}
fn thread_source() -> String {
    let thread_body = thread_body();
    format!(
        "SELECT o.id,NULL::uuid,o.kind,o.title,o.description,o.revision,'title: '||o.title||' | text: '||o.description||E'\n\n'||t.text,NULL::text, 'thread:'||o.id::text||':'||o.revision::text FROM eligible o CROSS JOIN LATERAL({thread_body}) t WHERE o.kind='thread'"
    )
}

const ARTIFACT_SOURCE: &str = r#"
 SELECT o.id,a.id,o.kind,o.title,o.description,o.revision,
  CASE WHEN correction.payload->'representation' IS NOT NULL AND correction.payload->'representation'<>'{}'::jsonb
   THEN CASE WHEN jsonb_typeof(correction.payload->'representation'->'body')='string' THEN correction.payload->'representation'->>'body'
    WHEN jsonb_typeof(correction.payload->'representation'->'text')='string' THEN correction.payload->'representation'->>'text' ELSE NULL END
   ELSE a.body END,NULL::text,
  CASE WHEN correction.payload->'representation' IS NOT NULL AND correction.payload->'representation'<>'{}'::jsonb
   THEN 'correction:'||correction.id::text||':artifact:'||a.id::text||':'||
    CASE WHEN jsonb_typeof(correction.payload->'representation'->'body')='string' THEN 'body' ELSE 'text' END ELSE 'artifact:'||a.id::text END FROM eligible o JOIN artifacts a ON a.object_id=o.id
 LEFT JOIN LATERAL(SELECT id,payload FROM changes WHERE kind='correction' AND target_type='artifact' AND target_id=a.id
  ORDER BY revision DESC NULLS LAST,occurred_at DESC NULLS LAST,id DESC LIMIT 1) correction ON true
 WHERE o.kind<>'thread' AND a.deleted_at IS NULL AND a.capture_outcome='complete' AND a.semantic_indexing_enabled
  AND a.body IS NOT NULL
  AND NOT EXISTS(SELECT 1 FROM artifacts next WHERE next.supersedes_artifact_id=a.id)
  AND NOT EXISTS(SELECT 1 FROM connections c WHERE c.kind='managed_copy' AND c.to_artifact_id=a.id)
"#;

fn sources() -> String {
    sources_with(false, "all", false)
}
fn sources_for(scoped: bool) -> String {
    sources_with(scoped, "all", false)
}

// Choose actual SQL branches, not a late scope predicate over a materialised
// all-document CTE. Default Object search never loads/hashes Artifact bodies.
fn documents_with(scoped: bool, scope: &str, filtered: bool) -> String {
    let ids = if scoped { "AND o.id=ANY($1)" } else { "" };
    let filters = if filtered {
        "AND ($2::text IS NULL OR o.kind=$2) AND ($3::uuid IS NULL OR o.id=$3)"
    } else {
        ""
    };
    // Readiness reuses eligible in multiple CTEs, so it is materialized. Scope
    // it here, before expensive unrelated excerpt/evidence eligibility checks.
    let scope_filter = if scope == "threads" {
        "AND o.kind='thread'"
    } else {
        ""
    };
    let documents = match scope {
        "objects" => format!("{OBJECT_SOURCE} UNION ALL {}", thread_source()),
        "threads" => thread_source(),
        "artifacts" => ARTIFACT_SOURCE.to_owned(),
        _ => format!(
            "{OBJECT_SOURCE} UNION ALL {ARTIFACT_SOURCE} UNION ALL {}",
            thread_source()
        ),
    };
    format!(
        "WITH eligible AS ({ELIGIBLE} {ids} {filters} {scope_filter}), docs(object_id,artifact_id,kind,title,description,revision,body,packet_body,reference) AS ({documents})"
    )
}

fn sources_with(scoped: bool, scope: &str, filtered: bool) -> String {
    format!(
        "{},sources AS MATERIALIZED (SELECT *,md5(jsonb_build_array(title,body)::text) AS source_hash FROM docs) ",
        documents_with(scoped, scope, filtered)
    )
}

fn catalog_with(scope: &str) -> String {
    // Revision/source identity is a cheap readiness signal, not a content cache.
    // Artifact originals/corrections are immutable and their changes advance the
    // owning revision. Every semantic result and published vector still checks
    // the exact current input hash. octet_length reads original size, not text.
    format!(
        "{},catalog AS (SELECT object_id,artifact_id,kind,revision,reference,octet_length(body)=0 AS empty,body IS NULL AS unsupported FROM docs) ",
        documents_with(false, scope, true)
    )
}

#[derive(Clone)]
pub struct Model {
    url: String,
    http: reqwest::Client,
    slots: Arc<Semaphore>,
}
impl Model {
    pub fn configured() -> std::result::Result<Option<Self>, Box<dyn std::error::Error>> {
        let Ok(url) = env::var("COMMONS_OLLAMA_URL") else {
            return Ok(None);
        };
        let parsed = url::Url::parse(&url)?;
        if parsed.scheme() != "http"
            || !matches!(
                parsed.host_str(),
                Some("127.0.0.1" | "localhost" | "ollama")
            )
            || !parsed.username().is_empty()
            || parsed.password().is_some()
            || parsed.path() != "/"
            || parsed.query().is_some()
            || parsed.fragment().is_some()
        {
            return Err(
                "COMMONS_OLLAMA_URL must be an HTTP loopback or private ollama service origin"
                    .into(),
            );
        }
        Ok(Some(Self {
            url: url.trim_end_matches('/').into(),
            http: reqwest::Client::builder()
                .no_proxy()
                .redirect(reqwest::redirect::Policy::none())
                .timeout(Duration::from_secs(5))
                .build()?,
            slots: Arc::new(Semaphore::new(1)),
        }))
    }

    async fn embed(
        &self,
        inputs: &[String],
        timeout: Duration,
    ) -> std::result::Result<Vec<String>, &'static str> {
        // Bounded admission: queries degrade rather than queue indefinitely behind indexing.
        let _slot = self.slots.try_acquire().map_err(|_| "model_busy")?;
        let version: Value = self
            .http
            .get(format!("{}/api/version", self.url))
            .send()
            .await
            .map_err(|_| "model_unavailable")?
            .error_for_status()
            .map_err(|_| "model_unavailable")?
            .json()
            .await
            .map_err(|_| "invalid_model_response")?;
        if version["version"] != "0.40.5" {
            return Err("runtime_mismatch");
        }
        let tags: Value = self
            .http
            .get(format!("{}/api/tags", self.url))
            .send()
            .await
            .map_err(|_| "model_unavailable")?
            .error_for_status()
            .map_err(|_| "model_unavailable")?
            .json()
            .await
            .map_err(|_| "invalid_model_response")?;
        if !tags["models"].as_array().is_some_and(|ms| {
            ms.iter()
                .any(|m| m["name"] == MODEL && m["digest"] == MODEL_DIGEST)
        }) {
            return Err("model_digest_mismatch_or_missing");
        }
        let result: Value = self
            .http
            .post(format!("{}/api/embed", self.url))
            .timeout(timeout)
            .json(
                &json!({"model":MODEL,"input":inputs,"truncate":false,"keep_alive":"5m",
                "options":{"num_gpu":0,"num_thread":2,"num_ctx":2048}}),
            )
            .send()
            .await
            .map_err(|_| "model_unavailable")?
            .error_for_status()
            .map_err(|_| "model_failed")?
            .json()
            .await
            .map_err(|_| "invalid_model_response")?;
        let vectors = result["embeddings"]
            .as_array()
            .filter(|v| v.len() == inputs.len())
            .ok_or("invalid_model_response")?;
        vectors
            .iter()
            .map(|v| {
                let numbers: Vec<f64> = v
                    .as_array()
                    .filter(|v| v.len() == 768)
                    .ok_or("invalid_dimensions")?
                    .iter()
                    .map(|n| n.as_f64().filter(|n| n.is_finite()).ok_or("invalid_vector"))
                    .collect::<std::result::Result<_, _>>()?;
                let norm = numbers.iter().map(|n| n * n).sum::<f64>().sqrt();
                if !norm.is_finite() || norm < 1e-10 {
                    return Err("invalid_vector");
                }
                Ok(format!(
                    "[{}]",
                    numbers
                        .iter()
                        .map(|n| (n / norm).to_string())
                        .collect::<Vec<_>>()
                        .join(",")
                ))
            })
            .collect()
    }
}
/// Build exact, bounded Artifact inputs with Unicode-character source windows.
/// Objects bypass this function: packet::input is already their only input.
fn artifact_packets(title: &str, text: &str) -> Result<Vec<(usize, usize, String)>> {
    let chars: Vec<char> = text.chars().collect();
    let mut packets = Vec::new();
    let mut start = 0;
    while start < chars.len() {
        let mut end = (start + 1000).min(chars.len());
        // Token count, not a character heuristic, is authoritative for each input.
        loop {
            let body: String = chars[start..end].iter().collect();
            if packet::count(title, "", &body)? <= packet::LIMIT {
                packets.push((start, end, packet::input(title, "", &body)));
                break;
            }
            if end - start <= 1 {
                return Err(invalid(
                    "Artifact title/character cannot fit embedding input",
                ));
            }
            end = start + (end - start) / 2;
        }
        if end == chars.len() {
            break;
        }
        // Bound overlap even when unusual Unicode takes many tokenizer tokens.
        start = end - ((end - start) / 10).min(100);
    }
    Ok(packets)
}

async fn reconcile(tx: &mut sqlx::Transaction<'_, sqlx::Postgres>) -> Result<bool> {
    sqlx::query("SET LOCAL jit=off").execute(&mut **tx).await?;
    sqlx::query("SELECT pg_advisory_xact_lock(8138001)")
        .execute(&mut **tx)
        .await?;
    // Materialize each long source/hash once. Hashed chunk-ID membership avoids
    // a correlated long-source scan for every existing chunk when PostgreSQL
    // underestimates current eligibility. Source hashes still fence current text.
    sqlx::query(&format!(
        "{} DELETE FROM chunks c WHERE c.space<>$1 OR c.id NOT IN(
        SELECT checked.id FROM sources s JOIN chunks checked ON checked.object_id=s.object_id
         AND s.artifact_id IS NOT DISTINCT FROM checked.artifact_id
         AND checked.input_hash=md5(s.source_hash||checked.body))",
        sources()
    ))
    .bind(SPACE)
    .execute(&mut **tx)
    .await?;
    // Pure bookkeeping revisions retain identical vectors, including in-flight work.
    sqlx::query(&format!("{} UPDATE chunks c SET object_revision=s.revision,
        reference=CASE WHEN c.artifact_id IS NULL AND s.kind<>'thread' THEN s.reference ELSE s.reference||substring(c.reference from ':[0-9]+:[0-9]+$') END
        FROM sources s WHERE s.object_id=c.object_id AND s.artifact_id IS NOT DISTINCT FROM c.artifact_id
         AND (c.object_revision<>s.revision OR c.reference IS DISTINCT FROM
          CASE WHEN c.artifact_id IS NULL AND s.kind<>'thread' THEN s.reference ELSE s.reference||substring(c.reference from ':[0-9]+:[0-9]+$') END)
         AND c.input_hash=md5(s.source_hash||c.body)", sources()))
        .execute(&mut **tx).await?;
    // Prepare up to32 bounded Object packets together, rather than one corpus
    // scan/tokenisation round trip per Object. Large Artifacts/Threads stay one at a time.
    let missing = "s.body<>'' AND NOT EXISTS(SELECT 1 FROM chunks c WHERE c.object_id=s.object_id
        AND c.artifact_id IS NOT DISTINCT FROM s.artifact_id AND c.space=$1 AND c.input_hash=md5(s.source_hash||c.body))";
    let mut rows=sqlx::query(&format!("{} SELECT * FROM sources s WHERE s.artifact_id IS NULL AND s.kind<>'thread' AND {missing} ORDER BY s.object_id LIMIT 32",sources()))
        .bind(SPACE).fetch_all(&mut **tx).await?;
    if rows.is_empty() {
        rows=sqlx::query(&format!("{} SELECT * FROM sources s WHERE (s.artifact_id IS NOT NULL OR s.kind='thread') AND {missing} ORDER BY s.object_id,s.artifact_id LIMIT 1",sources()))
            .bind(SPACE).fetch_all(&mut **tx).await?;
    }
    if rows.is_empty() {
        return Ok(false);
    }
    for row in rows {
        let oid: Uuid = row.get("object_id");
        let aid: Option<Uuid> = row.get("artifact_id");
        let title: String = row.get("title");
        let text: String = row.get("body");
        let reference: String = row.get("reference");
        let hash: String = row.get("source_hash");
        let revision: i64 = row.get("revision");
        let windowed = aid.is_some() || row.get::<String, _>("kind") == "thread";
        let packets = if windowed {
            artifact_packets(&title, &text)
        } else {
            // Split the canonical formatted string only to validate its source fields;
            // the model receives `text` exactly once, without a second title prefix.
            packet::validate(&title, row.get("description"), row.get("packet_body"))
                .map(|_| vec![(0, text.chars().count(), text.clone())])
        };
        let (packets, failed) = match packets {
            Ok(packets) => (packets, false),
            // An invalid legacy source must be visible as failed, never split/truncated.
            Err(_) => (vec![(0, 0, text.clone())], true),
        };
        for (ordinal, (start, end, input)) in packets.into_iter().enumerate() {
            let locator = if windowed {
                format!("{reference}:{start}:{end}")
            } else {
                reference.clone()
            };
            sqlx::query("INSERT INTO chunks(id,object_id,artifact_id,ordinal,reference,body,input_hash,object_revision,space,status,attempts,error)
            VALUES($1,$2,$3,$4,$5,$6,md5($7::text||$6::text),$8,$9,$10,$11,$12)")
            .bind(Uuid::new_v4()).bind(oid).bind(aid).bind(ordinal as i32).bind(locator)
            .bind(input).bind(&hash).bind(revision).bind(SPACE)
            .bind(if failed {"failed"} else {"pending"}).bind(if failed {8} else {0})
            .bind(failed.then_some("invalid_source_packet")).execute(&mut **tx).await?;
        }
    }

    Ok(true)
}

async fn state(tx: &mut sqlx::Transaction<'_, sqlx::Postgres>) -> Result<Value> {
    state_for(tx, None, None, "all").await
}

async fn state_for(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    kind: Option<&str>,
    object_id: Option<Uuid>,
    scope: &str,
) -> Result<Value> {
    // Cheap readiness metadata never hashes long original bodies on a poll.
    // Current content hashes remain enforced at semantic lookup/publication.
    // These bounded interactive queries do not amortise PostgreSQL JIT compilation.
    // Transaction-local only; do not alter installation-wide database settings.
    sqlx::query("SET LOCAL jit=off").execute(&mut **tx).await?;
    sqlx::query_scalar(&state_query(scope))
        .bind(SPACE)
        .bind(kind)
        .bind(object_id)
        .bind(scope)
        .fetch_one(&mut **tx)
        .await
        .map_err(Into::into)
}

fn state_query(scope: &str) -> String {
    // Both UUIDs have a typed delimiter: Object/Artifact identity cannot collide.
    // Keys are non-null. NOT IN permits a hashed membership subplan even when
    // eligibility estimates are tiny; a correlated anti-join rescanned chunks
    // millions of times on populated indexes under the same estimates.
    format!(
        r#"{}, signatures AS MATERIALIZED (
 SELECT *,object_id::text||CASE WHEN artifact_id IS NULL THEN ':object' ELSE ':artifact:'||artifact_id::text END AS source_key,true AS in_scope FROM catalog
), current_chunks AS (
 SELECT c.object_id,c.artifact_id,c.status,c.error,s.source_key,s.in_scope FROM chunks c JOIN signatures s
 ON c.object_id::text||CASE WHEN c.artifact_id IS NULL THEN ':object' ELSE ':artifact:'||c.artifact_id::text END=s.source_key
  WHERE c.space=$1 AND c.object_revision=s.revision AND c.reference IS NOT DISTINCT FROM
   CASE WHEN c.artifact_id IS NULL AND s.kind<>'thread' THEN s.reference ELSE s.reference||substring(c.reference from ':[0-9]+:[0-9]+$') END
), current_sources AS MATERIALIZED (
 SELECT DISTINCT source_key FROM current_chunks
), missing_sources AS (
 SELECT s.* FROM signatures s WHERE NOT s.empty AND NOT s.unsupported
 AND s.source_key NOT IN(SELECT source_key FROM current_sources)
), scoped_sources AS (
 SELECT * FROM signatures WHERE in_scope
), scoped_chunks AS (
 SELECT * FROM current_chunks WHERE in_scope
)
SELECT jsonb_build_object(
 'eligible',(SELECT count(*) FROM eligible WHERE $4<>'threads' OR kind='thread'),
 'conversation_content','visible_item_bodies_and_current_corrections; native_span_telemetry_excluded',
 'keyword_coverage','transactional_visible_item_lexemes_and_current_corrections; semantic_pending_is_separate',
 'excluded_incomplete_artifacts',(SELECT count(*) FROM artifacts a JOIN eligible o ON o.id=a.object_id WHERE a.deleted_at IS NULL AND a.capture_outcome<>'complete'),
 'excluded_native_trace_items',(SELECT count(*) FROM trace_items i JOIN traces t ON t.id=i.trace_id WHERE t.kind='opentelemetry' AND t.deleted_at IS NULL AND ($3::uuid IS NULL OR t.thread_id=$3) AND ($2::text IS NULL OR $2='thread')),
 'thread_sources',(SELECT count(*) FROM signatures WHERE kind='thread'),
 'visible_conversation_items',(SELECT count(*) FROM trace_items i JOIN eligible o ON o.id=i.thread_id WHERE o.kind='thread' AND i.kind IN('message','tool_call','tool_result','log') AND jsonb_typeof(i.payload->'body')='string' AND $4<>'artifacts'),
 'indexed',(SELECT count(DISTINCT object_id) FROM current_chunks WHERE artifact_id IS NULL AND status='ready'),
 'chunks',(SELECT count(*) FROM current_chunks),
 'ready_chunks',(SELECT count(*) FROM current_chunks WHERE status='ready'),
 'missing_sources',(SELECT count(*) FROM missing_sources),
 'empty_artifacts',(SELECT count(*) FROM signatures WHERE artifact_id IS NOT NULL AND empty),
 'pending',(SELECT count(*) FROM current_chunks WHERE status IN('pending','processing'))+(SELECT count(*) FROM missing_sources),
 'failed',(SELECT count(*) FROM current_chunks WHERE status='failed')+(SELECT count(*) FROM signatures WHERE artifact_id IS NOT NULL AND unsupported),
 'unsupported_corrections',(SELECT count(*) FROM signatures WHERE artifact_id IS NOT NULL AND unsupported),
 'errors',COALESCE((SELECT jsonb_agg(DISTINCT error) FROM (SELECT error FROM current_chunks WHERE error IS NOT NULL
  UNION SELECT 'unsupported_correction_text' WHERE EXISTS(SELECT 1 FROM signatures WHERE artifact_id IS NOT NULL AND unsupported)) e),'[]'::jsonb),
 'scope',$4::text,
 'scope_pending',(SELECT count(*) FROM scoped_chunks WHERE status IN('pending','processing'))+
   (SELECT count(*) FROM missing_sources WHERE in_scope),
 'scope_failed',(SELECT count(*) FROM scoped_chunks WHERE status='failed')+(SELECT count(*) FROM scoped_sources WHERE artifact_id IS NOT NULL AND unsupported),
 'readiness_validation','revision_source_identity_and_space; results/publication recheck input hashes',
 'coverage',CASE WHEN $4='all' AND $2::text IS NULL AND $3::uuid IS NULL THEN 'global' ELSE 'requested_scope' END,
 'kind_filter',$2::text,'object_filter',$3::uuid,'global_status_read','/api/retrieval/status',
 'space',$1::text)"#,
        catalog_with(scope)
    )
}

pub async fn rebuild(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, true).await?.admin()?;
    if app.model.is_none() {
        return Err(fail(
            StatusCode::SERVICE_UNAVAILABLE,
            "local embedding service is not configured",
        ));
    }
    reconcile(&mut tx).await?;
    // Clear claims as well as vectors: an old call can never publish after rebuild.
    sqlx::query("UPDATE chunks SET embedding=NULL,status='pending',attempts=0,claim=NULL,claimed_at=NULL,error=NULL,available_at=now(),updated_at=now()")
        .execute(&mut *tx).await?;
    let index = state(&mut tx).await?;
    tx.commit().await?;
    Ok(Json(
        json!({"state":"rebuilding","mode":"lexical_only","index":index}),
    ))
}

pub async fn status(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    Ok(Json(
        json!({"configured":app.model.is_some(),"model":MODEL,"space":SPACE,"index":state(&mut tx).await?}),
    ))
}

pub fn start(app: App) {
    if app.model.is_none() {
        return;
    }
    tokio::spawn(async move {
        let mut next_sweep = tokio::time::Instant::now();
        loop {
            let (busy, swept) = match work(&app, tokio::time::Instant::now() >= next_sweep).await {
                Ok(result) => result,
                Err(_) => {
                    eprintln!("retrieval worker failed; see retrieval readiness");
                    (false, false)
                }
            };
            if swept {
                next_sweep = tokio::time::Instant::now() + Duration::from_secs(5);
            }
            tokio::time::sleep(Duration::from_millis(if busy { 250 } else { 2000 })).await;
        }
    });
}

async fn claim(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    claim: Uuid,
) -> Result<Vec<sqlx::postgres::PgRow>> {
    sqlx::query("WITH selected AS (SELECT id FROM chunks WHERE space=$1 AND attempts<8
        AND available_at<=now() AND (status='pending' OR (status='processing' AND claimed_at<now()-make_interval(secs=>$2)))
        ORDER BY (artifact_id IS NOT NULL),available_at,id LIMIT 8 FOR UPDATE SKIP LOCKED)
        UPDATE chunks c SET status='processing',claim=$3,claimed_at=now(),available_at=now()+make_interval(secs=>$2),updated_at=now()
        FROM selected s WHERE c.id=s.id RETURNING c.id,c.object_id,c.body,c.input_hash")
        .bind(SPACE).bind(CLAIM_SECONDS as f64).bind(claim).fetch_all(&mut **tx).await.map_err(Into::into)
}

async fn work(app: &App, sweep: bool) -> Result<(bool, bool)> {
    let mut tx = app.db.begin().await?;
    let mut swept = sweep;
    let mut prepared = if sweep {
        reconcile(&mut tx).await?
    } else {
        false
    };
    let claim_id = Uuid::new_v4();
    let mut jobs = claim(&mut tx, claim_id).await?;
    if jobs.is_empty() && !sweep {
        prepared = reconcile(&mut tx).await?;
        swept = true;
        jobs = claim(&mut tx, claim_id).await?;
    }
    tx.commit().await?;
    if jobs.is_empty() {
        return Ok((prepared, swept));
    }
    let claim = claim_id;
    let inputs: Vec<String> = jobs.iter().map(|row| row.get("body")).collect();
    let vectors = app
        .model
        .as_ref()
        .unwrap()
        .embed(&inputs, Duration::from_secs(30))
        .await;
    let mut tx = app.db.begin().await?;
    sqlx::query("SET LOCAL jit=off").execute(&mut *tx).await?;
    // Validate only the claimed sources at publication. Re-running a full corpus
    // reconciliation here made every eight-vector batch rehash all long evidence.
    let objects: Vec<Uuid> = jobs.iter().map(|row| row.get("object_id")).collect();
    sqlx::query("SELECT pg_advisory_xact_lock(8138001)")
        .execute(&mut *tx)
        .await?;
    sqlx::query(&format!("{} DELETE FROM chunks c WHERE c.claim=$2 AND (c.space<>$3 OR NOT EXISTS(
        SELECT 1 FROM sources s WHERE s.object_id=c.object_id AND s.artifact_id IS NOT DISTINCT FROM c.artifact_id
        AND c.input_hash=md5(s.source_hash||c.body)))",sources_for(true)))
        .bind(&objects).bind(claim).bind(SPACE).execute(&mut *tx).await?;
    match vectors {
        Ok(vectors) => {
            for (job, vector) in jobs.iter().zip(vectors) {
                sqlx::query("UPDATE chunks SET embedding=$1::vector,status='ready',claim=NULL,claimed_at=NULL,error=NULL,updated_at=now()
                    WHERE id=$2 AND claim=$3 AND input_hash=$4 AND space=$5 AND status='processing'")
                    .bind(vector).bind(job.get::<Uuid,_>("id")).bind(claim)
                    .bind(job.get::<String,_>("input_hash")).bind(SPACE).execute(&mut *tx).await?;
            }
        }
        Err(error) => {
            sqlx::query("UPDATE chunks SET embedding=NULL,status=CASE WHEN attempts+1>=8 THEN 'failed' ELSE 'pending' END,
                attempts=attempts+1,claim=NULL,claimed_at=NULL,error=$1,available_at=now()+interval '10 seconds',updated_at=now()
                WHERE claim=$2 AND space=$3")
                .bind(error).bind(claim).bind(SPACE).execute(&mut *tx).await?;
        }
    }
    tx.commit().await?;
    Ok((true, swept))
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Search {
    q: String,
    kind: Option<String>,
    object_id: Option<Uuid>,
    scope: String,
    limit: usize,
    budget: usize,
    neighbours: usize,
}
impl Default for Search {
    fn default() -> Self {
        Self {
            q: String::new(),
            kind: None,
            object_id: None,
            scope: "objects".into(),
            limit: 5,
            budget: 24000,
            neighbours: 5,
        }
    }
}

fn lexical_sources(scope: &str) -> String {
    let header = "'title: '||o.title||' | text: '||o.description||E'\\n\\n'";
    let thread = format!(
        r#"
 SELECT o.id,NULL::uuid,o.kind,o.title,o.description,o.revision,{header},NULL::text,
  'thread:'||o.id::text||':'||o.revision::text,0::bigint FROM eligible o WHERE o.kind='thread'
 UNION ALL
 SELECT o.id,NULL::uuid,o.kind,o.title,o.description,o.revision,item.body,NULL::text,
  'thread:'||o.id::text||':'||o.revision::text,char_length({header})+offsets.base_offset
 FROM candidate_items item JOIN eligible o ON o.id=item.object_id
 JOIN item_offsets offsets ON offsets.object_id=item.object_id AND offsets.item_id=item.item_id
 WHERE item.body<>''
"#
    );
    let columns =
        "object_id,artifact_id,kind,title,description,revision,body,packet_body,reference";
    let wrap =
        |source: &str| format!("SELECT d.*,0::bigint AS base_offset FROM ({source}) d({columns})");
    let objects = wrap(OBJECT_SOURCE);
    let artifacts = wrap(ARTIFACT_SOURCE);
    let documents = match scope {
        "objects" => format!("{objects} UNION ALL {thread}"),
        "threads" => thread,
        "artifacts" => artifacts,
        _ => format!("{objects} UNION ALL {artifacts} UNION ALL {thread}"),
    };
    let filter = if scope == "threads" {
        "AND o.kind='thread'"
    } else {
        ""
    };
    // Materialize the GIN candidate set before joining parent eligibility. A tiny
    // parent estimate must not turn keyword discovery back into a body scan per
    // Thread. Metadata requirements preserve mixed metadata/body matches without
    // reducing every body query to an unselective ANY-word scan.
    let candidates = if scope == "artifacts" {
        String::new()
    } else {
        format!(
            r#",
 terms AS (SELECT tsvector_to_array(to_tsvector('pg_catalog.english'::regconfig,$1)) AS words),
 corrections AS MATERIALIZED (
  SELECT DISTINCT ON(object_id,target_id) object_id,target_id,payload FROM changes
  WHERE kind='correction' AND target_type='message'
  ORDER BY object_id,target_id,revision DESC NULLS LAST,occurred_at DESC NULLS LAST,id DESC
 ), metadata_requirements AS MATERIALIZED (
  SELECT o.id,terms.words,ARRAY(SELECT unnest(terms.words) EXCEPT
   SELECT unnest(tsvector_to_array(to_tsvector('pg_catalog.english'::regconfig,o.title||' '||o.description)))) AS required_words
  FROM eligible o CROSS JOIN terms WHERE o.kind='thread'
 ), body_matches AS MATERIALIZED (
  SELECT i.id AS item_id,i.thread_id AS object_id,i.position,i.payload->>'body' AS body
  FROM trace_items i CROSS JOIN terms
  WHERE i.thread_id IS NOT NULL AND i.kind IN('message','tool_call','tool_result','log')
   AND jsonb_typeof(i.payload->'body')='string' AND cardinality(terms.words)>0
   AND public.commons_visible_lexemes(i.payload->>'body') @> terms.words
  UNION ALL
  SELECT i.id,i.thread_id,i.position,i.payload->>'body'
  FROM metadata_requirements m CROSS JOIN LATERAL(
   SELECT i.* FROM trace_items i WHERE i.thread_id=m.id
    AND i.thread_id IS NOT NULL AND i.kind IN('message','tool_call','tool_result','log')
    AND jsonb_typeof(i.payload->'body')='string'
    AND public.commons_visible_lexemes(i.payload->>'body') @> m.required_words
  ) i WHERE cardinality(m.required_words)>0 AND cardinality(m.required_words)<cardinality(m.words)
 ), raw_matches AS MATERIALIZED (
  SELECT DISTINCT ON(item_id) * FROM body_matches ORDER BY item_id
 ), candidate_items AS MATERIALIZED (
  SELECT i.* FROM raw_matches i JOIN eligible o ON o.id=i.object_id
  LEFT JOIN corrections c ON c.object_id=i.object_id AND c.target_id=i.item_id
  WHERE o.kind='thread' AND (c.payload->'representation' IS NULL OR c.payload->'representation'='{{}}'::jsonb)
  UNION ALL
  SELECT i.id,i.thread_id,i.position,
   COALESCE(c.payload->'representation'->>'body',c.payload->'representation'->>'text','') AS body
  FROM corrections c JOIN trace_items i ON i.id=c.target_id AND i.thread_id=c.object_id
  JOIN eligible o ON o.id=i.thread_id JOIN metadata_requirements m ON m.id=o.id
  WHERE o.kind='thread' AND i.kind IN('message','tool_call','tool_result','log')
   AND jsonb_typeof(i.payload->'body')='string' AND c.payload->'representation'<>'{{}}'::jsonb
   AND cardinality(m.required_words)>0
   AND public.commons_visible_lexemes(COALESCE(c.payload->'representation'->>'body',c.payload->'representation'->>'text','')) @> m.required_words
 ), matched_threads AS (SELECT DISTINCT object_id FROM candidate_items), item_offsets AS MATERIALIZED (
  SELECT o.id AS object_id,items.id AS item_id,items.base_offset FROM eligible o
  CROSS JOIN LATERAL(
   WITH item_text AS MATERIALIZED ({THREAD_ITEM_BODIES})
   SELECT id,COALESCE(sum(char_length(body)+1) OVER(ORDER BY position,id
    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)::bigint AS base_offset FROM item_text
  ) items WHERE o.kind='thread' AND o.id IN(SELECT object_id FROM matched_threads)
 )"#
        )
    };
    format!(
        "WITH eligible AS ({ELIGIBLE} {filter} AND ($2::text IS NULL OR o.kind=$2) AND ($3::uuid IS NULL OR o.id=$3)) {candidates}, sources({columns},base_offset) AS ({documents}) "
    )
}

fn lexical_query(scope: &str) -> String {
    let scope_filter = "($2::text IS NULL OR s.kind=$2) AND ($3::uuid IS NULL OR s.object_id=$3) AND ($4='all' OR ($4='objects' AND s.artifact_id IS NULL) OR ($4='threads' AND s.kind='thread') OR ($4='artifacts' AND s.artifact_id IS NOT NULL))";
    // Keyword ranking favors title/description and covers long Artifact tails.
    format!(
        r#"{}, slices AS (
 SELECT s.*,pos,substring(s.body FROM pos FOR 32000) AS passage FROM sources s
 CROSS JOIN LATERAL generate_series(1,greatest(length(s.body),1),31000) pos WHERE {scope_filter}
), ranked AS (
 SELECT *,ts_rank_cd(
  CASE WHEN artifact_id IS NULL THEN setweight(to_tsvector('english',title),'A')||setweight(to_tsvector('english',description),'B')||setweight(to_tsvector('english',passage),'C')
  ELSE setweight(to_tsvector('english',passage),'D') END,plainto_tsquery('english',$1)) AS score
 FROM slices WHERE to_tsvector('english',CASE WHEN kind='thread' THEN title||' '||description||' '||passage ELSE passage END) @@ plainto_tsquery('english',$1)
), best AS (
 SELECT DISTINCT ON(object_id) object_id,
 CASE WHEN kind='thread' THEN reference||':'||(base_offset+pos-1)::text||':'||(base_offset+least(pos+31999,length(body)))::text ELSE reference END AS reference,
 score FROM ranked ORDER BY object_id,score DESC,reference,base_offset,pos
) SELECT * FROM best ORDER BY score DESC,object_id LIMIT 50"#,
        lexical_sources(scope)
    )
}

fn edges_query() -> String {
    // Check only incident endpoints. Primary-only requests retain primary links.
    format!(
        r#"WITH incident AS MATERIALIZED (
 SELECT * FROM connections c WHERE c.kind<>'managed_copy'
 AND (c.from_id=ANY($1) OR c.to_id=ANY($1))
 AND ($3::boolean OR (c.from_id=ANY($1) AND c.to_id=ANY($1)))
), endpoints AS MATERIALIZED (
 SELECT from_id AS id FROM incident UNION SELECT to_id FROM incident
), eligible AS ({ELIGIBLE} AND o.id IN(SELECT id FROM endpoints))
 SELECT jsonb_build_object('id',c.id,'from_id',c.from_id,'to_id',c.to_id,'kind',c.kind,'explanation',left(c.explanation,1000),'revision',c.revision,'read','/api/connections/'||c.id::text)
 FROM incident c JOIN eligible f ON f.id=c.from_id JOIN eligible t ON t.id=c.to_id
 ORDER BY ts_rank_cd(to_tsvector('english',c.explanation||' '||CASE WHEN c.from_id=ANY($1) THEN t.title||' '||t.description ELSE f.title||' '||f.description END),plainto_tsquery('english',$2)) DESC,
 LEAST(COALESCE(array_position($1,c.from_id),2147483647),COALESCE(array_position($1,c.to_id),2147483647)),c.id LIMIT 50"#
    )
}

// Fixed diagnostic only: no caller SQL, private content, inference or writes.
// Every EXPLAIN uses the same builder/bindings as its interactive query.
pub async fn diagnose(db: &PgPool) -> Result<Value> {
    diagnose_inner(db).await.map_err(|_| {
        fail(
            StatusCode::SERVICE_UNAVAILABLE,
            "retrieval diagnostic failed or exceeded its statement timeout",
        )
    })
}

async fn diagnose_inner(db: &PgPool) -> Result<Value> {
    let mut tx = db.begin().await?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        .execute(&mut *tx)
        .await?;
    sqlx::query("SET LOCAL statement_timeout='20s'")
        .execute(&mut *tx)
        .await?;
    sqlx::query("SET LOCAL jit=off").execute(&mut *tx).await?;
    let explain = "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) ";
    let eligibility = format!("WITH eligible AS ({ELIGIBLE}) SELECT count(*) FROM eligible");
    let plan: Value = sqlx::query_scalar(&(explain.to_owned() + &eligibility))
        .fetch_one(&mut *tx)
        .await?;
    let mut plans = vec![json!({"query":"eligibility","plan":plan_metadata(&plan)})];
    let ids: Vec<Uuid> = sqlx::query_scalar(&format!(
        "WITH eligible AS ({ELIGIBLE}) SELECT id FROM eligible ORDER BY id LIMIT 10"
    ))
    .fetch_all(&mut *tx)
    .await?;
    for (label, scope, id) in [
        ("global_status", "all", None),
        ("object_status", "objects", None),
        ("single_object_status", "objects", ids.first().copied()),
    ] {
        let plan: Value = sqlx::query_scalar(&(explain.to_owned() + &state_query(scope)))
            .bind(SPACE)
            .bind(None::<&str>)
            .bind(id)
            .bind(scope)
            .fetch_one(&mut *tx)
            .await?;
        plans.push(json!({"query":label,"plan":plan_metadata(&plan)}));
    }
    for (label, id) in [
        ("object_lexical", None),
        ("single_object_lexical", ids.first().copied()),
    ] {
        let plan: Value = sqlx::query_scalar(&(explain.to_owned() + &lexical_query("objects")))
            .bind("Commons")
            .bind(None::<&str>)
            .bind(id)
            .bind("objects")
            .fetch_one(&mut *tx)
            .await?;
        plans.push(json!({"query":label,"plan":plan_metadata(&plan)}));
    }
    for (label, neighbours) in [("primary_edges", false), ("neighbour_edges", true)] {
        let plan: Value = sqlx::query_scalar(&(explain.to_owned() + &edges_query()))
            .bind(&ids)
            .bind("Commons")
            .bind(neighbours)
            .fetch_one(&mut *tx)
            .await?;
        plans.push(json!({"query":label,"plan":plan_metadata(&plan)}));
    }
    tx.rollback().await?;
    Ok(json!({"read_only":true,"statement_timeout_ms":20000,"plans":plans}))
}

fn plan_metadata(raw: &Value) -> Value {
    // Allowlist, never redact a raw plan: Filters, Output, aliases, relation names,
    // literals, user IDs, query text, errors and unknown settings cannot escape.
    fn node(raw: &Value) -> Value {
        let mut result = json!({});
        if let Some(kind) = raw["Node Type"].as_str()
            && [
                "Result",
                "Append",
                "Merge Append",
                "Recursive Union",
                "BitmapAnd",
                "BitmapOr",
                "Seq Scan",
                "Index Scan",
                "Index Only Scan",
                "Bitmap Index Scan",
                "Bitmap Heap Scan",
                "Tid Scan",
                "Tid Range Scan",
                "Subquery Scan",
                "Function Scan",
                "Values Scan",
                "CTE Scan",
                "Named Tuplestore Scan",
                "WorkTable Scan",
                "Foreign Scan",
                "Custom Scan",
                "Nested Loop",
                "Merge Join",
                "Hash Join",
                "Materialize",
                "Memoize",
                "Sort",
                "Incremental Sort",
                "Group",
                "Aggregate",
                "WindowAgg",
                "Unique",
                "Gather",
                "Gather Merge",
                "Hash",
                "SetOp",
                "Limit",
                "ProjectSet",
                "LockRows",
            ]
            .contains(&kind)
        {
            result["node_type"] = json!(kind);
        }
        for key in [
            "Plan Rows",
            "Actual Rows",
            "Actual Loops",
            "Actual Startup Time",
            "Actual Total Time",
            "Rows Removed by Filter",
            "Rows Removed by Join Filter",
            "Shared Hit Blocks",
            "Shared Read Blocks",
            "Shared Dirtied Blocks",
            "Shared Written Blocks",
            "Local Hit Blocks",
            "Local Read Blocks",
            "Temp Read Blocks",
            "Temp Written Blocks",
            "Peak Memory Usage",
            "Hash Batches",
        ] {
            if raw[key].is_number() {
                result[key] = raw[key].clone();
            }
        }
        if let Some(children) = raw["Plans"].as_array() {
            result["children"] = children.iter().map(node).collect();
        }
        result
    }
    let root = &raw[0];
    let mut result = json!({"root":node(&root["Plan"])});
    for key in ["Planning Time", "Execution Time"] {
        if root[key].is_number() {
            result[key] = root[key].clone();
        }
    }
    if root["Settings"]["jit"] == "off" {
        result["settings"] = json!({"jit":"off"});
    }
    result
}

pub async fn retrieve(
    State(app): State<App>,
    headers: HeaderMap,
    Query(q): Query<Search>,
) -> Result<Json<Value>> {
    let started = tokio::time::Instant::now();
    let mut tx = app.db.begin().await?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        .execute(&mut *tx)
        .await?;
    actor(&app, &headers, &mut tx, false).await?;
    if q.q.trim().is_empty()
        || q.q.len() > 500
        || !(1..=10).contains(&q.limit)
        || !(2000..=24000).contains(&q.budget)
        || q.neighbours > 5
        || !["objects", "artifacts", "threads", "all"].contains(&q.scope.as_str())
        || q.kind
            .as_ref()
            .is_some_and(|k| !atomic::KINDS.contains(&k.as_str()))
    {
        return Err(invalid(
            "nonblank q<=500 bytes, seven-kind filter, scope objects/artifacts/threads/all, limit1–10, budget2000–24000, neighbours0–5 required",
        ));
    }
    let initial_index = state_for(&mut tx, q.kind.as_deref(), q.object_id, &q.scope).await?;
    let initially_ready = initial_index["scope_pending"] == 0 && initial_index["scope_failed"] == 0;
    let model_attempted = initially_ready && app.model.is_some();
    let (embedded, index, before_model, model_elapsed, after_model);
    if model_attempted {
        // Release the database snapshot before external inference. Re-authorise
        // and recheck requested-scope readiness in a fresh snapshot afterwards.
        tx.commit().await?;
        before_model = started.elapsed();
        let model_started = tokio::time::Instant::now();
        embedded = app
            .model
            .as_ref()
            .unwrap()
            .embed(
                &[format!("task: search result | query: {}", q.q)],
                Duration::from_secs(5),
            )
            .await;
        model_elapsed = model_started.elapsed();
        after_model = tokio::time::Instant::now();
        tx = app.db.begin().await?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            .execute(&mut *tx)
            .await?;
        actor(&app, &headers, &mut tx, false).await?;
        index = state_for(&mut tx, q.kind.as_deref(), q.object_id, &q.scope).await?;
    } else {
        // No external wait: reuse this one coherent readiness/search snapshot,
        // instead of performing the same scope-wide diagnostic a second time.
        embedded = Err(if initially_ready {
            "model_not_configured"
        } else {
            "scope_index_incomplete_or_rebuilding"
        });
        index = initial_index;
        before_model = started.elapsed();
        model_elapsed = Duration::ZERO;
        after_model = tokio::time::Instant::now();
    }
    let scope_filter = "($2::text IS NULL OR s.kind=$2) AND ($3::uuid IS NULL OR s.object_id=$3) AND ($4='all' OR ($4='objects' AND s.artifact_id IS NULL) OR ($4='threads' AND s.kind='thread') OR ($4='artifacts' AND s.artifact_id IS NOT NULL))";
    let lexical = sqlx::query(&lexical_query(&q.scope))
        .bind(&q.q)
        .bind(&q.kind)
        .bind(q.object_id)
        .bind(&q.scope)
        .fetch_all(&mut *tx)
        .await?;
    let mut scores: HashMap<Uuid, (f64, String)> = HashMap::new();
    for (i, row) in lexical.iter().enumerate() {
        scores.insert(
            row.get("object_id"),
            (1.0 / (61 + i) as f64, row.get("reference")),
        );
    }
    let complete = index["scope_pending"] == 0 && index["scope_failed"] == 0;
    let mut mode = "lexical_only";
    let mut reason = embedded.as_ref().err().copied();
    if complete && let Ok(vectors) = &embedded {
        let semantic = sqlx::query(&format!(r#"{}, distances AS (
 SELECT c.object_id,CASE WHEN c.artifact_id IS NULL AND s.kind<>'thread' THEN s.reference
 ELSE s.reference||substring(c.reference from ':[0-9]+:[0-9]+$') END AS reference,c.embedding <=> $1::vector AS distance FROM chunks c
 JOIN sources s ON s.object_id=c.object_id AND s.artifact_id IS NOT DISTINCT FROM c.artifact_id
 WHERE c.space=$5 AND c.status='ready' AND c.input_hash=md5(s.source_hash||c.body) AND {scope_filter}
), best AS (SELECT DISTINCT ON(object_id) * FROM distances ORDER BY object_id,distance,reference)
SELECT * FROM best ORDER BY distance,object_id LIMIT 50"#,sources_with(false,&q.scope,true)))
            .bind(&vectors[0]).bind(&q.kind).bind(q.object_id).bind(&q.scope).bind(SPACE).fetch_all(&mut *tx).await?;
        for (i, row) in semantic.iter().enumerate() {
            let entry = scores
                .entry(row.get("object_id"))
                .or_insert((0.0, row.get("reference")));
            entry.0 += 1.0 / (61 + i) as f64;
        }
        mode = "hybrid";
    } else if embedded.is_ok() {
        reason = Some("index_incomplete_or_rebuilding");
    }
    if q.scope != "artifacts" {
        let exact=sqlx::query_scalar::<_,Uuid>(&format!("WITH eligible AS ({ELIGIBLE}) SELECT id FROM eligible WHERE (id::text=$1 OR lower(title)=lower($1)) AND ($2::text IS NULL OR kind=$2) AND ($3::uuid IS NULL OR id=$3) AND ($4<>'threads' OR kind='thread') ORDER BY id LIMIT 10"))
            .bind(q.q.trim()).bind(&q.kind).bind(q.object_id).bind(&q.scope).fetch_all(&mut *tx).await?;
        for id in exact {
            scores.entry(id).or_insert((0.0, format!("object:{id}"))).0 += 1.0;
        }
    }
    let mut ranked: Vec<_> = scores.into_iter().collect();
    ranked.sort_by(|a, b| b.1.0.total_cmp(&a.1.0).then(a.0.cmp(&b.0)));
    let mut context = json!({"objects":[],"connections":[]});
    let mut ids = Vec::new();
    let mut truncated = false;
    for (id, (_, reference)) in ranked.into_iter().take(q.limit) {
        let mut value = summary(&mut tx, id).await?;
        value["match"] = match_metadata(&reference);
        context["objects"].as_array_mut().unwrap().push(value);
        if context.to_string().len() > q.budget {
            context["objects"].as_array_mut().unwrap().pop();
            truncated = true;
        } else {
            ids.push(id);
        }
    }
    // Only Object-to-Object knowledge edges expand discovery. Typed activity,
    // user and raw-copy links are deliberately read through their own readers.
    // Prefer query relevance in the neighbour/edge, then direct-candidate rank.
    let edges = if ids.is_empty() {
        Vec::new()
    } else {
        sqlx::query_scalar::<_, Value>(&edges_query())
            .bind(&ids)
            .bind(&q.q)
            .bind(q.neighbours > 0)
            .fetch_all(&mut *tx)
            .await?
    };
    let mut included = ids.clone();
    for edge in edges {
        if context["connections"].as_array().unwrap().len() >= 10 {
            truncated = true;
            break;
        }
        let from: Uuid = serde_json::from_value(edge["from_id"].clone()).unwrap();
        let to: Uuid = serde_json::from_value(edge["to_id"].clone()).unwrap();
        let other = if ids.contains(&from) { to } else { from };
        let needs = !included.contains(&other);
        if needs && included.len() - ids.len() >= q.neighbours {
            truncated = true;
            continue;
        }
        if needs {
            let mut value = summary(&mut tx, other).await?;
            value["match"] = json!({"relation":"existing_connection"});
            context["objects"].as_array_mut().unwrap().push(value);
        }
        context["connections"].as_array_mut().unwrap().push(edge);
        if context.to_string().len() > q.budget {
            context["connections"].as_array_mut().unwrap().pop();
            if needs {
                context["objects"].as_array_mut().unwrap().pop();
            }
            truncated = true;
        } else if needs {
            included.push(other);
        }
    }
    Ok(Json(
        json!({"mode":mode,"reason":reason,"scope":q.scope,"index":index,"context_bytes":context.to_string().len(),"budget":q.budget,
        "timings":{"model_attempted":model_attempted,"model_ms":model_elapsed.as_secs_f64()*1000.0,
          "database_and_projection_ms":(before_model+after_model.elapsed()).as_secs_f64()*1000.0},
        "truncated":truncated,"primary_count":ids.len(),"neighbour_count":included.len()-ids.len(),"context":context,
        "guidance":"Compact Object candidates, not verified answers. Connected context is separately labelled; read selected Objects and exact Artifact windows deliberately. One Object vector includes body; title/description priority is a separate keyword signal."}),
    ))
}

/// Match locators always address the exact original or correction field. They
/// never reuse corrected offsets against an original Artifact's text endpoint.
fn match_metadata(reference: &str) -> Value {
    let mut result = json!({"reference":reference,"relation":"query_candidate"});
    let parts: Vec<&str> = reference.split(':').collect();
    let (read, field, offsets) = match parts.as_slice() {
        ["object", id] => (
            json!({"resource":"object","id":id}),
            "title+description+body".to_owned(),
            &parts[2..],
        ),
        ["thread", id, revision, ..] => (
            json!({"resource":"thread_text","id":id,"expected_revision":revision.parse::<i64>().ok()}),
            "conversation_text".to_owned(),
            &parts[3..],
        ),
        ["artifact", id, ..] => {
            result["artifact_id"] = json!(id);
            (
                json!({"resource":"artifact","id":id}),
                "text".to_owned(),
                &parts[2..],
            )
        }
        ["correction", id, "artifact", artifact, field, ..] => {
            result["artifact_id"] = json!(artifact);
            result["correction_id"] = json!(id);
            (
                json!({"resource":"correction","id":id,"field":field}),
                format!("representation.{field}"),
                &parts[5..],
            )
        }
        _ => return result,
    };
    result["read"] = read;
    result["field"] = json!(field);
    if let [start, end] = offsets
        && let (Ok(start), Ok(end)) = (start.parse::<usize>(), end.parse::<usize>())
        && end >= start
    {
        result["locator"] =
            json!({"unit":"unicode_characters","field":field,"start":start,"end":end});
        if parts[0] == "artifact" || parts[0] == "correction" || parts[0] == "thread" {
            result["read"]["offset"] = json!(start);
            result["read"]["limit"] = json!(end - start);
        }
    }
    result
}

async fn summary(tx: &mut sqlx::Transaction<'_, sqlx::Postgres>, id: Uuid) -> Result<Value> {
    sqlx::query_scalar("SELECT jsonb_build_object('id',id,'kind',kind,'title',title,'description',description,'revision',revision,'read','/api/objects/'||id::text) FROM objects WHERE id=$1")
        .bind(id).fetch_one(&mut **tx).await.map_err(Into::into)
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Orientation {
    limit: i64,
}
impl Default for Orientation {
    fn default() -> Self {
        Self { limit: 10 }
    }
}
pub async fn orientation(
    State(app): State<App>,
    headers: HeaderMap,
    Query(q): Query<Orientation>,
) -> Result<Json<Value>> {
    if !(1..=20).contains(&q.limit) {
        return Err(invalid("limit1–20 required"));
    }
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let objects=sqlx::query_scalar::<_,Value>(&format!("WITH eligible AS ({ELIGIBLE}) SELECT jsonb_build_object('id',o.id,'kind',o.kind,'title',o.title,'description',o.description,'revision',o.revision) FROM eligible o ORDER BY (SELECT count(*) FROM connections WHERE from_id=o.id OR to_id=o.id) DESC,o.id LIMIT $1"))
        .bind(q.limit).fetch_all(&mut *tx).await?;
    Ok(Json(
        json!({"objects":objects,"schema":{"object_kinds":atomic::KINDS,"objects":"Bounded atomic title, explicit description and body; one embedding, at most500 formatted model tokens.","artifacts":"Long original evidence, deliberately read and chunkable.","connections":"Explained typed links; read actual endpoints and evidence."},"guidance":"Optional overview; centrality is not relevance or truth. Ordinary tool use needs no orientation call."}),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn diagnostic_metadata_never_copies_private_plan_fields() {
        let raw = json!([{"Plan":{"Node Type":"Hash Join","Actual Rows":42,
          "Filter":"PRIVATE literal", "Output":["PRIVATE body"], "Relation Name":"PRIVATE table",
          "Plans":[{"Node Type":"CTE Scan","Actual Loops":2,"CTE Name":"PRIVATE alias"}]},
          "Execution Time":1.5,"Settings":{"jit":"off","search_path":"PRIVATE setting"},
          "Query Text":"PRIVATE query"}]);
        let safe = plan_metadata(&raw);
        assert_eq!(safe["root"]["Actual Rows"], 42);
        assert_eq!(safe["root"]["children"][0]["Actual Loops"], 2);
        assert_eq!(safe["Execution Time"], 1.5);
        assert!(!safe.to_string().contains("PRIVATE"));
        assert_eq!(safe["settings"], json!({"jit":"off"}));
    }
    #[test]
    fn correction_locator_never_addresses_original_artifact_offsets() {
        let correction = Uuid::new_v4();
        let artifact = Uuid::new_v4();
        let m = match_metadata(&format!(
            "correction:{correction}:artifact:{artifact}:body:2:9"
        ));
        assert_eq!(m["read"]["resource"], "correction");
        assert_eq!(m["read"]["id"], correction.to_string());
        assert_eq!(m["locator"]["field"], "representation.body");
        assert_eq!(m["locator"]["start"], 2);
        assert_eq!(m["read"]["field"], "body");
        assert_eq!(m["read"]["offset"], 2);
        let original = match_metadata(&format!("artifact:{artifact}:2:9"));
        assert_eq!(original["read"]["resource"], "artifact");
        assert_eq!(original["read"]["offset"], 2);
        assert_eq!(original["read"]["limit"], 7);
    }
    #[test]
    fn artifact_windows_are_exact_bounded_and_cover_the_tail() {
        let original = "Résumé 東京 — a useful passage. ".repeat(250);
        let packets = artifact_packets("Evidence", &original).unwrap();
        let chars: Vec<char> = original.chars().collect();
        assert!(packets.len() > 1);
        let mut covered = 0;
        for (start, end, input) in packets {
            assert!(start <= covered && end > start);
            let text: String = chars[start..end].iter().collect();
            assert_eq!(input, packet::input("Evidence", "", &text));
            assert!(packet::count("Evidence", "", &text).unwrap() <= 500);
            covered = end;
        }
        assert_eq!(covered, chars.len());
        assert!(artifact_packets("Evidence", "").unwrap().is_empty());
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ThreadWindow {
    expected_revision: i64,
    #[serde(default)]
    offset: i64,
    limit: i64,
}
/// Exact current visible-body projection used by search; revisions fence appended/corrected content.
pub async fn thread_text(
    State(app): State<App>,
    h: HeaderMap,
    Path(id): Path<Uuid>,
    Query(q): Query<ThreadWindow>,
) -> Result<Json<Value>> {
    if q.offset < 0 || !(1..=48000).contains(&q.limit) {
        return Err(invalid("offset>=0 and limit1–48000 required"));
    }
    let mut tx = app.db.begin().await?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        .execute(&mut *tx)
        .await?;
    actor(&app, &h, &mut tx, false).await?;
    conversations::active(&mut tx, id).await?;
    let o = atomic::object(&mut tx, id, false).await?;
    if o["kind"] != "thread" {
        return Err(invalid("Not a Thread"));
    }
    if o["revision"] != q.expected_revision {
        return Err(fail(
            StatusCode::CONFLICT,
            "Thread revision conflict; repeat search",
        ));
    }
    let thread_body = thread_body();
    let text: String = sqlx::query_scalar(&format!(
        "SELECT 'title: '||o.title||' | text: '||o.description||E'\n\n'||t.text FROM objects o CROSS JOIN LATERAL({thread_body}) t WHERE o.id=$1"
    ))
    .bind(id)
    .fetch_one(&mut *tx)
    .await?;
    let total = text.chars().count() as i64;
    let end = (q.offset + q.limit).min(total);
    let window: String = text
        .chars()
        .skip(q.offset as usize)
        .take(q.limit as usize)
        .collect();
    Ok(Json(
        json!({"thread_id":id,"revision":q.expected_revision,"field":"conversation_text","text":window,"offset":q.offset,"total_characters":total,"next_offset":(end<total).then_some(end),"coverage":o["provenance"]["capture"]["coverage"],"guidance":"Stored visible bodies and current corrections only; capture coverage can be partial. Native span telemetry is separate."}),
    ))
}
