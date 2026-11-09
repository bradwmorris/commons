//! Atomic schema mutations. One validator and transaction boundary for every client.
use super::*;
pub const KINDS: &[&str] = &[
    "task", "note", "entity", "source", "theme", "event", "thread",
];
pub type Tx<'a> = sqlx::Transaction<'a, sqlx::Postgres>;
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str()
        .ok_or_else(|| invalid(&format!("{k} must be a string")))
}
fn id(v: &Value, k: &str) -> Result<Uuid> {
    Uuid::parse_str(text(v, k)?).map_err(|_| invalid(&format!("invalid {k}")))
}
fn revision(v: &Value, k: &str) -> Result<i64> {
    v[k].as_i64()
        .filter(|r| *r > 0)
        .ok_or_else(|| invalid(&format!("{k} must be a positive revision")))
}
pub async fn object(tx: &mut Tx<'_>, id: Uuid, lock: bool) -> Result<Value> {
    let q = if lock {
        "SELECT to_jsonb(o) FROM objects o WHERE id=$1 FOR UPDATE"
    } else {
        "SELECT to_jsonb(o) FROM objects o WHERE id=$1"
    };
    sqlx::query_scalar(q)
        .bind(id)
        .fetch_optional(&mut **tx)
        .await?
        .ok_or_else(|| fail(StatusCode::NOT_FOUND, "Object not found"))
}
pub async fn lock_object(tx: &mut Tx<'_>, a: &Actor, id: Uuid, rev: i64) -> Result<String> {
    conversations::active(tx, id).await?;
    let o = object(tx, id, true).await?;
    let k = o["kind"].as_str().unwrap();
    a.write(k)?;
    if o["revision"].as_i64() != Some(rev) {
        return Err(fail(
            StatusCode::CONFLICT,
            "revision conflict; reload before editing",
        ));
    }
    Ok(k.into())
}
pub async fn audit(tx: &mut Tx<'_>, a: &Actor, id: Uuid, rev: i64, action: &str) -> Result<()> {
    sqlx::query("UPDATE objects SET metadata=metadata||jsonb_build_object('last_action_on_behalf_of',$2::uuid)||CASE WHEN $3 THEN jsonb_build_object('on_behalf_of',$2::uuid) ELSE '{}'::jsonb END WHERE id=$1").bind(id).bind(a.on_behalf_of).bind(rev==1).execute(&mut **tx).await?;
    let state = sqlx::query_scalar::<_, Value>("SELECT to_jsonb(o) FROM objects o WHERE id=$1")
        .bind(id)
        .fetch_optional(&mut **tx)
        .await?;
    let (typ, oid) = if state.is_some() {
        ("object", Some(id))
    } else {
        ("user", None)
    };
    let state = if let Some(o) = state {
        o
    } else {
        sqlx::query_scalar::<_, Value>(
            "SELECT to_jsonb(u)-'password_hash'-'avatar_image' FROM users u WHERE id=$1",
        )
        .bind(id)
        .fetch_one(&mut **tx)
        .await?
    };
    sqlx::query("INSERT INTO changes(kind,object_id,target_type,target_id,revision,actor_id,credential_id,occurred_at,payload) VALUES('history',$1,$2,$3,$4,$5,$6,now(),jsonb_build_object('action',$7::text,'after_state',$8::jsonb,'observation','server','attribution',$9::jsonb))")
 .bind(oid).bind(typ).bind(id).bind(rev).bind(a.id).bind(a.credential).bind(action).bind(json!({"object":state})).bind(attribution::action(a)).execute(&mut **tx).await?;
    Ok(())
}
pub async fn bump(tx: &mut Tx<'_>, a: &Actor, id: Uuid, rev: i64, action: &str) -> Result<()> {
    sqlx::query("UPDATE objects SET revision=revision+1,metadata=metadata||jsonb_build_object('updated_by',$2::uuid,'updated_at',now()) WHERE id=$1").bind(id).bind(a.id).execute(&mut **tx).await?;
    audit(tx, a, id, rev + 1, action).await
}
pub fn issue_url(url: &str) -> Result<String> {
    if !regex::Regex::new(
        r"^https://github[.]com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*$",
    )
    .unwrap()
    .is_match(url)
    {
        return Err(invalid("canonical GitHub Issue URL required"));
    }
    Ok(url.to_ascii_lowercase())
}
pub async fn task_lookup(
    State(app): State<App>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let url = issue_url(
        q.get("github_issue_url")
            .ok_or_else(|| invalid("github_issue_url required"))?,
    )?;
    let o=sqlx::query_scalar::<_,Value>("SELECT to_jsonb(o) FROM objects o WHERE kind='task' AND lower(fields->>'github_issue_url')=$1 AND COALESCE(provenance->>'historical_only','false')<>'true' AND provenance->>'deleted_at' IS NULL").bind(url).fetch_optional(&mut *tx).await?.ok_or_else(||fail(StatusCode::NOT_FOUND,"no Task for this Issue"))?;
    Ok(Json(json!({"object":o})))
}
pub fn field_names(kind: &str) -> &'static [&'static str] {
    match kind {
        "task" => &[
            "status",
            "priority",
            "owner_object_id",
            "agent_suitable",
            "blocked_reason",
            "due_at",
            "completed_at",
            "work_kind",
            "github_issue_url",
            "project",
        ],
        "note" => &[
            "happened_at",
            "intent",
            "content_format",
            "source_artifact_id",
            "source_locator",
        ],
        "entity" => &["entity_kind", "image_url"],
        "source" => &[
            "source_kind",
            "canonical_uri",
            "byline",
            "publisher",
            "published_at",
            "published_at_precision",
            "last_accessed_at",
            "original_language",
            "original_media_type",
            "original_artifact_reference",
            "current_artifact_id",
        ],
        "theme" => &["slug"],
        "event" => &[
            "starts_at",
            "starts_at_precision",
            "ends_at",
            "ends_at_precision",
            "timezone",
        ],
        _ => &[],
    }
}
pub async fn validate(
    tx: &mut Tx<'_>,
    kind: &str,
    title: &str,
    description: &str,
    body: &str,
    fields: &Value,
    previous: Option<&Value>,
) -> Result<()> {
    if !KINDS.contains(&kind) || kind == "thread" {
        return Err(invalid("Unsupported writable kind; Threads use capture"));
    }
    packet::validate(title, description, body)?;
    let map = fields
        .as_object()
        .ok_or_else(|| invalid("fields must be an object"))?;
    if fields.to_string().len() > 16384 {
        return Err(invalid(
            "fields exceed 16 KiB; long content belongs in Artifacts",
        ));
    }
    let allowed = field_names(kind);
    if map.keys().any(|k| !allowed.contains(&k.as_str())) {
        return Err(invalid(
            "Unknown field: content belongs in body; metadata/attribution are server-controlled",
        ));
    }
    for key in [
        "happened_at",
        "due_at",
        "completed_at",
        "published_at",
        "last_accessed_at",
    ] {
        if let Some(v) = map.get(key).filter(|v| !v.is_null()) {
            chrono::DateTime::parse_from_rfc3339(
                v.as_str()
                    .ok_or_else(|| invalid("timestamp must be RFC3339 string"))?,
            )
            .map_err(|_| invalid("timestamp must be RFC3339"))?;
        }
    }
    for (key, value) in map {
        if value.is_null() {
            continue;
        }
        if key == "agent_suitable" {
            if !value.is_boolean() {
                return Err(invalid("agent_suitable must be boolean"));
            }
        } else if key == "source_locator" {
            if !value.is_object() || value.to_string().len() > 2048 {
                return Err(invalid(
                    "source_locator must be a bounded structured locator",
                ));
            }
        } else if !value.is_string() {
            return Err(invalid("Type-specific field must be a string or null"));
        }
        if let Some(v) = value.as_str() {
            let max = if key == "canonical_uri" || key == "image_url" {
                2000
            } else if key == "blocked_reason" {
                1000
            } else {
                600
            };
            if v.chars().count() > max {
                return Err(invalid(
                    "Type-specific field is too long; supporting content belongs in body or an Artifact",
                ));
            }
        }
    }
    if let Some(format) = fields["content_format"].as_str()
        && !["markdown", "plain_text", "plain"].contains(&format)
    {
        return Err(invalid(
            "content_format must be markdown or plain_text (plain is a legacy alias)",
        ));
    }
    for key in [
        "published_at_precision",
        "starts_at_precision",
        "ends_at_precision",
    ] {
        if let Some(v) = fields[key].as_str()
            && !["year", "month", "day", "instant"].contains(&v)
        {
            return Err(invalid("Unsupported timestamp precision"));
        }
    }
    if kind == "event" {
        let start = event_time(&fields["starts_at"], &fields["starts_at_precision"])?;
        let end = event_time(&fields["ends_at"], &fields["ends_at_precision"])?;
        if let (Some(start), Some(end)) = (start, end)
            && (fields["starts_at_precision"] != fields["ends_at_precision"] || start > end)
        {
            return Err(invalid(
                "Event endpoints must have matching precision and nondecreasing order",
            ));
        }
        if let Some(zone) = fields["timezone"].as_str() {
            let tz: chrono_tz::Tz = zone
                .parse()
                .map_err(|_| invalid("timezone must be an IANA name"))?;
            for key in ["starts_at", "ends_at"] {
                if let Some(time) = fields[key]
                    .as_str()
                    .filter(|_| fields[format!("{key}_precision")] == "instant")
                {
                    let time = chrono::DateTime::parse_from_rfc3339(time)
                        .map_err(|_| invalid("invalid instant"))?;
                    use chrono::Offset;
                    if time.offset().local_minus_utc()
                        != time.with_timezone(&tz).offset().fix().local_minus_utc()
                    {
                        return Err(invalid("Event offset does not match timezone"));
                    }
                }
            }
        }
    }
    if kind == "theme" && previous.is_some_and(|o| o["fields"]["slug"] != fields["slug"]) {
        return Err(invalid("Theme slug is immutable"));
    }
    let legacy = if let Some(old) = previous {
        if let Some(change) = old["provenance"]["original_change_id"]
            .as_str()
            .and_then(|s| Uuid::parse_str(s).ok())
        {
            sqlx::query_scalar::<_,Value>("SELECT jsonb_build_object('imported',payload->'import_provenance' IS NOT NULL AND payload->'import_provenance'<>'null','due_at',payload->'fields'->'due_at','owner',payload->'fields'->'owner_object_id') FROM changes WHERE id=$1 AND kind='migration_original'").bind(change).fetch_optional(&mut **tx).await?
        } else {
            None
        }
    } else {
        None
    };
    if kind == "task" {
        for (key, allowed) in [
            (
                "status",
                &["backlog", "todo", "doing", "review", "done", "blocked"][..],
            ),
            ("priority", &["low", "medium", "high"][..]),
            ("work_kind", &["general", "code"][..]),
        ] {
            if !allowed.contains(&text(fields, key)?) {
                return Err(invalid(&format!("Invalid Task {key}")));
            }
        }
        let owner = id(fields, "owner_object_id")?;
        let retained_owner = legacy.as_ref().is_some_and(|l| l["imported"] == true)
            && previous
                .is_some_and(|old| old["fields"]["owner_object_id"] == fields["owner_object_id"]);
        if !retained_owner
            && !sqlx::query_scalar::<_, bool>(
                "SELECT EXISTS(SELECT 1 FROM users WHERE id=$1 AND active)",
            )
            .bind(owner)
            .fetch_one(&mut **tx)
            .await?
        {
            return Err(invalid("Active User owner required"));
        }
        let retained_missing_due = fields["due_at"].is_null()
            && legacy
                .as_ref()
                .is_some_and(|l| l["imported"] == true && l["due_at"].is_null())
            && previous.is_some_and(|old| old["fields"]["due_at"].is_null());
        if !retained_missing_due {
            text(fields, "due_at")?;
        }
        if let Some(u) = fields["github_issue_url"].as_str() {
            issue_url(u)?;
        }
        if let Some(p) = fields["project"].as_str()
            && !regex::Regex::new(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
                .unwrap()
                .is_match(p)
        {
            return Err(invalid("project must be a short slug"));
        }
        if fields["status"] == "doing" && body.trim().is_empty() {
            return Err(invalid(
                "Task body required before doing; long detail can be linked as an Artifact",
            ));
        }
    }
    if kind == "theme"
        && !regex::Regex::new(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
            .unwrap()
            .is_match(text(fields, "slug")?)
    {
        return Err(invalid("Theme slug required"));
    }
    if kind == "source"
        && ![
            "article",
            "paper",
            "podcast_episode",
            "video",
            "book",
            "report",
            "document",
            "dataset",
            "web_page",
            "social_post",
            "other",
        ]
        .contains(&text(fields, "source_kind")?)
    {
        return Err(invalid("supported source_kind required"));
    }
    if let Some(uri) = fields["canonical_uri"].as_str() {
        let u = url::Url::parse(uri).map_err(|_| invalid("canonical_uri must be HTTP(S)"))?;
        if !["http", "https"].contains(&u.scheme()) || uri.len() > 2000 {
            return Err(invalid("canonical_uri must be HTTP(S), at most 2000 bytes"));
        }
    }
    if kind == "source" {
        if fields["published_at"].is_null() != fields["published_at_precision"].is_null() {
            return Err(invalid(
                "Publication timestamp and precision must be supplied together",
            ));
        }
        if !fields["current_artifact_id"].is_null() {
            let aid = id(fields, "current_artifact_id")?;
            let oid = previous
                .and_then(|o| o["id"].as_str())
                .and_then(|s| Uuid::parse_str(s).ok());
            let retained = previous.is_some_and(|o| {
                o["provenance"]["original_change_id"].is_string()
                    && o["fields"]["current_artifact_id"] == fields["current_artifact_id"]
            });
            if !sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM artifacts WHERE id=$1 AND object_id=$2 AND deleted_at IS NULL AND ($3 OR capture_outcome='complete' AND body IS NOT NULL))").bind(aid).bind(oid).bind(retained).fetch_one(&mut **tx).await?{return Err(invalid("Current Artifact must be complete text owned by this Source"));}
        }
    }
    if kind == "note" {
        if let Some(intent) = fields["intent"].as_str()
            && !["idea", "excerpt", "fact", "insight", "question"].contains(&intent)
        {
            return Err(invalid("invalid Note intent"));
        }
        if fields["intent"] == "excerpt" {
            let aid = id(fields, "source_artifact_id")?;
            let source=sqlx::query("SELECT object_id,body FROM artifacts WHERE id=$1 AND deleted_at IS NULL AND body IS NOT NULL").bind(aid).fetch_optional(&mut **tx).await?.ok_or_else(||invalid("Stored source Artifact required for excerpt"))?;
            let parent: Option<Uuid> = source.get("object_id");
            let parent =
                parent.ok_or_else(|| invalid("Excerpt requires an Object-owned text Artifact"))?;
            conversations::active(tx, parent).await?;
            let original: String = source.get("body");
            let retained = previous.is_some_and(|o| {
                o["provenance"]["original_change_id"].is_string()
                    && o["body"] == body
                    && ["intent", "source_artifact_id", "source_locator"]
                        .iter()
                        .all(|k| o["fields"][k] == fields[k])
            });
            if retained {
                if !fields["source_locator"].is_object() {
                    return Err(invalid("Historical locator must be structured"));
                }
            } else {
                if body.is_empty() {
                    return Err(invalid("Excerpt body required"));
                }
                validate_locator(&fields["source_locator"], &original, body)?;
            }
        } else if !fields["source_artifact_id"].is_null() || !fields["source_locator"].is_null() {
            return Err(invalid("Only excerpts carry source evidence locators"));
        }
    }
    Ok(())
}
fn merge_fields(old: &Value, patch: &Value) -> Result<Value> {
    let mut n = old
        .as_object()
        .cloned()
        .ok_or_else(|| invalid("invalid stored fields"))?;
    for (k, v) in patch
        .as_object()
        .ok_or_else(|| invalid("fields must be an object"))?
    {
        if v.is_null() {
            n.remove(k);
        } else {
            n.insert(k.clone(), v.clone());
        }
    }
    Ok(Value::Object(n))
}
async fn snapshot_before(tx: &mut Tx<'_>, a: &Actor, o: &Value) -> Result<()> {
    sqlx::query("INSERT INTO changes(kind,object_id,target_type,target_id,revision,actor_id,credential_id,occurred_at,payload) VALUES('before',$1,'object',$1,$2,$3,$4,now(),jsonb_build_object('state',$5::jsonb,'attribution',$6::jsonb))").bind(id(o,"id")?).bind(o["revision"].as_i64()).bind(a.id).bind(a.credential).bind(o).bind(attribution::action(a)).execute(&mut **tx).await?;
    Ok(())
}

pub async fn apply(
    State(app): State<App>,
    headers: HeaderMap,
    Json(raw): Json<Value>,
) -> Result<Json<Value>> {
    if raw["contract_version"] != "commons/0.1" {
        return Err(invalid("contract commons/0.1 required"));
    }
    let key = text(&raw, "idempotency_key")?;
    if key.is_empty() || key.len() > 200 {
        return Err(invalid("idempotency key must be 1–200 bytes"));
    }
    let ops = raw["operations"]
        .as_array()
        .filter(|o| !o.is_empty() && o.len() <= 50)
        .ok_or_else(|| invalid("1–50 operations required"))?;
    let mut tx = app.db.begin().await?;
    let mut a = actor(&app, &headers, &mut tx, true).await?;
    attribution::context(&mut tx, &mut a, &raw["on_behalf_of"]).await?;
    let deleting = ops.iter().any(|op| op["op"] == "delete_object");
    conversations::write_gate(&mut tx, deleting).await?;
    if a.role == "reader" || a.mode == "agent" && a.kinds.is_empty() {
        return Err(fail(StatusCode::FORBIDDEN, "write permission required"));
    }
    let hash = attribution::request_hash(&raw, &a);
    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))")
        .bind(format!("write:{}:{key}", a.credential))
        .execute(&mut *tx)
        .await?;
    if let Some(r)=sqlx::query("SELECT request_hash,result FROM request_receipts WHERE namespace='write' AND owner_id=$1 AND request_key=$2").bind(a.credential).bind(key).fetch_optional(&mut *tx).await?{
 if r.get::<String,_>("request_hash")!=hash{return Err(fail(StatusCode::CONFLICT,"same key with different request body"));}return Ok(Json(r.get("result")));}
    // Take the worker lock before any Object row locks, including earlier batch
    // operations. Reconciliation inserts chunks with FK locks on those Objects.
    if deleting {
        sqlx::query("SELECT pg_advisory_xact_lock(8138001)")
            .execute(&mut *tx)
            .await?;
    }
    let mut refs = serde_json::Map::new();
    let mut changes = Vec::new();
    for op in ops {
        let operation = text(op, "op")?;
        let allowed: &[&str] = match operation {
            "create_object" => &[
                "op",
                "local_ref",
                "kind",
                "title",
                "description",
                "body",
                "fields",
            ],
            "ensure_task" => &["op", "local_ref", "title", "description", "body", "fields"],
            "update_object" => &[
                "op",
                "object_id",
                "expected_revision",
                "title",
                "description",
                "body",
                "fields",
            ],
            "delete_object" => &[
                "op",
                "object_id",
                "expected_revision",
                "acknowledge_owned_content_deletion",
            ],
            "save_artifact" => &["op", "object_id", "expected_revision", "artifact"],
            "append_artifact" => &["op", "object_id", "expected_revision", "body"],
            "create_connection" => &[
                "op",
                "from_id",
                "to_id",
                "from_user_id",
                "to_user_id",
                "from_artifact_id",
                "to_artifact_id",
                "from_trace_id",
                "to_trace_id",
                "from_revision",
                "to_revision",
                "kind",
                "explanation",
            ],
            "update_connection" => &[
                "op",
                "connection_id",
                "expected_revision",
                "from_revision",
                "to_revision",
                "explanation",
            ],
            "delete_connection" => &[
                "op",
                "connection_id",
                "expected_revision",
                "from_revision",
                "to_revision",
            ],
            "correct_attribution" => &[
                "op",
                "object_id",
                "expected_revision",
                "target_type",
                "target_id",
                "user_id",
                "on_behalf_of",
                "reason",
                "evidence",
            ],
            "correct_evidence" => &[
                "op",
                "object_id",
                "expected_revision",
                "target_type",
                "target_id",
                "reason",
                "representation",
            ],
            _ => return Err(invalid("Unsupported operation")),
        };
        if op
            .as_object()
            .unwrap()
            .keys()
            .any(|k| !allowed.contains(&k.as_str()))
        {
            return Err(invalid(
                "Unknown operation field; attribution and metadata are server-controlled",
            ));
        }
        for key in ["title", "description", "body"] {
            if op.get(key).is_some_and(|v| !v.is_string()) {
                return Err(invalid("title, description and body must be strings"));
            }
        }
        match operation {
            "create_object" | "ensure_task" => {
                let kind = if op["op"] == "ensure_task" {
                    "task"
                } else {
                    text(op, "kind")?
                };
                a.write(kind)?;
                let title = text(op, "title")?;
                let desc = text(op, "description")?;
                let body = op["body"].as_str().unwrap_or("");
                let f = &op["fields"];
                let local = text(op, "local_ref")?;
                if refs.contains_key(local) {
                    return Err(invalid("duplicate local_ref"));
                }
                if op["op"] == "ensure_task" {
                    let url = issue_url(text(f, "github_issue_url")?)?;
                    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))")
                        .bind(format!("task-issue:{url}"))
                        .execute(&mut *tx)
                        .await?;
                    if let Some(old)=sqlx::query_scalar::<_,Uuid>("SELECT id FROM objects WHERE kind='task' AND lower(fields->>'github_issue_url')=$1 AND COALESCE(provenance->>'historical_only','false')<>'true' AND provenance->>'deleted_at' IS NULL").bind(url).fetch_optional(&mut *tx).await?{refs.insert(local.into(),json!(old));continue;}
                }
                validate(&mut tx, kind, title, desc, body, f, None).await?;
                let oid = Uuid::new_v4();
                sqlx::query("INSERT INTO objects(id,kind,title,description,body,fields,metadata) VALUES($1,$2,$3,$4,$5,$6,jsonb_build_object('created_by',$7::uuid,'updated_by',$7::uuid,'created_at',now(),'updated_at',now()))").bind(oid).bind(kind).bind(title).bind(desc).bind(body).bind(f).bind(a.id).execute(&mut *tx).await?;
                audit(&mut tx, &a, oid, 1, "create_object").await?;
                refs.insert(local.into(), json!(oid));
                changes.push(json!({"id":oid,"revision":1}));
            }
            "update_object" => {
                let oid = id(op, "object_id")?;
                let rev = revision(op, "expected_revision")?;
                let kind = lock_object(&mut tx, &a, oid, rev).await?;
                let old = object(&mut tx, oid, false).await?;
                let title = op["title"].as_str().or(old["title"].as_str()).unwrap();
                let desc = op["description"]
                    .as_str()
                    .or(old["description"].as_str())
                    .unwrap();
                let body = op["body"].as_str().or(old["body"].as_str()).unwrap();
                let fields = if op.get("fields").is_some() {
                    merge_fields(&old["fields"], &op["fields"])?
                } else {
                    old["fields"].clone()
                };
                validate(&mut tx, &kind, title, desc, body, &fields, Some(&old)).await?;
                snapshot_before(&mut tx, &a, &old).await?;
                sqlx::query(
                    "UPDATE objects SET title=$2,description=$3,body=$4,fields=$5 WHERE id=$1",
                )
                .bind(oid)
                .bind(title)
                .bind(desc)
                .bind(body)
                .bind(fields)
                .execute(&mut *tx)
                .await?;
                bump(&mut tx, &a, oid, rev, "update_object").await?;
                changes.push(json!({"id":oid,"revision":rev+1}));
            }
            "delete_object" => {
                changes.push(records::delete(&mut tx, &a, op).await?);
            }
            "save_artifact" | "append_artifact" => {
                let oid = id(op, "object_id")?;
                let rev = revision(op, "expected_revision")?;
                lock_object(&mut tx, &a, oid, rev).await?;
                let input = if op["op"] == "save_artifact" {
                    serde_json::from_value(op["artifact"].clone())
                        .map_err(|_| invalid("invalid Artifact"))?
                } else {
                    evidence::ArtifactInput {
                        body: Some(text(op, "body")?.into()),
                        ..Default::default()
                    }
                };
                let aid = Uuid::new_v4();
                evidence::insert(&mut tx, &a, oid, input, aid, false).await?;
                bump(&mut tx, &a, oid, rev, "save_artifact").await?;
                changes.push(json!({"id":oid,"revision":rev+1,"artifact_id":aid}));
            }
            "create_connection" => {
                changes.extend(create_connection(&mut tx, &a, op).await?);
            }
            "update_connection" | "delete_connection" => {
                let cid = id(op, "connection_id")?;
                let rev = revision(op, "expected_revision")?;
                let old = sqlx::query_scalar::<_, Value>(
                    "SELECT to_jsonb(c) FROM connections c WHERE id=$1 FOR UPDATE",
                )
                .bind(cid)
                .fetch_optional(&mut *tx)
                .await?
                .ok_or_else(|| fail(StatusCode::NOT_FOUND, "Connection not found"))?;
                if old["revision"].as_i64() != Some(rev) {
                    return Err(fail(StatusCode::CONFLICT, "Connection revision conflict"));
                }
                if old["kind"] == "managed_copy" {
                    return Err(invalid(
                        "Registered raw-copy lineage is retained until source deletion",
                    ));
                }
                let mut endpoint_revisions = Vec::new();
                for k in ["from_id", "to_id"] {
                    if let Some(s) = old[k].as_str() {
                        let oid = Uuid::parse_str(s).unwrap();
                        let o = object(&mut tx, oid, true).await?;
                        a.write(o["kind"].as_str().unwrap())?;
                        let current = o["revision"].as_i64().unwrap();
                        let supplied = if k == "from_id" {
                            "from_revision"
                        } else {
                            "to_revision"
                        };
                        if op.get(supplied).is_some() && revision(op, supplied)? != current {
                            return Err(fail(StatusCode::CONFLICT, "Endpoint revision conflict"));
                        }
                        endpoint_revisions.push((oid, current));
                    }
                }
                for prefix in ["from", "to"] {
                    let supplied = format!("{prefix}_revision");
                    for (typ, table) in [("user", "users"), ("trace", "traces")] {
                        if let Some(uid) = old[format!("{prefix}_{typ}_id")]
                            .as_str()
                            .and_then(|s| Uuid::parse_str(s).ok())
                        {
                            if typ == "trace" {
                                a.write("thread")?;
                            }
                            let current = sqlx::query_scalar::<_, i64>(&format!(
                                "SELECT revision FROM {table} WHERE id=$1 FOR SHARE"
                            ))
                            .bind(uid)
                            .fetch_one(&mut *tx)
                            .await?;
                            if op.get(&supplied).is_some() && revision(op, &supplied)? != current {
                                return Err(fail(
                                    StatusCode::CONFLICT,
                                    "Endpoint revision conflict",
                                ));
                            }
                        }
                    }
                    if let Some(aid) = old[format!("{prefix}_artifact_id")]
                        .as_str()
                        .and_then(|s| Uuid::parse_str(s).ok())
                    {
                        if op.get(&supplied).is_some() {
                            return Err(invalid(
                                "Artifact endpoints are immutable and have no revision",
                            ));
                        }
                        let owner = sqlx::query_scalar::<_, Option<Uuid>>(
                            "SELECT object_id FROM artifacts WHERE id=$1 AND deleted_at IS NULL",
                        )
                        .bind(aid)
                        .fetch_optional(&mut *tx)
                        .await?
                        .ok_or_else(|| fail(StatusCode::GONE, "Artifact evidence deleted"))?;
                        if let Some(owner) = owner {
                            let parent = object(&mut tx, owner, false).await?;
                            a.write(parent["kind"].as_str().unwrap())?;
                        } else {
                            a.admin()?;
                        }
                    }
                }
                if old["from_user_id"].is_string() && old["to_user_id"].is_string() {
                    a.admin()?;
                }

                sqlx::query("INSERT INTO changes(kind,target_type,target_id,revision,actor_id,credential_id,occurred_at,payload) VALUES('connection','connection',$1,$2,$3,$4,now(),jsonb_build_object('before_state',$5::jsonb,'action',$6::text,'attribution',$7::jsonb))").bind(cid).bind(rev+1).bind(a.id).bind(a.credential).bind(&old).bind(op["op"].as_str()).bind(attribution::action(&a)).execute(&mut *tx).await?;
                if op["op"] == "delete_connection" {
                    sqlx::query("DELETE FROM connections WHERE id=$1")
                        .bind(cid)
                        .execute(&mut *tx)
                        .await?;
                } else {
                    let exp = text(op, "explanation")?;
                    if exp.trim().is_empty() || exp.len() > 4000 {
                        return Err(invalid("Short explanation required, at most4000 bytes"));
                    }
                    sqlx::query("UPDATE connections SET explanation=$2,revision=revision+1,metadata=metadata||jsonb_build_object('updated_by',$3::uuid,'updated_at',now()) WHERE id=$1").bind(cid).bind(exp).bind(a.id).execute(&mut *tx).await?;
                }
                for (oid, revision) in endpoint_revisions {
                    bump(&mut tx, &a, oid, revision, operation).await?;
                    changes.push(json!({"id":oid,"revision":revision+1}));
                }
                changes.push(json!({"id":cid,"revision":rev+1}));
            }
            "correct_attribution" => {
                changes.push(attribution::correct(&mut tx, &a, op).await?);
            }
            "correct_evidence" => {
                changes.push(records::correct(&mut tx, &a, op).await?);
            }
            _ => {
                return Err(invalid(
                    "Unsupported operation; archive, protection and legacy imports are retired",
                ));
            }
        }
    }
    let dry = raw["validate_only"].as_bool().unwrap_or(false);
    let result = json!({"local_refs":refs,"changes":changes,"validated_only":dry,"saved":!dry});
    if dry {
        tx.rollback().await?;
    } else {
        sqlx::query("INSERT INTO request_receipts(namespace,owner_id,request_key,request_hash,result,credential_id,actor_id) VALUES('write',$1,$2,$3,$4,$1,$5)").bind(a.credential).bind(key).bind(hash).bind(&result).bind(a.id).execute(&mut *tx).await?;
        tx.commit().await?;
    }
    Ok(Json(result))
}
async fn endpoint(
    tx: &mut Tx<'_>,
    a: &Actor,
    op: &Value,
    prefix: &str,
) -> Result<(Uuid, String, Option<i64>)> {
    let mut found = Vec::new();
    for (typ, suffix) in [
        ("object", "id"),
        ("user", "user_id"),
        ("artifact", "artifact_id"),
        ("trace", "trace_id"),
    ] {
        let key = format!("{prefix}_{suffix}");
        if !op[&key].is_null() {
            found.push((id(op, &key)?, typ));
        }
    }
    if found.len() != 1 {
        return Err(invalid("Exactly one typed endpoint required on each side"));
    }
    let (oid, typ) = found[0];
    let table = match typ {
        "object" => "objects",
        "user" => "users",
        "artifact" => "artifacts",
        _ => "traces",
    };
    let row = sqlx::query_scalar::<_, Value>(&format!(
        "SELECT to_jsonb(x) FROM {table} x WHERE id=$1 FOR UPDATE"
    ))
    .bind(oid)
    .fetch_optional(&mut **tx)
    .await?
    .ok_or_else(|| invalid("Endpoint does not exist"))?;
    if typ == "object" {
        a.write(row["kind"].as_str().unwrap())?;
        conversations::active(tx, oid).await?;
    } else if typ == "artifact" {
        if row["deleted_at"].is_string() {
            return Err(fail(StatusCode::GONE, "Artifact evidence deleted"));
        }
        if let Some(owner) = row["object_id"]
            .as_str()
            .and_then(|s| Uuid::parse_str(s).ok())
        {
            let parent = object(tx, owner, false).await?;
            a.write(parent["kind"].as_str().unwrap())?;
        } else {
            a.admin()?;
        }
    } else if typ == "trace" {
        a.write("thread")?;
    }
    let rev = row["revision"].as_i64();
    if let Some(r) = rev
        && revision(op, &format!("{prefix}_revision"))? != r
    {
        return Err(fail(StatusCode::CONFLICT, "Endpoint revision conflict"));
    }
    Ok((oid, typ.into(), rev))
}
async fn create_connection(tx: &mut Tx<'_>, a: &Actor, op: &Value) -> Result<Vec<Value>> {
    let kind = text(op, "kind")?;
    if ![
        "involves",
        "about",
        "related_to",
        "depends_on",
        "derived_from",
        "themed",
    ]
    .contains(&kind)
    {
        return Err(invalid("Unsupported relationship kind"));
    }
    let exp = text(op, "explanation")?;
    if exp.trim().is_empty() || exp.len() > 4000 {
        return Err(invalid(
            "Connection explanation required, at most4000 bytes",
        ));
    }
    let (from, ft, fr) = endpoint(tx, a, op, "from").await?;
    let (to, tt, tr) = endpoint(tx, a, op, "to").await?;
    if from == to {
        return Err(invalid("Distinct endpoints required"));
    }
    if ft == "user" && tt == "user" {
        a.admin()?;
    }
    let col = |p: &str, t: &str| {
        if t == "object" {
            format!("{p}_id")
        } else {
            format!("{p}_{t}_id")
        }
    };
    let cid = Uuid::new_v4();
    sqlx::query(&format!("INSERT INTO connections(id,{}, {},kind,explanation,metadata) VALUES($1,$2,$3,$4,$5,jsonb_build_object('created_by',$6::uuid,'updated_by',$6::uuid,'created_at',now(),'updated_at',now()))",col("from",&ft),col("to",&tt))).bind(cid).bind(from).bind(to).bind(kind).bind(exp).bind(a.id).execute(&mut **tx).await?;
    sqlx::query("UPDATE connections SET metadata=metadata||jsonb_build_object('attribution',$2::jsonb) WHERE id=$1").bind(cid).bind(attribution::action(a)).execute(&mut **tx).await?;
    let mut out = vec![json!({"id":cid,"revision":1,"connection_id":cid})];
    for (oid, typ, rev) in [(from, ft, fr), (to, tt, tr)] {
        if typ == "object" {
            let rev = rev.unwrap();
            bump(tx, a, oid, rev, "create_connection").await?;
            out.push(json!({"id":oid,"revision":rev+1}));
        }
    }
    Ok(out)
}
pub async fn schema_snapshot(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let cols=sqlx::query_scalar::<_,Value>("SELECT jsonb_build_object('table',table_name,'name',column_name,'type',udt_name,'nullable',is_nullable='YES','position',ordinal_position) FROM information_schema.columns WHERE table_schema='public' AND table_name<>'_sqlx_migrations' ORDER BY table_name,ordinal_position").fetch_all(&mut *tx).await?;
    let links=sqlx::query_scalar::<_,Value>("SELECT jsonb_build_object('from_table',tc.table_name,'from_column',kcu.column_name,'to_table',ccu.table_name,'to_column',ccu.column_name) FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name AND tc.constraint_schema=kcu.constraint_schema JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name=tc.constraint_name AND ccu.constraint_schema=tc.constraint_schema WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'").fetch_all(&mut *tx).await?;
    drop(tx);
    let Json(write_contract) = crate::contract(State(app), headers).await?;
    Ok(Json(
        json!({"schema_version":12,"columns":cols,"relationships":links,"object_kinds":KINDS,"write_contract":write_contract}),
    ))
}

