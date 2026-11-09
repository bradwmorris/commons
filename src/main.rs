// Context field/operation conventions adapted from Centaur Context (MIT).
// See THIRD_PARTY_NOTICES.md. Commons authentication and policy are independent.
use axum::{
    Json, Router,
    extract::{DefaultBodyLimit, Path, Query, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{PgPool, Row, postgres::PgPoolOptions};
use std::{collections::HashMap, env};
use uuid::Uuid;

mod appearance;
mod attribution;
mod auth;
mod error;
use auth::{Actor, actor, login, password_hash, session_cookie};
use error::{Result, fail, invalid};

mod atomic;
mod blocking;
mod browser_entry;
mod collections;
mod conversations;
mod evidence;
mod installation;
mod object_reads;
mod packet;
mod records;
mod retrieval;
mod telemetry;
mod user_media;

#[derive(Clone)]
struct App {
    db: PgPool,
    origin: String,
    secure: bool,
    protected_demo_user: Option<Uuid>,
    local_user: Option<Uuid>,
    installation_name: String,
    theme: String,
    appearance_css: String,
    model: Option<retrieval::Model>,
}
fn digest(s: &str) -> String {
    format!("{:x}", Sha256::digest(s.as_bytes()))
}
fn secret() -> String {
    format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple())
}
async fn me(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &headers, &mut tx, false).await?;
    Ok(Json(
        json!({"id":a.id,"role":a.role,"mode":a.mode,"write_kinds":a.kinds}),
    ))
}
async fn contract(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &headers, &mut tx, false).await?;
    Ok(Json(
        json!({"contract_version":"commons/0.1","schema_version":12,"identity":{"user_id":a.id,"credential_id":a.credential,"role":a.role,"write_kinds":a.kinds},
 "writable_kinds":["task","note","entity","source","theme","event"],"object_kinds":["task","note","entity","source","theme","event","thread"],
 "object_fields":atomic::KINDS.iter().map(|kind|((*kind).to_owned(),atomic::field_names(kind))).collect::<std::collections::BTreeMap<_,_>>(),
 "users":"GET /api/users","read":"GET /api/objects/{id}","search":"GET /api/objects","retrieve":"GET /api/retrieve","orientation":"GET /api/orientation",
 "apply":{"method":"POST","path":"/api/apply","required":["contract_version","idempotency_key","operations"],"optional":["validate_only","on_behalf_of"]},
 "attribution":{"human_context":"Optional on_behalf_of active human User UUID in apply/capture, or X-Commons-On-Behalf-Of header. Unspecified is allowed; never inferred from assignment.","participants":"Saved contributions only; original creator retained; reads and consulted edges excluded.","corrections":"Admin session correct_attribution with Object revision, exact target, real User, reason and evidence references; original action retained."},
 "operations":[{"op":"create_object","required":["local_ref","kind","title","description","fields"],"optional":["body"]},{"op":"ensure_task","required":["local_ref","title","description","fields"],"optional":["body"]},{"op":"update_object","required":["object_id","expected_revision"],"optional":["title","description","body","fields"],"fields_mode":"partial merge; null removes an optional key"},{"op":"delete_object","required":["object_id","expected_revision","acknowledge_owned_content_deletion"],"semantics":"Remove ordinary Object content and owned evidence, retain ID tombstone and deletion audit; independent linked Objects survive. Threads use their owner/admin managed deletion endpoint."},{"op":"save_artifact","required":["object_id","expected_revision","artifact"]},{"op":"append_artifact","required":["object_id","expected_revision","body"]},{"op":"create_connection","required":["kind","explanation"],"endpoints":"from_id/to_id for Objects, or from/to_user_id, from/to_artifact_id, from/to_trace_id; exactly one endpoint on each side; expected endpoint revisions required for Objects/Users/Traces"},{"op":"update_connection","required":["connection_id","expected_revision","explanation"]},{"op":"delete_connection","required":["connection_id","expected_revision"]},{"op":"correct_attribution","required":["object_id","expected_revision","target_type","target_id","user_id","reason","evidence"],"optional":["on_behalf_of"]},{"op":"correct_evidence","required":["object_id","expected_revision","target_type","target_id","reason","representation"]}],
 "limits":{"object_tokens":500,"title_characters":200,"description_characters":600,"fields_bytes":16384,"provenance_bytes":8192,"operations":50,"artifact_bytes":16777216},
 "object_rules":{"description":"State explicitly what this record is, what it concerns and its purpose. Supporting detail belongs in body.","embedding":"One packet: title + description + body, including formatting and special tokens. No automatic splitting/truncation.","tokenizer_sha256":packet::TOKENIZER_SHA256},
 "task_required":["status","priority","owner_object_id","due_at","work_kind"],"task_optional":{"body":"Bounded brief; long detail belongs in Artifacts","project":"fields.project"},
 "capture":{"contract_version":"commons.capture/1","submit":"POST /api/capture","write_kind":"thread","list":"GET /api/threads","read":"GET /api/threads/{id}","traces":"GET /api/traces","native_trace_export":"GET /api/traces/{id}/otlp","native_trace_kind":"opentelemetry","readership":"all_authenticated_in_this_installation","default":"off; API access does not enable capture"},
 "connection_kinds":["involves","about","related_to","depends_on","derived_from","themed"],"guidance":"Read current revisions, validate authorized writes, retain key/body for retries, read back changes. Ordinary Users responses never include authentication secrets. Traces are separate from Objects. DSPy is not part of Commons."}),
    ))
}
async fn logout(State(app): State<App>, headers: HeaderMap) -> Result<Response> {
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &headers, &mut tx, true).await?;
    sqlx::query("UPDATE credentials SET revoked=true WHERE id=$1")
        .bind(a.credential)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok((
        [(
            header::SET_COOKIE,
            "commons_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
        )],
        Json(json!({"ok":true})),
    )
        .into_response())
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NewUser {
    username: String,
    title: String,
    password: Option<String>,
    role: String,
    #[serde(default = "human_kind")]
    user_kind: String,
}
fn human_kind() -> String {
    "human".into()
}
async fn insert_user(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    input: NewUser,
    by: Option<Uuid>,
) -> Result<Uuid> {
    if !["admin", "member", "reader"].contains(&input.role.as_str())
        || input.username.is_empty()
        || input.username.len() > 80
        || input.title.trim().is_empty()
        || input.title.chars().count() > 200
        || !["human", "agent"].contains(&input.user_kind.as_str())
        || (input.user_kind == "agent" && (input.password.is_some() || input.role == "admin"))
    {
        return Err(invalid("invalid user"));
    }
    let hash = if input.user_kind == "human" {
        let password = input
            .password
            .clone()
            .ok_or_else(|| invalid("human password required"))?;
        Some(blocking::run(move || password_hash(&password)).await?)
    } else {
        None
    };
    let id = Uuid::new_v4();
    sqlx::query("INSERT INTO users(id,username,password_hash,role,title,user_kind,active,metadata) VALUES($1,$2,$3,$4,$5,$6,true,jsonb_build_object('created_by',$7::uuid,'updated_by',$7::uuid,'created_at',now(),'updated_at',now()))")
        .bind(id)
        .bind(input.username)
        .bind(hash)
        .bind(input.role)
        .bind(input.title)
        .bind(input.user_kind)
        .bind(by.unwrap_or(id))
        .execute(&mut **tx)
        .await?;
    Ok(id)
}
async fn users(
    State(app): State<App>,
    headers: HeaderMap,
    Json(input): Json<NewUser>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &headers, &mut tx, true).await?;
    a.admin()?;
    let id = insert_user(&mut tx, input, Some(a.id)).await?;
    audit(&mut tx, &a, id, 1, "create_user").await?;
    tx.commit().await?;
    Ok(Json(json!({"id":id})))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Token {
    label: String,
    write_kinds: Vec<String>,
    account_id: Option<Uuid>,
}
async fn tokens(
    State(app): State<App>,
    headers: HeaderMap,
    Json(input): Json<Token>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &headers, &mut tx, true).await?;
    if a.mode != "session"
        || input.label.trim().is_empty()
        || input.label.len() > 100
        || input.write_kinds.iter().any(|k| {
            ![
                "task", "note", "entity", "source", "theme", "event", "thread",
            ]
            .contains(&k.as_str())
        })
        || (a.role == "reader" && !input.write_kinds.is_empty())
    {
        return Err(fail(StatusCode::FORBIDDEN, "invalid token scope"));
    }
    let account_id = input.account_id.unwrap_or(a.id);
    if account_id != a.id {
        a.admin()?;
        let target = sqlx::query("SELECT a.role FROM users a WHERE a.id=$1 AND a.active AND a.user_kind='agent' FOR SHARE OF a")
            .bind(account_id).fetch_optional(&mut *tx).await?
            .ok_or_else(|| fail(StatusCode::FORBIDDEN, "only active agent accounts can receive delegated credentials"))?;
        if target.get::<String, _>("role") == "reader" && !input.write_kinds.is_empty() {
            return Err(fail(
                StatusCode::FORBIDDEN,
                "reader agent cannot receive write scopes",
            ));
        }
    }
    let id = Uuid::new_v4();
    let value = secret();
    sqlx::query("INSERT INTO credentials(id,account_id,secret_hash,mode,label,write_kinds,expires_at) VALUES($1,$2,$3,'agent',$4,$5,now()+interval '30 days')").bind(id).bind(account_id).bind(digest(&value)).bind(input.label).bind(input.write_kinds).execute(&mut *tx).await?;
    sqlx::query("INSERT INTO changes(kind,target_type,target_id,actor_id,credential_id,occurred_at,payload) VALUES('credential','credential',$1,$2,$3,now(),$4)").bind(id).bind(a.id).bind(a.credential).bind(json!({"action":"issue_token","account_id":account_id,"attribution":attribution::action(&a)})).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(Json(
        json!({"id":id,"account_id":account_id,"token":value,"expires_in_days":30}),
    ))
}
async fn token_list(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &headers, &mut tx, false).await?;
    let rows=sqlx::query("SELECT id,account_id,label,write_kinds,revoked,expires_at::text FROM credentials WHERE (account_id=$1 OR $2) AND mode='agent' ORDER BY expires_at DESC").bind(a.id).bind(a.mode == "session" && a.role == "admin").fetch_all(&mut *tx).await?;
    Ok(Json(json!(rows.iter().map(|r| json!({"id":r.get::<Uuid,_>("id"),"account_id":r.get::<Uuid,_>("account_id"),"label":r.get::<String,_>("label"),"write_kinds":r.get::<Vec<String>,_>("write_kinds"),"revoked":r.get::<bool,_>("revoked"),"expires_at":r.get::<String,_>("expires_at")})).collect::<Vec<_>>())))
}
async fn revoke(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &headers, &mut tx, true).await?;
    if a.mode != "session" {
        return Err(fail(StatusCode::FORBIDDEN, "session required"));
    }
    let count = sqlx::query(
        "UPDATE credentials SET revoked=true WHERE id=$1 AND (account_id=$2 OR $3) AND mode='agent'",
    )
    .bind(id)
    .bind(a.id)
    .bind(a.role == "admin")
    .execute(&mut *tx)
    .await?
    .rows_affected();
    if count > 0 {
        sqlx::query("INSERT INTO changes(kind,target_type,target_id,actor_id,credential_id,occurred_at,payload) VALUES('credential','credential',$1,$2,$3,now(),$4)").bind(id).bind(a.id).bind(a.credential).bind(json!({"action":"revoke_token","attribution":attribution::action(&a)})).execute(&mut *tx).await?;
    }
    tx.commit().await?;
    if count == 0 {
        return Err(fail(StatusCode::NOT_FOUND, "token not found"));
    }
    Ok(Json(json!({"ok":true})))
}
use atomic::*;

