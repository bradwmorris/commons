//! External execution records, never indexed as organisational knowledge.
use crate::{App, Result, actor, digest, fail, invalid};
use axum::{
    Json,
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::Row;
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Page {
    #[serde(default)]
    offset: i64,
    #[serde(default)]
    q: String,
}
pub async fn list(
    State(app): State<App>,
    headers: HeaderMap,
    Query(p): Query<Page>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    if p.offset < 0 || p.q.len() > 200 {
        return Err(invalid("invalid pagination"));
    }
    let rows: Vec<Value> = sqlx::query_scalar("SELECT to_jsonb(t) - 'request' - 'configuration' FROM eval_tests t WHERE title ILIKE '%' || $1 || '%' ORDER BY created_at DESC,id LIMIT 51 OFFSET $2")
        .bind(p.q).bind(p.offset).fetch_all(&mut *tx).await?;
    let next = if rows.len() > 50 {
        Some(p.offset + 50)
    } else {
        None
    };
    Ok(Json(
        json!({"tests":rows.into_iter().take(50).collect::<Vec<_>>(),"next_offset":next}),
    ))
}
pub async fn test(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let test: Value = sqlx::query_scalar("SELECT to_jsonb(t) FROM eval_tests t WHERE id=$1")
        .bind(id)
        .fetch_optional(&mut *tx)
        .await?
        .ok_or_else(|| fail(StatusCode::NOT_FOUND, "test not found"))?;
    let versions: Vec<Value> = sqlx::query_scalar(
        "SELECT to_jsonb(v) FROM eval_versions v WHERE test_id=$1 ORDER BY revision DESC",
    )
    .bind(id)
    .fetch_all(&mut *tx)
    .await?;
    let runs: Vec<Value> = sqlx::query_scalar("SELECT jsonb_build_object('id',id,'test_revision',test_revision,'revision',revision,'created_at',created_at) FROM eval_comparisons WHERE test_id=$1 ORDER BY created_at DESC,id").bind(id).fetch_all(&mut *tx).await?;
    Ok(Json(json!({"test":test,"versions":versions,"runs":runs})))
}
pub async fn run(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let run: Value = sqlx::query_scalar("SELECT to_jsonb(r) FROM eval_comparisons r WHERE id=$1")
        .bind(id)
        .fetch_optional(&mut *tx)
        .await?
        .ok_or_else(|| fail(StatusCode::NOT_FOUND, "run not found"))?;
    let attempts: Vec<Value> = sqlx::query_scalar(
        "SELECT to_jsonb(a) FROM eval_attempts a WHERE run_id=$1 ORDER BY sequence",
    )
    .bind(id)
    .fetch_all(&mut *tx)
    .await?;
    let latest = |arm: &str| {
        attempts
            .iter()
            .rev()
            .find(|a| a["arm"] == arm)
            .map(|a| a["payload"]["status"].as_str().unwrap_or("pending"))
            .unwrap_or("pending")
    };
    let (left, right) = (latest("without"), latest("with"));
    let status = if left == "completed" && right == "completed" {
        "completed"
    } else if left == "pending" && right == "pending" {
        "pending"
    } else if left == "failed" && right == "failed" {
        "failed"
    } else {
        "partial"
    };
    Ok(Json(json!({"run":run,"attempts":attempts,"status":status})))
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct File {
    name: String,
    content: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductLink {
    label: String,
    url: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Attempt {
    status: String,
    output: String,
    error: String,
    /// Supplied execution evidence; Commons cannot certify the remote host.
    evidence: String,
    session_id: String,
    isolation: String,
    #[serde(default)]
    files: Vec<File>,
    #[serde(default)]
    links: Vec<ProductLink>,
}
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Operation {
    CreateTest {
        title: String,
        request: String,
        configuration: Value,
    },
    ReviseTest {
        test_id: Uuid,
        expected_revision: i64,
        title: String,
        request: String,
        configuration: Value,
    },
    CreateRun {
        test_id: Uuid,
        test_revision: i64,
        context_bundle: String,
    },
    AppendAttempt {
        run_id: Uuid,
        expected_revision: i64,
        arm: String,
        attempt: Attempt,
    },
    GrantContext {
        run_id: Uuid,
        token: String,
    },
    RevokeContext {
        run_id: Uuid,
    },
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Mutation {
    contract_version: String,
    idempotency_key: String,
    #[serde(default)]
    validate_only: bool,
    operation: Operation,
}
fn bounded(s: &str, max: usize, required: bool) -> Result<()> {
    if s.len() > max || (required && s.trim().is_empty()) {
        Err(invalid("missing or oversized eval field"))
    } else {
        Ok(())
    }
}
pub async fn mutate(
    State(app): State<App>,
    headers: HeaderMap,
    Json(mut raw): Json<Value>,
) -> Result<Json<Value>> {
    let input: Mutation =
        serde_json::from_value(raw.clone()).map_err(|_| invalid("invalid eval request"))?;
    if input.contract_version != "commons.evals/1" {
        return Err(invalid("commons.evals/1 required"));
    }
    bounded(&input.idempotency_key, 200, true)?;
    // Validation and execution share the same logical body/key.
    raw.as_object_mut().unwrap().remove("validate_only");
    let hash = digest(&raw.to_string());
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &headers, &mut tx, true).await?;
    a.write("eval")?;
    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))")
        .bind(format!("eval:{}:{}", a.credential, input.idempotency_key))
        .execute(&mut *tx)
        .await?;
    if let Some(row) = sqlx::query(
        "SELECT request_hash,result FROM eval_receipts WHERE credential_id=$1 AND request_key=$2",
    )
    .bind(a.credential)
    .bind(&input.idempotency_key)
    .fetch_optional(&mut *tx)
    .await?
    {
        if row.get::<String, _>("request_hash") != hash {
            return Err(fail(
                StatusCode::CONFLICT,
                "key already used for different request",
            ));
        }
        return Ok(Json(row.get("result")));
    }
    let revision_target = match &input.operation {
        Operation::ReviseTest {
            test_id,
            expected_revision,
            ..
        } => Some((*test_id, *expected_revision)),
        _ => None,
    };
    let result = match input.operation {
        Operation::CreateTest {
            title,
            request,
            configuration,
        }
        | Operation::ReviseTest {
            test_id: _,
            expected_revision: _,
            title,
            request,
            configuration,
        } => {
            bounded(&title, 200, true)?;
            bounded(&request, 100_000, true)?;
            if !configuration.is_object() || configuration.to_string().len() > 32_000 {
                return Err(invalid("configuration must be a bounded object"));
            }
            let (id, revision) = if let Some((id, rev)) = revision_target {
                let current: Option<i64> =
                    sqlx::query_scalar("SELECT revision FROM eval_tests WHERE id=$1 FOR UPDATE")
                        .bind(id)
                        .fetch_optional(&mut *tx)
                        .await?;
                if current != Some(rev) {
                    return Err(fail(StatusCode::CONFLICT, "test revision conflict"));
                }
                sqlx::query("UPDATE eval_tests SET revision=revision+1,title=$2,request=$3,configuration=$4 WHERE id=$1").bind(id).bind(&title).bind(&request).bind(&configuration).execute(&mut *tx).await?;
                (id, rev + 1)
            } else {
                let id = Uuid::new_v4();
                sqlx::query("INSERT INTO eval_tests(id,title,request,configuration,created_by) VALUES($1,$2,$3,$4,$5)").bind(id).bind(&title).bind(&request).bind(&configuration).bind(a.id).execute(&mut *tx).await?;
                (id, 1)
            };
            let snapshot = json!({"id":id,"revision":revision,"title":title,"request":request,"configuration":configuration});
            sqlx::query(
                "INSERT INTO eval_versions(test_id,revision,snapshot,actor_id) VALUES($1,$2,$3,$4)",
            )
            .bind(id)
            .bind(revision)
            .bind(snapshot)
            .bind(a.id)
            .execute(&mut *tx)
            .await?;
            json!({"id":id,"revision":revision})
        }
        Operation::CreateRun {
            test_id,
            test_revision,
            context_bundle,
        } => {
            bounded(&context_bundle, 200_000, false)?;
            let snapshot: Value = sqlx::query_scalar(
                "SELECT snapshot FROM eval_versions WHERE test_id=$1 AND revision=$2",
            )
            .bind(test_id)
            .bind(test_revision)
            .fetch_optional(&mut *tx)
            .await?
            .ok_or_else(|| fail(StatusCode::NOT_FOUND, "test version not found"))?;
            let id = Uuid::new_v4();
            sqlx::query("INSERT INTO eval_comparisons(id,test_id,test_revision,snapshot,context_bundle,created_by) VALUES($1,$2,$3,$4,$5,$6)").bind(id).bind(test_id).bind(test_revision).bind(snapshot).bind(context_bundle).bind(a.id).execute(&mut *tx).await?;
            json!({"id":id,"revision":1})
        }
        Operation::AppendAttempt {
            run_id,
            expected_revision,
            arm,
            attempt,
        } => {
            if !["without", "with"].contains(&arm.as_str())
                || !["pending", "completed", "failed", "partial"].contains(&attempt.status.as_str())
                || !["verified", "unverified", "unsupported"].contains(&attempt.isolation.as_str())
            {
                return Err(invalid("invalid arm, status or isolation"));
            }
            bounded(&attempt.output, 200_000, attempt.status == "completed")?;
            bounded(&attempt.error, 20_000, attempt.status == "failed")?;
            bounded(&attempt.evidence, 50_000, attempt.isolation == "verified")?;
            bounded(&attempt.session_id, 200, true)?;
            if attempt.files.len() > 10 || attempt.links.len() > 20 {
                return Err(invalid("too many products"));
            }
            for f in &attempt.files {
                bounded(&f.name, 200, true)?;
                bounded(&f.content, 200_000, false)?;
                if f.name.contains(['/', '\\', '\r', '\n', '"']) {
                    return Err(invalid("file name must be a simple name"));
                }
            }
            for link in &attempt.links {
                bounded(&link.label, 200, true)?;
                bounded(&link.url, 2000, true)?;
                let url = url::Url::parse(&link.url).map_err(|_| invalid("invalid product URL"))?;
                if url.scheme() != "https" || !url.username().is_empty() || url.password().is_some()
                {
                    return Err(invalid("product URL must be HTTPS without credentials"));
                }
            }
            let current: Option<i64> =
                sqlx::query_scalar("SELECT revision FROM eval_comparisons WHERE id=$1 FOR UPDATE")
                    .bind(run_id)
                    .fetch_optional(&mut *tx)
                    .await?;
            if current != Some(expected_revision) {
                return Err(fail(StatusCode::CONFLICT, "run revision conflict"));
            }
            let id = Uuid::new_v4();
            sqlx::query("INSERT INTO eval_attempts(id,run_id,sequence,arm,payload,actor_id) VALUES($1,$2,$3,$4,$5,$6)").bind(id).bind(run_id).bind(expected_revision).bind(arm).bind(serde_json::to_value(attempt).unwrap()).bind(a.id).execute(&mut *tx).await?;
            sqlx::query("UPDATE eval_comparisons SET revision=revision+1 WHERE id=$1")
                .bind(run_id)
                .execute(&mut *tx)
                .await?;
            json!({"id":run_id,"revision":expected_revision+1,"attempt_id":id})
        }
        Operation::GrantContext { run_id, token } => {
            if !token.starts_with("cet_") || token.len() < 40 || token.len() > 200 {
                return Err(invalid(
                    "generate a random cet_ token with at least 256 bits of entropy",
                ));
            }
            let exists: bool =
                sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM eval_comparisons WHERE id=$1)")
                    .bind(run_id)
                    .fetch_one(&mut *tx)
                    .await?;
            if !exists {
                return Err(fail(StatusCode::NOT_FOUND, "run not found"));
            }
            sqlx::query("INSERT INTO eval_context_grants(secret_hash,run_id,credential_id) VALUES($1,$2,$3)").bind(digest(&token)).bind(run_id).bind(a.credential).execute(&mut *tx).await?;
            json!({"id":run_id,"context_path":"/api/eval-context","expires_in_seconds":86400})
        }
        Operation::RevokeContext { run_id } => {
            sqlx::query("UPDATE eval_context_grants SET revoked=true WHERE run_id=$1")
                .bind(run_id)
                .execute(&mut *tx)
                .await?;
            json!({"id":run_id,"revoked":true})
        }
    };
    if input.validate_only {
        tx.rollback().await?;
        return Ok(Json(json!({"validated_only":true})));
    }
    sqlx::query("INSERT INTO eval_receipts VALUES($1,$2,$3,$4)")
        .bind(a.credential)
        .bind(input.idempotency_key)
        .bind(hash)
        .bind(&result)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(Json(result))
}
/// A separate capability surface. Never accepts cookies or ordinary agent tokens.
pub async fn context(State(app): State<App>, headers: HeaderMap) -> Result<Response> {
    let token = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .ok_or_else(|| fail(StatusCode::UNAUTHORIZED, "trial credential required"))?;
    let bundle: Option<String>=sqlx::query_scalar("SELECT r.context_bundle FROM eval_context_grants g JOIN eval_comparisons r ON r.id=g.run_id JOIN credentials c ON c.id=g.credential_id JOIN accounts a ON a.id=c.account_id WHERE g.secret_hash=$1 AND NOT g.revoked AND g.expires_at>now() AND NOT c.revoked AND c.expires_at>now() AND a.active").bind(digest(token)).fetch_optional(&app.db).await?;
    Ok(([(header::CACHE_CONTROL, "no-store")], Json(
        json!({"context":bundle.ok_or_else(|| fail(StatusCode::UNAUTHORIZED,"trial credential invalid or expired"))?,"provenance":"coordinator-selected frozen knowledge; not a live retrieval interface"}),
    )).into_response())
}
pub async fn file(
    State(app): State<App>,
    headers: HeaderMap,
    Path((id, index)): Path<(Uuid, usize)>,
) -> Result<Response> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let payload: Option<Value> =
        sqlx::query_scalar("SELECT payload FROM eval_attempts WHERE id=$1")
            .bind(id)
            .fetch_optional(&mut *tx)
            .await?;
    let file = payload
        .as_ref()
        .and_then(|v| v["files"].get(index))
        .ok_or_else(|| fail(StatusCode::NOT_FOUND, "file not found"))?;
    Ok((
        [
            (header::CONTENT_TYPE, "text/plain; charset=utf-8"),
            (header::CONTENT_DISPOSITION, "attachment"),
            (header::CACHE_CONTROL, "no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        file["content"].as_str().unwrap().to_owned(),
    )
        .into_response())
}

/// Discovery is available to ordinary coordinators, never to a trial capability.
pub async fn guide(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    Ok(Json(json!({"contract_version":"commons.evals/1",
        "skill":include_str!("../skills/commons-evals/SKILL.md"),
        "api":include_str!("../docs/evals.md")})))
}