fn event_time(value: &Value, precision: &Value) -> Result<Option<(i64, u32)>> {
    if value.is_null() && precision.is_null() {
        return Ok(None);
    }
    let value = value
        .as_str()
        .ok_or_else(|| invalid("Event time must be text"))?;
    let date = match precision.as_str() {
        Some("year") if value.len() == 4 => {
            chrono::NaiveDate::parse_from_str(&format!("{value}-01-01"), "%Y-%m-%d").ok()
        }
        Some("month") if value.len() == 7 => {
            chrono::NaiveDate::parse_from_str(&format!("{value}-01"), "%Y-%m-%d").ok()
        }
        Some("day") if value.len() == 10 => {
            chrono::NaiveDate::parse_from_str(value, "%Y-%m-%d").ok()
        }
        Some("instant") => {
            return chrono::DateTime::parse_from_rfc3339(value)
                .map(|v| Some((v.timestamp(), v.timestamp_subsec_nanos())))
                .map_err(|_| invalid("invalid Event instant"));
        }
        _ => None,
    }
    .ok_or_else(|| invalid("Event value must match year/month/day/instant precision"))?;
    if value.starts_with("0000") || !value.chars().all(|c| c.is_ascii_digit() || c == '-') {
        return Err(invalid("invalid calendar year"));
    }
    Ok(Some((
        date.and_hms_opt(0, 0, 0).unwrap().and_utc().timestamp(),
        0,
    )))
}