#[tokio::main]
async fn main() -> std::result::Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if matches!(
        args.get(1).map(String::as_str),
        Some("version" | "--version")
    ) {
        println!("commons {} (commons/0.1)", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }
    let db = PgPoolOptions::new()
        .max_connections(10)
        .acquire_timeout(std::time::Duration::from_secs(5))
        .connect(&installation::secret_setting("DATABASE_URL")?)
        .await?;
    match args.get(1).map(String::as_str) {
        Some("migrate") => {
            installation::migrate(&db).await?;
            println!("Migrations applied");
            return Ok(());
        }
        Some("diagnose-retrieval") => {
            if args.len() != 2 {
                return Err("usage: commons diagnose-retrieval (no arguments)".into());
            }
            installation::schema(&db).await.map_err(|e| e.1)?;
            println!("{}", retrieval::diagnose(&db).await.map_err(|e| e.1)?);
            return Ok(());
        }
        Some("bootstrap") => {
            installation::schema(&db).await.map_err(|e| e.1)?;
            let mut tx = db.begin().await?;
            sqlx::query("SELECT pg_advisory_xact_lock(91371511)")
                .execute(&mut *tx)
                .await?;
            let count: i64 = sqlx::query_scalar("SELECT count(*) FROM users")
                .fetch_one(&mut *tx)
                .await?;
            if count != 0 {
                return Err("bootstrap refused: accounts already exist".into());
            }
            let id = insert_user(
                &mut tx,
                NewUser {
                    username: env::var("COMMONS_ADMIN_USER")?,
                    title: env::var("COMMONS_ADMIN_NAME")?,
                    password: Some(installation::secret_setting("COMMONS_ADMIN_PASSWORD")?),
                    role: "admin".into(),
                    user_kind: human_kind(),
                },
                None,
            )
            .await
            .map_err(|e| e.1)?;
            tx.commit().await?;
            println!("Administrator created: {id}");
            return Ok(());
        }
        None | Some("serve") => {}
        _ => {
            return Err(
                "usage: commons [serve|migrate|bootstrap|version|diagnose-retrieval]".into(),
            );
        }
    }
    installation::schema(&db).await.map_err(|e| e.1)?;
    let configured = url::Url::parse(&env::var("COMMONS_ORIGIN")?)?;
    if !configured.username().is_empty()
        || configured.password().is_some()
        || configured.path() != "/"
        || configured.query().is_some()
        || configured.fragment().is_some()
        || !(configured.scheme() == "https"
            || (configured.scheme() == "http"
                && matches!(configured.host_str(), Some("localhost" | "127.0.0.1"))))
    {
        return Err("COMMONS_ORIGIN must be an HTTPS origin (HTTP loopback allowed for development), without credentials/path/query/fragment".into());
    }
    let origin = configured.origin().ascii_serialization();
    let protected_demo_user =
        browser_entry::configured_user(&db, "COMMONS_PROTECTED_DEMO_USER").await?;
    let local_user = browser_entry::configured_user(&db, "COMMONS_LOCAL_USER").await?;
    if local_user.is_some()
        && (protected_demo_user.is_some()
            || configured.scheme() != "http"
            || !matches!(configured.host_str(), Some("localhost" | "127.0.0.1")))
    {
        return Err("COMMONS_LOCAL_USER requires an HTTP loopback origin and cannot be combined with protected demo".into());
    }
    let installation_name = env::var("COMMONS_INSTALLATION_NAME")
        .unwrap_or_else(|_| "Commons".into())
        .trim()
        .to_owned();
    if installation_name.is_empty()
        || installation_name.chars().count() > 64
        || installation_name.chars().any(char::is_control)
    {
        return Err(
            "COMMONS_INSTALLATION_NAME must contain 1–64 characters without control characters"
                .into(),
        );
    }
    let theme = env::var("COMMONS_THEME").unwrap_or_else(|_| "charcoal".into());
    if !matches!(theme.as_str(), "charcoal" | "blue-slate") {
        return Err("COMMONS_THEME must be charcoal or blue-slate".into());
    }
    let appearance_css = match env::var("COMMONS_APPEARANCE") {
        Ok(raw) if !raw.trim().is_empty() => {
            let parsed = serde_json::from_str::<std::collections::BTreeMap<String, String>>(&raw);
            match parsed
                .ok()
                .and_then(|tokens| appearance::stylesheet(&tokens).ok())
            {
                Some(css) => css,
                None => {
                    eprintln!("Invalid COMMONS_APPEARANCE; using configured theme preset");
                    String::new()
                }
            }
        }
        _ => String::new(),
    };
    let app = App {
        db,
        secure: origin.starts_with("https://"),
        origin,
        protected_demo_user,
        local_user,
        installation_name,
        theme,
        appearance_css,
        model: retrieval::Model::configured()?,
    };
    retrieval::start(app.clone());
    let router = Router::new()
        .route(
            "/api/appearance.css",
            get(|State(app): State<App>| async move {
                (
                    [
                        (header::CONTENT_TYPE, "text/css; charset=utf-8"),
                        (header::CACHE_CONTROL, "no-store"),
                    ],
                    app.appearance_css,
                )
            }),
        )
        .route("/api/health", get(installation::health))
        .route("/api/login", post(login))
        .route("/api/logout", post(logout))
        .route("/api/me", get(me))
        .route("/api/contract", get(contract))
        .route("/api/users", get(collections::users).post(users))
        .route("/api/participants", get(collections::participants))
        .route(
            "/api/users/{id}/avatar",
            get(user_media::read).post(user_media::upload),
        )
        .route("/api/tasks/by-issue", get(task_lookup))
        .route("/api/tokens", get(token_list).post(tokens))
        .route("/api/tokens/{id}/revoke", post(revoke))
        .route("/api/schema", get(atomic::schema_snapshot))
        .route("/api/users/{id}", get(collections::user))
        .route("/api/threads", get(conversations::list_chats))
        .route("/api/threads/{id}", get(conversations::read_chat))
        .route(
            "/api/threads/{id}/relationships",
            get(conversations::chat_relationships),
        )
        .route("/api/threads/{id}/text", get(retrieval::thread_text))
        .route("/api/threads/{id}/delete", post(conversations::delete_chat))
        .route("/api/traces", get(conversations::list_runs))
        .route("/api/traces/{id}", get(conversations::read_run))
        .route("/api/traces/{id}/otlp", get(telemetry::download))
        .route(
            "/api/traces/{id}/relationships",
            get(conversations::run_relationships),
        )
        .route("/api/traces/{id}/history", get(conversations::run_history))
        .route("/api/objects", get(collections::list))
        .route("/api/objects/{id}", get(object_reads::read))
        .route("/api/history/{id}", get(object_reads::history))
        .route("/api/corrections/{id}", get(object_reads::correction))
        .route("/api/artifacts/{id}", get(evidence::read))
        .route("/api/artifacts/{id}/content", get(evidence::download))
        .route("/api/artifacts/{id}/text", get(evidence::text_window))
        .route("/api/capture", post(conversations::submit))
        .route("/api/chats", get(conversations::list_chats))
        .route("/api/chats/{id}", get(conversations::read_chat))
        .route(
            "/api/chats/{id}/relationships",
            get(conversations::chat_relationships),
        )
        .route("/api/chats/{id}/delete", post(conversations::delete_chat))
        .route("/api/runs", get(conversations::list_runs))
        .route("/api/runs/{id}", get(conversations::read_run))
        .route(
            "/api/runs/{id}/relationships",
            get(conversations::run_relationships),
        )
        .route("/api/runs/{id}/history", get(conversations::run_history))
        .route("/api/connections", get(collections::connections))
        .route("/api/connections/{id}", get(collections::connection))
        .route("/api/retrieve", get(retrieval::retrieve))
        .route("/api/orientation", get(retrieval::orientation))
        .route("/api/retrieval/status", get(retrieval::status))
        .route("/api/retrieval/rebuild", post(retrieval::rebuild))
        .route("/api/apply", post(apply))
        .route(
            "/api/{*path}",
            get(|| async {
                (
                    StatusCode::NOT_FOUND,
                    Json(json!({"error":"unknown API route"})),
                )
            }),
        )
        .fallback_service(
            tower_http::services::ServeDir::new("web/dist")
                .fallback(tower_http::services::ServeFile::new("web/dist/index.html")),
        )
        .layer(DefaultBodyLimit::max(32 * 1024 * 1024))
        .layer(axum::middleware::from_fn_with_state(
            app.clone(),
            browser_entry::document_session,
        ))
        .with_state(app);
    let port = env::var("PORT").unwrap_or("3000".into());
    // Demo session bootstrap is reachable only through a trusted local ingress.
    // The operator must protect that ingress (Amp's private portal in this Orb).
    let bind = if protected_demo_user.is_some() {
        "127.0.0.1".to_owned()
    } else if local_user.is_some() {
        // Native local entry defaults to loopback. Compose explicitly listens on its
        // private bridge and publishes only host loopback; never publish it publicly.
        env::var("COMMONS_BIND").unwrap_or_else(|_| "127.0.0.1".to_owned())
    } else {
        "0.0.0.0".to_owned()
    };
    let listener = tokio::net::TcpListener::bind(format!("{bind}:{port}")).await?;
    println!("Commons foundation listening on port {port}");
    axum::serve(listener, router).await?;
    Ok(())
}
