//! Supplied visible interactions, not an agent runtime or a claim of verified authorship.
use super::*;

pub const CONTRACT: &str = "commons.capture/1";

// Admit writes concurrently, but finish every admitted write before enumerating
// a deletion's managed copies. Late corrections/imports cannot slip behind cleanup.
pub async fn write_gate(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    deleting: bool,
) -> Result<()> {
    let sql = if deleting {
        "SELECT pg_advisory_xact_lock(hashtextextended('commons:capture-deletion',0))"
    } else {
        "SELECT pg_advisory_xact_lock_shared(hashtextextended('commons:capture-deletion',0))"
    };
    sqlx::query(sql).execute(&mut **tx).await?;
    Ok(())
}

#[derive(Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct Source {
    provider: String,
    namespace: String,
    thread_id: String,
}

#[derive(Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
struct Coverage {
    status: String,
    messages: String,
    tools: String,
    attachments: String,
    history: String,
    #[serde(default)]
    gaps: Vec<String>,
}

#[derive(Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
struct Item {
    id: Uuid,
    source_item_id: String,
    turn_id: Option<String>,
    position: i64,
    kind: String,
    role: String,
    speaker_id: Option<Uuid>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    model: Option<Value>,
    source_created_at: Option<String>,
    body: String,
    tool_name: Option<String>,
    tool_call_id: Option<String>,
    status: Option<String>,
    #[serde(default)]
    artifact_ids: Vec<Uuid>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Attachment {
    id: Uuid,
    artifact: Value,
}

#[derive(Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunInput {
    pub id: Uuid,
    pub expected_revision: Option<i64>,
    pub parent_run_id: Option<Uuid>,
    pub source_run_id: String,
    pub kind: String,
    pub status: String,
    pub actor_id: Option<Uuid>,
    pub primary_object_id: Option<Uuid>,
    #[serde(default = "empty_object")]
    pub input: Value,
    #[serde(default = "empty_array")]
    pub trace: Value,
    #[serde(default = "empty_object")]
    pub result: Value,
    pub error: Option<String>,
    #[serde(default = "empty_object")]
    pub review: Value,
    #[serde(default)]
    pub consulted_object_ids: Vec<Uuid>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    object_effects: Vec<ObjectEffect>,
    pub source_created_at: Option<String>,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
}

#[derive(Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
struct ObjectEffect {
    id: Uuid,
    revision: i64,
    operation: ObjectOperation,
}

#[derive(Deserialize, serde::Serialize)]
#[serde(rename_all = "snake_case")]
enum ObjectOperation {
    Read,
    Created,
    Updated,
}