fn validate_locator(value: &Value, body: &str, quote: &str) -> Result<()> {
    let map = value
        .as_object()
        .ok_or_else(|| invalid("source_locator must be an object"))?;
    let kind = value["kind"].as_str().unwrap_or("");
    let allowed: &[&str] = match kind {
        "text_offset" => &["kind", "start", "end", "label"],
        "page" => &["kind", "page", "end_page", "label"],
        "timestamp" => &["kind", "start_ms", "end_ms", "label"],
        "section" => &["kind", "label"],
        _ => return Err(invalid("unsupported locator kind")),
    };
    if map.keys().any(|k| !allowed.contains(&k.as_str()))
        || map.get("label").is_some_and(|v| {
            v.as_str()
                .is_none_or(|s| s.trim().is_empty() || s.chars().count() > 500)
        })
    {
        return Err(invalid("invalid locator fields"));
    }
    let number = |key: &str| {
        value[key]
            .as_i64()
            .ok_or_else(|| invalid("locator integer required"))
    };
    match kind {
        "text_offset" => {
            let (start, end) = (number("start")?, number("end")?);
            if start < 0
                || end <= start
                || end as usize > body.chars().count()
                || body
                    .chars()
                    .skip(start as usize)
                    .take((end - start) as usize)
                    .collect::<String>()
                    != quote
            {
                return Err(invalid(
                    "text offsets must select the exact excerpt (Unicode characters)",
                ));
            }
        }
        "page" => {
            let start = number("page")?;
            let end = if map.contains_key("end_page") {
                number("end_page")?
            } else {
                start
            };
            if start < 1 || end < start {
                return Err(invalid("invalid page range"));
            }
        }
        "timestamp" => {
            if number("start_ms")? < 0 || number("end_ms")? <= number("start_ms")? {
                return Err(invalid("invalid timestamp range"));
            }
        }
        "section" => {
            if !map.contains_key("label") {
                return Err(invalid("section label required"));
            }
        }
        _ => unreachable!(),
    }
    if !body.contains(quote) {
        return Err(invalid("excerpt must occur verbatim in original evidence"));
    }
    Ok(())
}