fn empty_object() -> Value {
    json!({})
}
fn empty_array() -> Value {
    json!([])
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Envelope {
    contract_version: String,
    source: Source,
    batch_id: String,
    chat_id: Option<Uuid>,
    parent_chat_id: Option<Uuid>,
    title: String,
    on_behalf_of: Option<Uuid>,
    #[serde(default)]
    history: bool,
    coverage: Coverage,
    #[serde(default)]
    items: Vec<Item>,
    #[serde(default)]
    attachments: Vec<Attachment>,
    #[serde(default)]
    runs: Vec<RunInput>,
}

fn bounded(value: &str, limit: usize) -> Result<()> {
    if value.trim().is_empty() || value.len() > limit {
        return Err(invalid(
            "capture field is empty or exceeds its documented limit",
        ));
    }
    Ok(())
}
fn timestamp(value: &Option<String>) -> Result<()> {
    if let Some(value) = value {
        chrono::DateTime::parse_from_rfc3339(value)
            .map_err(|_| invalid("source timestamps must be RFC3339 or null"))?;
    }
    Ok(())
}

pub async fn active(tx: &mut atomic::Tx<'_>, oid: Uuid) -> Result<()> {
    let gone=sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM objects WHERE id=$1 AND (provenance->>'deleted_at' IS NOT NULL OR provenance->'capture'->>'deleted_at' IS NOT NULL)) OR EXISTS(SELECT 1 FROM connections c JOIN objects s ON s.id=c.from_id WHERE c.kind='managed_copy' AND c.to_id=$1 AND s.provenance->'capture'->>'deleted_at' IS NOT NULL)").bind(oid).fetch_one(&mut **tx).await?;
    if gone {
        return Err(fail(StatusCode::GONE, "conversation evidence deleted"));
    }
    Ok(())
}
async fn user_reference(tx: &mut atomic::Tx<'_>, uid: Option<Uuid>) -> Result<()> {
    if let Some(uid) = uid
        && !sqlx::query_scalar::<_, bool>("SELECT EXISTS(SELECT 1 FROM users WHERE id=$1)")
            .bind(uid)
            .fetch_one(&mut **tx)
            .await?
    {
        return Err(invalid("User identity not found"));
    }
    Ok(())
}
pub async fn submit(
    State(app): State<App>,
    headers: HeaderMap,
    Json(raw): Json<Value>,
) -> Result<Json<Value>> {
    let input: Envelope = serde_json::from_value(raw.clone())
        .map_err(|_| invalid("Invalid commons.capture/1 envelope"))?;
    if input.contract_version != CONTRACT
        || raw.to_string().len() > 30 * 1024 * 1024
        || input.items.len() > 200
        || input.attachments.len() > 20
        || input.runs.len() > 50
    {
        return Err(invalid("Capture contract or batch limits exceeded"));
    }
    for (v, l) in [
        (&input.source.provider, 100),
        (&input.source.namespace, 300),
        (&input.source.thread_id, 300),
        (&input.batch_id, 200),
    ] {
        bounded(v, l)?;
    }
    if !["complete", "partial", "failed", "empty"].contains(&input.coverage.status.as_str())
        || input.coverage.gaps.len() > 50
    {
        return Err(invalid("Invalid coverage"));
    }
    if serde_json::to_value(&input.coverage)
        .unwrap()
        .to_string()
        .len()
        > 4000
    {
        return Err(invalid(
            "Coverage metadata exceeds4000 bytes; keep detailed logs in trace items",
        ));
    }
    let mut tx = app.db.begin().await?;
    let mut a = actor(&app, &headers, &mut tx, true).await?;
    attribution::context(&mut tx, &mut a, &json!(input.on_behalf_of)).await?;
    a.write("thread")?;
    write_gate(&mut tx, false).await?;
    if input.history {
        a.admin()?;
    }
    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))")
        .bind(format!(
            "capture:{}:{}:{}",
            input.source.provider, input.source.namespace, input.source.thread_id
        ))
        .execute(&mut *tx)
        .await?;
    let existing=sqlx::query_scalar::<_,Value>("SELECT to_jsonb(o) FROM objects o WHERE kind='thread' AND provenance->'capture'->>'provider'=$1 AND provenance->'capture'->>'namespace'=$2 AND provenance->'capture'->>'thread_id'=$3 FOR UPDATE").bind(&input.source.provider).bind(&input.source.namespace).bind(&input.source.thread_id).fetch_optional(&mut *tx).await?;
    let chat = if let Some(o) = existing {
        let oid = Uuid::parse_str(o["id"].as_str().unwrap()).unwrap();
        active(&mut tx, oid).await?;
        if o["provenance"]["capture"]["owner_id"].as_str() != Some(&a.id.to_string())
            && !(a.role == "admin" && a.mode == "session")
        {
            return Err(fail(
                StatusCode::FORBIDDEN,
                "Capture belongs to another submitting identity",
            ));
        }
        if input.chat_id.is_some_and(|id| id != oid) {
            return Err(fail(
                StatusCode::CONFLICT,
                "Source already has a different Thread ID",
            ));
        }
        oid
    } else {
        let oid = input.chat_id.unwrap_or_else(Uuid::new_v4);
        let desc = format!(
            "A captured {} conversation titled “{}”.",
            input.source.provider, input.title
        );
        packet::validate(&input.title, &desc, "")?;
        if let Some(parent) = input.parent_chat_id {
            active(&mut tx, parent).await?;
            let p = atomic::object(&mut tx, parent, false).await?;
            if p["kind"] != "thread" {
                return Err(invalid("Parent must be a Thread"));
            }
        }
        let capture = json!({"provider":input.source.provider,"namespace":input.source.namespace,"thread_id":input.source.thread_id,"owner_id":a.id,"parent_chat_id":input.parent_chat_id,"coverage":input.coverage,"deleted_at":null});
        sqlx::query("INSERT INTO objects(id,kind,title,description,metadata,provenance) VALUES($1,'thread',$2,$3,jsonb_build_object('created_by',$4::uuid,'updated_by',$4::uuid,'created_at',now(),'updated_at',now()),jsonb_build_object('capture',$5::jsonb))").bind(oid).bind(&input.title).bind(desc).bind(a.id).bind(capture).execute(&mut *tx).await?;
        audit(&mut tx, &a, oid, 1, "thread_created").await?;
        oid
    };
    let hash = attribution::request_hash(&raw, &a);
    if let Some(r)=sqlx::query("SELECT request_hash,result FROM request_receipts WHERE namespace='capture' AND owner_id=$1 AND request_key=$2").bind(chat).bind(&input.batch_id).fetch_optional(&mut *tx).await?{if r.get::<String,_>("request_hash")!=hash{return Err(fail(StatusCode::CONFLICT,"Batch key already used for different content"));}return Ok(Json(r.get("result")));}
    let rev = sqlx::query_scalar::<_, i64>("SELECT revision FROM objects WHERE id=$1 FOR UPDATE")
        .bind(chat)
        .fetch_one(&mut *tx)
        .await?;
    let telemetry_only = input.items.is_empty()
        && !input.runs.is_empty()
        && input.runs.iter().all(|r| r.kind == telemetry::KIND);
    let mut artifacts = Vec::new();
    for attachment in input.attachments {
        let mut ai: evidence::ArtifactInput = serde_json::from_value(attachment.artifact)
            .map_err(|_| invalid("Invalid attachment"))?;
        ai.semantic_indexing_enabled = false;
        evidence::insert(&mut tx, &a, chat, ai, attachment.id, false).await?;
        artifacts.push(attachment.id);
    }
    let mut items = Vec::new();
    for item in input.items {
        items.push(save_item(&mut tx, &a, chat, item).await?);
    }
    let mut runs = Vec::new();
    for run in input.runs {
        save_run(&mut tx, &a, chat, &run).await?;
        runs.push(run.id);
    }
    if !telemetry_only {
        sqlx::query("UPDATE objects SET provenance=jsonb_set(provenance,'{capture,coverage}',$2::jsonb) WHERE id=$1").bind(chat).bind(serde_json::to_value(input.coverage).unwrap()).execute(&mut *tx).await?;
    }
    bump(&mut tx, &a, chat, rev, "capture_received").await?;
    let result = json!({"chat_id":chat,"thread_id":chat,"revision":rev+1,"item_ids":items,"artifact_ids":artifacts,"run_ids":runs,"trace_ids":runs});
    sqlx::query("INSERT INTO request_receipts(namespace,owner_id,request_key,request_hash,result,credential_id,thread_id,actor_id) VALUES('capture',$1,$2,$3,$4,$5,$1,$6)").bind(chat).bind(input.batch_id).bind(hash).bind(&result).bind(a.credential).bind(a.id).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(Json(result))
}
async fn save_item(tx: &mut atomic::Tx<'_>, a: &Actor, thread: Uuid, item: Item) -> Result<Uuid> {
    bounded(&item.source_item_id, 300)?;
    timestamp(&item.source_created_at)?;
    user_reference(tx, item.speaker_id).await?;
    if item.position < 0
        || item.body.len() > 1024 * 1024
        || item.artifact_ids.len() > 50
        || !["message", "tool_call", "tool_result", "log"].contains(&item.kind.as_str())
        || !["human", "agent", "tool", "system"].contains(&item.role.as_str())
    {
        return Err(invalid(
            "Invalid visible item; hidden reasoning is not an item kind",
        ));
    }
    for aid in &item.artifact_ids {
        if !sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM artifacts WHERE id=$1 AND object_id=$2 AND deleted_at IS NULL)").bind(aid).bind(thread).fetch_one(&mut **tx).await?{return Err(invalid("Attachment must belong to this Thread"));}
    }
    if item
        .model
        .as_ref()
        .is_some_and(|m| !m.is_object() || m.to_string().len() > 2000)
    {
        return Err(invalid("model telemetry must be a bounded object"));
    }
    let payload = serde_json::to_value(&item).unwrap();
    let hash = digest(&payload.to_string());
    if let Some(r) = sqlx::query(
        "SELECT id,payload_hash FROM trace_items WHERE thread_id=$1 AND source_item_id=$2",
    )
    .bind(thread)
    .bind(&item.source_item_id)
    .fetch_optional(&mut **tx)
    .await?
    {
        if r.get::<String, _>("payload_hash") != hash {
            return Err(fail(
                StatusCode::CONFLICT,
                "Source item is immutable; use a correction",
            ));
        }
        return Ok(r.get("id"));
    }
    sqlx::query("INSERT INTO trace_items(id,thread_id,source_item_id,turn_id,position,kind,role,speaker_id,source_created_at,payload,payload_hash) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::text::timestamptz,$10,$11)").bind(item.id).bind(thread).bind(item.source_item_id).bind(item.turn_id).bind(item.position).bind(item.kind).bind(item.role).bind(item.speaker_id).bind(item.source_created_at).bind(payload).bind(hash).execute(&mut **tx).await?;
    sqlx::query("UPDATE trace_items SET provenance=provenance||jsonb_build_object('attribution',$2::jsonb) WHERE id=$1").bind(item.id).bind(attribution::action(a)).execute(&mut **tx).await?;
    Ok(item.id)
}
async fn save_run(tx: &mut atomic::Tx<'_>, a: &Actor, thread: Uuid, r: &RunInput) -> Result<()> {
    user_reference(tx, r.actor_id).await?;
    for t in [&r.source_created_at, &r.started_at, &r.completed_at] {
        timestamp(t)?;
    }
    bounded(&r.source_run_id, 300)?;
    if !r.object_effects.is_empty()
        && (r.kind != "commons-tool-call"
            || r.object_effects.len() > 50
            || r.object_effects.iter().any(|effect| effect.revision <= 0))
    {
        return Err(invalid("Invalid Commons tool-call Object effects"));
    }

    if !r.trace.is_array() || r.trace.to_string().len() > 1024 * 1024 {
        return Err(invalid("Trace steps must be a bounded array"));
    }
    if sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS(SELECT 1 FROM traces WHERE id=$1 AND deleted_at IS NOT NULL)",
    )
    .bind(r.id)
    .fetch_one(&mut **tx)
    .await?
    {
        return Err(fail(
            StatusCode::GONE,
            "Trace evidence deleted; replay forbidden",
        ));
    }
    let prior = sqlx::query_scalar::<_, i64>(
        "SELECT revision FROM traces WHERE id=$1 AND thread_id=$2 FOR UPDATE",
    )
    .bind(r.id)
    .bind(thread)
    .fetch_optional(&mut **tx)
    .await?;
    if prior != r.expected_revision {
        return Err(fail(StatusCode::CONFLICT, "Trace revision conflict"));
    }
    if r.kind == telemetry::KIND {
        telemetry::validate(&r.source_run_id, &r.trace)?;
    }
    // Trace identity is bound to its original thread and native source ID.
    if let Some(identity) = sqlx::query("SELECT thread_id,source_id,kind FROM traces WHERE id=$1")
        .bind(r.id)
        .fetch_optional(&mut **tx)
        .await?
        && (identity.get::<Option<Uuid>, _>("thread_id") != Some(thread)
            || identity.get::<Option<String>, _>("source_id").as_deref() != Some(&r.source_run_id)
            || identity.get::<String, _>("kind") != r.kind)
    {
        return Err(fail(StatusCode::CONFLICT, "Trace identity cannot change"));
    }
    let mut details = serde_json::to_value(r).unwrap();
    let detail_fields = details.as_object_mut().unwrap();
    detail_fields.remove("trace");
    detail_fields.remove("object_effects");
    details["attribution"] = attribution::action(a);
    let saved = sqlx::query("INSERT INTO traces(id,thread_id,parent_id,source_id,kind,status,actor_id,primary_object_id,started_at,completed_at,details) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::text::timestamptz,$10::text::timestamptz,$11) ON CONFLICT(id) DO UPDATE SET kind=$5,status=$6,primary_object_id=$8,started_at=$9::text::timestamptz,completed_at=$10::text::timestamptz,details=$11,revision=traces.revision+1 WHERE traces.thread_id=$2 AND traces.source_id=$4 AND traces.kind=$5 AND traces.revision=$12")
 .bind(r.id).bind(thread).bind(r.parent_run_id).bind(&r.source_run_id).bind(&r.kind).bind(&r.status).bind(r.actor_id.or(Some(a.id))).bind(r.primary_object_id).bind(&r.started_at).bind(&r.completed_at).bind(&details).bind(r.expected_revision.unwrap_or(0)).execute(&mut **tx).await?;
    if saved.rows_affected() != 1 {
        return Err(fail(
            StatusCode::CONFLICT,
            "Trace identity or revision conflict",
        ));
    }
    let position_base = if r.kind == telemetry::KIND {
        sqlx::query_scalar::<_, i64>(
            "SELECT COALESCE(max(position),-1)+1 FROM trace_items WHERE trace_id=$1",
        )
        .bind(r.id)
        .fetch_one(&mut **tx)
        .await?
    } else {
        0
    };
    for (i, step) in r.trace.as_array().unwrap().iter().enumerate() {
        let key = if r.kind == telemetry::KIND {
            format!(
                "span:{}",
                step["span"]["spanId"]
                    .as_str()
                    .unwrap()
                    .to_ascii_lowercase()
            )
        } else {
            format!("step:{i}")
        };
        let hash = digest(&step.to_string());
        let old = sqlx::query_scalar::<_, String>(
            "SELECT payload_hash FROM trace_items WHERE trace_id=$1 AND source_item_id=$2",
        )
        .bind(r.id)
        .bind(&key)
        .fetch_optional(&mut **tx)
        .await?;
        if let Some(old) = old {
            if old != hash {
                return Err(fail(StatusCode::CONFLICT, "Existing trace step changed"));
            }
        } else {
            sqlx::query("INSERT INTO trace_items(id,trace_id,source_item_id,position,kind,payload,payload_hash) VALUES($1,$2,$3,$4,'step',$5,$6)").bind(Uuid::new_v4()).bind(r.id).bind(key).bind(position_base + i as i64).bind(step).bind(hash).execute(&mut **tx).await?;
        }
    }
    sqlx::query("UPDATE trace_items SET provenance=provenance||jsonb_build_object('attribution',$2::jsonb) WHERE trace_id=$1 AND NOT provenance ? 'attribution'").bind(r.id).bind(attribution::action(a)).execute(&mut **tx).await?;
    for oid in &r.consulted_object_ids {
        let o = atomic::object(tx, *oid, false).await?;
        sqlx::query("INSERT INTO connections(id,from_trace_id,to_id,kind,explanation,provenance) SELECT $1,$2,$3,'consulted','Object recorded as consulted by this execution.',$4 WHERE NOT EXISTS(SELECT 1 FROM connections WHERE from_trace_id=$2 AND to_id=$3 AND kind='consulted')").bind(Uuid::new_v4()).bind(r.id).bind(oid).bind(json!({"operation":"read","object_revision":o["revision"],"attribution":attribution::action(a)})).execute(&mut **tx).await?;
    }
    for effect in &r.object_effects {
        let (kind, operation) = match effect.operation {
            ObjectOperation::Read => ("consulted", "read"),
            ObjectOperation::Created => ("created", "created"),
            ObjectOperation::Updated => ("updated", "updated"),
        };
        // A delayed capture can outlive the target. Keep the Trace without
        // making an invalid or deleted target block the whole capture batch.
        sqlx::query("INSERT INTO connections(id,from_trace_id,to_id,kind,explanation,provenance)
            SELECT $1,$2,o.id,$3,'Object recorded by a successful Commons tool call.',$4
            FROM objects o WHERE o.id=$5 AND o.revision >= $6
            AND NOT o.provenance ? 'deleted_at' AND o.kind <> 'thread'
            AND NOT EXISTS(SELECT 1 FROM connections c WHERE c.from_trace_id=$2 AND c.to_id=o.id AND c.kind=$3)")
            .bind(Uuid::new_v4()).bind(r.id).bind(kind)
            .bind(json!({"operation":operation,"object_revision":effect.revision,"attribution":attribution::action(a)}))
            .bind(effect.id).bind(effect.revision).execute(&mut **tx).await?;
    }
    sqlx::query("INSERT INTO changes(kind,object_id,target_type,target_id,revision,actor_id,credential_id,occurred_at,payload) VALUES('trace',$1,'trace',$2,$3,$4,$5,now(),$6)").bind(thread).bind(r.id).bind(prior.unwrap_or(0)+1).bind(a.id).bind(a.credential).bind(details).execute(&mut **tx).await?;
    Ok(())
}
#[derive(Default, Deserialize)]
#[serde(default)]
pub struct Page {
    format: Option<String>,
    limit: Option<i64>,
    offset: i64,
}
impl Page {
    fn limit(&self) -> Result<i64> {
        let l = self.limit.unwrap_or(50);
        if !(1..=200).contains(&l) || self.offset < 0 {
            return Err(invalid("limit1–200 and nonnegative offset required"));
        }
        Ok(l)
    }
}
pub async fn list_chats(
    State(app): State<App>,
    headers: HeaderMap,
    Query(q): Query<Page>,
) -> Result<Json<Value>> {
    let l = q.limit()?;
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let total=sqlx::query_scalar::<_,i64>("SELECT count(*) FROM objects WHERE kind='thread' AND COALESCE(provenance->>'historical_only','false')<>'true' AND provenance->'capture'->>'deleted_at' IS NULL").fetch_one(&mut *tx).await?;
    let mut rows=sqlx::query_scalar::<_,Value>("SELECT jsonb_build_object('id',o.id,'title',o.title,'provider',o.provenance->'capture'->>'provider','coverage',o.provenance->'capture'->'coverage','imported',o.provenance->'import' IS NOT NULL AND o.provenance->'import'<>'null','updated_at',o.metadata->'updated_at','participants',COALESCE((SELECT jsonb_agg(jsonb_build_object('user_object_id',u.id,'title',u.title,'user_kind',u.user_kind,'role','participant')) FROM users u WHERE u.id IN(SELECT speaker_id FROM trace_items WHERE thread_id=o.id)),'[]'::jsonb)) FROM objects o WHERE kind='thread' AND COALESCE(provenance->>'historical_only','false')<>'true' AND provenance->'capture'->>'deleted_at' IS NULL ORDER BY o.metadata->>'updated_at' DESC NULLS LAST,o.id LIMIT $1 OFFSET $2").bind(l).bind(q.offset).fetch_all(&mut *tx).await?;
    for row in &mut rows {
        row["participants"] = json!(
            attribution::users(
                &mut tx,
                Uuid::parse_str(row["id"].as_str().unwrap()).unwrap()
            )
            .await?
        );
    }
    Ok(Json(
        json!({"objects":rows,"threads":rows,"total":total,"next_offset":(q.offset+l<total).then_some(q.offset+l)}),
    ))
}
pub async fn list_runs(
    State(app): State<App>,
    headers: HeaderMap,
    Query(q): Query<Page>,
) -> Result<Json<Value>> {
    let l = q.limit()?;
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let native = match q.format.as_deref() {
        None | Some("all") => None,
        Some("native") => Some(true),
        Some("history") => Some(false),
        _ => return Err(invalid("Trace format must be native, history or all")),
    };
    let total = sqlx::query_scalar::<_, i64>("SELECT count(*) FROM traces WHERE deleted_at IS NULL AND ($1::boolean IS NULL OR (kind='opentelemetry')=$1)")
        .bind(native).fetch_one(&mut *tx).await?;
    let mut rows=sqlx::query_scalar::<_,Value>("SELECT to_jsonb(t)||jsonb_build_object('source_created_at',t.details->'source_created_at','imported',t.details->'import_provenance' IS NOT NULL,'thread_title',o.title,'provider',o.provenance->'capture'->>'provider','span_count',CASE WHEN t.kind='opentelemetry' THEN (SELECT count(*) FROM trace_items i WHERE i.trace_id=t.id) ELSE NULL END) FROM traces t LEFT JOIN objects o ON o.id=t.thread_id WHERE t.deleted_at IS NULL AND ($3::boolean IS NULL OR (t.kind='opentelemetry')=$3) ORDER BY t.received_at DESC,t.id LIMIT $1 OFFSET $2").bind(l).bind(q.offset).bind(native).fetch_all(&mut *tx).await?;
    for row in &mut rows {
        row["participants"] = json!(
            attribution::users(
                &mut tx,
                Uuid::parse_str(row["id"].as_str().unwrap()).unwrap()
            )
            .await?
        );
    }
    Ok(Json(
        json!({"runs":rows,"traces":rows,"total":total,"next_offset":(q.offset+l<total).then_some(q.offset+l)}),
    ))
}
pub async fn read_chat(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
    Query(q): Query<Page>,
) -> Result<Json<Value>> {
    let l = q.limit()?;
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    active(&mut tx, id).await?;
    let o = atomic::object(&mut tx, id, false).await?;
    if o["kind"] != "thread" {
        return Err(invalid("Not a Thread"));
    }
    let total = sqlx::query_scalar::<_, i64>("SELECT count(*) FROM trace_items WHERE thread_id=$1")
        .bind(id)
        .fetch_one(&mut *tx)
        .await?;
    let mut rows=sqlx::query_scalar::<_,Value>("SELECT i.payload||jsonb_build_object('id',i.id,'kind',i.kind,'role',i.role,'speaker_id',i.speaker_id,'speaker_name',u.title,'source_created_at',i.source_created_at,'source_ingested_at',i.source_ingested_at,'received_at',i.received_at,'import_provenance',i.provenance->'import','attachments',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',a.id,'title',a.title,'media_type',a.media_type,'capture_outcome',a.capture_outcome,'capture_reason',a.capture_reason,'stored',a.body IS NOT NULL OR a.bytes IS NOT NULL)) FROM artifacts a WHERE a.id::text IN(SELECT jsonb_array_elements_text(COALESCE(i.payload->'artifact_ids','[]'::jsonb)))),'[]'::jsonb),'correction',(SELECT c.payload FROM changes c WHERE c.kind='correction' AND c.target_id=i.id ORDER BY c.occurred_at DESC LIMIT 1)) FROM trace_items i LEFT JOIN users u ON u.id=i.speaker_id WHERE i.thread_id=$1 ORDER BY i.position,i.id LIMIT $2 OFFSET $3").bind(id).bind(l).bind(q.offset).fetch_all(&mut *tx).await?;
    for row in &mut rows {
        row["participants"] = json!(
            attribution::users(
                &mut tx,
                Uuid::parse_str(row["id"].as_str().unwrap()).unwrap()
            )
            .await?
        );
    }
    let participants = attribution::users(&mut tx, id).await?;
    let mut capture = o["provenance"]["capture"].clone();
    capture["chat_id"] = json!(id);
    Ok(Json(
        json!({"object":o,"chat":capture,"thread":capture,"items":rows,"participants":participants,"total":total,"next_offset":(q.offset+l<total).then_some(q.offset+l)}),
    ))
}
pub async fn read_run(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let mut r=sqlx::query_scalar::<_,Value>("SELECT t.details||to_jsonb(t)-'details'||jsonb_build_object('parent_run_id',parent_id,'chat_object_id',thread_id,'consulted_object_ids',COALESCE((SELECT jsonb_agg(to_id) FROM connections WHERE from_trace_id=t.id AND kind='consulted'),'[]'::jsonb),'trace',COALESCE((SELECT jsonb_agg(payload ORDER BY position) FROM trace_items WHERE trace_id=t.id),'[]'::jsonb)) FROM traces t WHERE id=$1 AND deleted_at IS NULL").bind(id).fetch_optional(&mut *tx).await?.ok_or_else(||fail(StatusCode::NOT_FOUND,"Trace not found"))?;
    r["participants"] = json!(attribution::users(&mut tx, id).await?);
    Ok(Json(json!({"run":r,"trace":r})))
}
pub async fn chat_relationships(
    State(app): State<App>,
    h: HeaderMap,
    Path(id): Path<Uuid>,
    Query(page): Query<Page>,
) -> Result<Json<Value>> {
    relationships(&app, &h, id, false, page).await
}
pub async fn run_relationships(
    State(app): State<App>,
    h: HeaderMap,
    Path(id): Path<Uuid>,
    Query(page): Query<Page>,
) -> Result<Json<Value>> {
    relationships(&app, &h, id, true, page).await
}
async fn relationships(
    app: &App,
    h: &HeaderMap,
    id: Uuid,
    trace: bool,
    page: Page,
) -> Result<Json<Value>> {
    let limit = page.limit()?;
    let mut tx = app.db.begin().await?;
    actor(app, h, &mut tx, false).await?;
    let rows=sqlx::query_scalar::<_,Value>(&format!("SELECT {} FROM connections c WHERE $1 IN(from_id,to_id,from_trace_id,to_trace_id) ORDER BY c.id LIMIT 200",collections::CONNECTION_JSON)).bind(id).fetch_all(&mut *tx).await?;
    let mut refs = sqlx::query_scalar::<_, Value>(
        "WITH related_traces AS (
            SELECT id,kind,primary_object_id FROM traces
            WHERE deleted_at IS NULL AND (CASE WHEN $2 THEN id=$1 ELSE thread_id=$1 END)
         ), object_refs AS (
            SELECT c.to_id AS id,c.kind AS relation FROM related_traces t
            JOIN connections c ON c.from_trace_id=t.id
            WHERE c.kind IN ('consulted','created','updated') AND c.to_id IS NOT NULL
            UNION SELECT primary_object_id,'primary_object' FROM related_traces WHERE primary_object_id IS NOT NULL
         )
         SELECT jsonb_build_object('id',ref.id,'kind',ref.kind,'title',ref.title,'relation',ref.relation,'archived_at',ref.archived_at)
         FROM (
            SELECT o.id,o.kind,o.title,r.relation,o.metadata->>'archived_at' AS archived_at FROM object_refs r
            JOIN objects o ON o.id=r.id AND NOT o.provenance ? 'deleted_at'
            UNION ALL SELECT id,'trace',kind,'trace',NULL FROM related_traces WHERE NOT $2
         ) ref ORDER BY (ref.relation='trace'),ref.id,ref.relation LIMIT $3 OFFSET $4"
    ).bind(id).bind(trace).bind(limit + 1).bind(page.offset).fetch_all(&mut *tx).await?;
    let next = (refs.len() as i64 > limit).then(|| page.offset.saturating_add(limit));
    refs.truncate(limit as usize);
    Ok(Json(
        json!({"connections":rows,"references":refs,"next_offset":next}),
    ))
}
pub async fn run_history(
    State(app): State<App>,
    h: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &h, &mut tx, false).await?;
    let rows=sqlx::query_scalar::<_,Value>("SELECT payload||jsonb_build_object('id',id,'occurred_at',occurred_at,'revision',revision) FROM changes WHERE target_id=$1 AND target_type IN('run','trace') ORDER BY occurred_at,id").bind(id).fetch_all(&mut *tx).await?;
    Ok(Json(json!({"history":rows})))
}
#[derive(Deserialize)]
pub struct Delete {
    expected_revision: i64,
    acknowledge_managed_copy_deletion: bool,
}
pub async fn delete_chat(
    State(app): State<App>,
    h: HeaderMap,
    Path(id): Path<Uuid>,
    Json(q): Json<Delete>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &h, &mut tx, true).await?;
    a.write("thread")?;
    write_gate(&mut tx, true).await?;
    sqlx::query("SELECT pg_advisory_xact_lock(8138001)")
        .execute(&mut *tx)
        .await?;
    if !q.acknowledge_managed_copy_deletion {
        return Err(invalid("acknowledge_managed_copy_deletion required"));
    }
    let o = atomic::object(&mut tx, id, true).await?;
    if o["kind"] != "thread" {
        return Err(invalid("Not a Thread"));
    }
    if o["revision"].as_i64() != Some(q.expected_revision) {
        return Err(fail(StatusCode::CONFLICT, "Thread revision conflict"));
    }
    if o["provenance"]["capture"]["owner_id"].as_str() != Some(&a.id.to_string())
        && !(a.role == "admin" && a.mode == "session")
    {
        return Err(fail(
            StatusCode::FORBIDDEN,
            "Only owner or administrator may delete this Thread",
        ));
    }
    let managed=sqlx::query_scalar::<_,Uuid>("SELECT to_id FROM connections WHERE from_id=$1 AND kind='managed_copy' AND to_id IS NOT NULL").bind(id).fetch_all(&mut *tx).await?;
    let mut ids = managed;
    ids.push(id);
    let aids=sqlx::query_scalar::<_,Uuid>("SELECT id FROM artifacts WHERE object_id=ANY($1) UNION SELECT to_artifact_id FROM connections WHERE from_id=$2 AND kind='managed_copy' AND to_artifact_id IS NOT NULL").bind(&ids).bind(id).fetch_all(&mut *tx).await?;
    let tids=sqlx::query_scalar::<_,Uuid>("WITH RECURSIVE affected(id) AS (SELECT t.id FROM traces t WHERE t.thread_id=ANY($1) OR t.primary_object_id=ANY($1) OR EXISTS(SELECT 1 FROM connections c WHERE c.from_trace_id=t.id AND (c.to_id=ANY($1) OR c.to_artifact_id=ANY($2))) UNION SELECT t.id FROM traces t JOIN affected x ON t.parent_id=x.id OR t.id=(SELECT parent_id FROM traces WHERE id=x.id)) SELECT id FROM affected").bind(&ids).bind(&aids).fetch_all(&mut *tx).await?;
    let cids=sqlx::query_scalar::<_,Uuid>("SELECT id FROM connections WHERE from_id=ANY($1) OR to_id=ANY($1) OR from_artifact_id=ANY($2) OR to_artifact_id=ANY($2) OR from_trace_id=ANY($3) OR to_trace_id=ANY($3)").bind(&ids).bind(&aids).bind(&tids).fetch_all(&mut *tx).await?;
    let targets: Vec<Uuid> = ids
        .iter()
        .chain(&aids)
        .chain(&tids)
        .chain(&cids)
        .copied()
        .collect();
    sqlx::query("UPDATE artifacts SET body=NULL,bytes=NULL,metadata='{}',title=NULL,uri=NULL,provenance='{}',deleted_at=now(),semantic_indexing_enabled=false WHERE id=ANY($1)").bind(&aids).execute(&mut *tx).await?;
    sqlx::query("DELETE FROM chunks WHERE object_id=ANY($1) OR artifact_id=ANY($2)")
        .bind(&ids)
        .bind(&aids)
        .execute(&mut *tx)
        .await?;
    sqlx::query("DELETE FROM trace_items WHERE thread_id=ANY($1) OR trace_id=ANY($2)")
        .bind(&ids)
        .bind(&tids)
        .execute(&mut *tx)
        .await?;
    sqlx::query("UPDATE traces SET details=jsonb_build_object('deleted_source_id',$2::uuid),deleted_at=now() WHERE id=ANY($1)")
        .bind(&tids).bind(id)
        .execute(&mut *tx)
        .await?;
    sqlx::query("UPDATE changes SET payload=jsonb_build_object('deleted_source_id',$3::uuid) WHERE object_id=ANY($1) OR target_id=ANY($2) OR payload->>'run_id'=ANY(SELECT x::text FROM unnest($4::uuid[]) x)").bind(&ids).bind(&targets).bind(id).bind(&tids).execute(&mut *tx).await?;
    // Scrub affected relationship snapshots without deleting independently
    // authored Object content in other records' histories.
    for path in ["before_state", "after_state"] {
        sqlx::query(&format!("UPDATE changes h SET payload=jsonb_set(h.payload,'{{{path},connections}}',(SELECT COALESCE(jsonb_agg(CASE WHEN e.value->>'id'=ANY(SELECT x::text FROM unnest($1::uuid[]) x) THEN jsonb_build_object('id',e.value->'id','deleted_source_id',$2::uuid) ELSE e.value END),'[]'::jsonb) FROM jsonb_array_elements(h.payload->'{path}'->'connections') e)) WHERE jsonb_typeof(h.payload->'{path}'->'connections')='array'")).bind(&cids).bind(id).execute(&mut *tx).await?;
    }
    sqlx::query("UPDATE connections SET explanation='Relationship to deleted captured material.',provenance=jsonb_build_object('deleted_source_id',$2::uuid),revision=revision+1 WHERE id=ANY($1)").bind(&cids).bind(id).execute(&mut *tx).await?;
    sqlx::query("UPDATE objects SET title='Deleted captured material',description='A deleted captured record; its content has been removed.',body='',fields='{}',provenance=provenance||jsonb_build_object('deleted_at',now()),revision=revision+1 WHERE id=ANY($1)").bind(&ids).execute(&mut *tx).await?;
    sqlx::query("UPDATE objects SET provenance=jsonb_set(provenance,'{capture,deleted_at}',to_jsonb(now())) WHERE id=$1").bind(id).execute(&mut *tx).await?;
    sqlx::query("DELETE FROM request_receipts WHERE namespace='capture' AND thread_id=$1")
        .bind(id)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(Json(
        json!({"id":id,"deleted":true,"revision":q.expected_revision+1}),
    ))
}
