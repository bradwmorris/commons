//! Authentication and scoped authority, shared by HTTP operations.
use crate::{App, Result, blocking, digest, fail, invalid, secret};
use argon2::{
    Argon2, PasswordHash, PasswordHasher, PasswordVerifier,
    password_hash::{SaltString, rand_core::OsRng},
};
use axum::{
    Json,
    extract::State,
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::json;
use sqlx::Row;
use uuid::Uuid;
pub(crate) fn password_hash(password: &str) -> Result<String> {
    if password.len() < 12 || password.len() > 128 {
        return Err(invalid("password must contain 12–128 bytes"));
    }
    Argon2::default()
        .hash_password(password.as_bytes(), &SaltString::generate(&mut OsRng))
        .map(|h| h.to_string())
        .map_err(|_| invalid("password hashing failed"))
}
#[derive(Clone)]
pub(crate) struct Actor {
    pub(crate) id: Uuid,
    pub(crate) on_behalf_of: Option<Uuid>,
    pub(crate) credential: Uuid,
    pub(crate) role: String,
    pub(crate) mode: String,
    pub(crate) kinds: Vec<String>,
}
impl Actor {
    pub(crate) fn admin(&self) -> Result<()> {
        if self.role != "admin" || self.mode != "session" {
            return Err(fail(
                StatusCode::FORBIDDEN,
                "administrator session required",
            ));
        }
        Ok(())
    }
    pub(crate) fn write(&self, kind: &str) -> Result<()> {
        if kind == "user"
            || self.role == "reader"
            || (self.mode == "agent" && !self.kinds.iter().any(|k| k == kind))
        {
            return Err(fail(
                StatusCode::FORBIDDEN,
                "not authorized to change this kind",
            ));
        }
        Ok(())
    }
}
// Credential/account locks are held until commit: revoke/disable waits for in-flight writes.
pub(crate) async fn actor(
    app: &App,
    headers: &HeaderMap,
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    mutation: bool,
) -> Result<Actor> {
    let bearer = headers
        .get(header::AUTHORIZATION)
        .and_then(|h| h.to_str().ok())
        .and_then(|h| h.strip_prefix("Bearer "));
    let cookie = headers
        .get(header::COOKIE)
        .and_then(|h| h.to_str().ok())
        .and_then(|h| {
            h.split(';')
                .find_map(|s| s.trim().strip_prefix("commons_session="))
        });
    let token = bearer
        .or(cookie)
        .ok_or_else(|| fail(StatusCode::UNAUTHORIZED, "login required"))?;
    let row = sqlx::query("SELECT c.id, c.account_id, c.mode, c.label, c.write_kinds, a.role FROM credentials c JOIN users a ON a.id=c.account_id WHERE c.secret_hash=$1 AND NOT c.revoked AND c.expires_at>now() AND a.active FOR SHARE OF c,a")
        .bind(digest(token)).fetch_optional(&mut **tx).await?.ok_or_else(|| fail(StatusCode::UNAUTHORIZED, "credential invalid or expired"))?;
    let mode: String = row.get("mode");
    if (bearer.is_some() && mode != "agent") || (bearer.is_none() && mode != "session") {
        return Err(fail(StatusCode::UNAUTHORIZED, "wrong credential transport"));
    }
    if mode == "session"
        && ((row.get::<String, _>("label") == "protected demo"
            && app.protected_demo_user != Some(row.get("account_id")))
            || (row.get::<String, _>("label") == "trusted local"
                && app.local_user != Some(row.get("account_id")))
            || (["protected demo", "trusted local"]
                .contains(&row.get::<String, _>("label").as_str())
                && row.get::<String, _>("role") != "member"))
    {
        return Err(fail(
            StatusCode::UNAUTHORIZED,
            "automatic browser session is no longer enabled",
        ));
    }
    if mutation
        && bearer.is_none()
        && headers.get(header::ORIGIN).and_then(|h| h.to_str().ok()) != Some(app.origin.as_str())
    {
        return Err(fail(
            StatusCode::FORBIDDEN,
            "browser Origin must match COMMONS_ORIGIN",
        ));
    }
    let mut result = Actor {
        on_behalf_of: None,
        id: row.get("account_id"),
        credential: row.get("id"),
        role: row.get("role"),
        mode,
        kinds: row.get("write_kinds"),
    };
    if let Some(value) = headers.get("x-commons-on-behalf-of") {
        crate::attribution::context(
            tx,
            &mut result,
            &json!(
                value
                    .to_str()
                    .map_err(|_| invalid("invalid on-behalf-of header"))?
            ),
        )
        .await?;
    }
    Ok(result)
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Login {
    username: String,
    password: String,
}
pub(crate) async fn login(
    State(app): State<App>,
    headers: HeaderMap,
    Json(input): Json<Login>,
) -> Result<Response> {
    if headers.get(header::ORIGIN).and_then(|h| h.to_str().ok()) != Some(app.origin.as_str()) {
        return Err(fail(StatusCode::FORBIDDEN, "invalid Origin"));
    }
    let row = sqlx::query("SELECT id,password_hash FROM users WHERE username=$1 AND active AND password_hash IS NOT NULL")
        .bind(&input.username)
        .fetch_optional(&app.db)
        .await?;
    // Argon2 off the async executor; bound JSON size and password length before work.
    if input.password.len() > 128 {
        return Err(fail(StatusCode::UNAUTHORIZED, "invalid login"));
    }
    let stored: Option<String> = row.as_ref().map(|r| r.get("password_hash"));
    let valid = blocking::run(move || {
        static DUMMY: std::sync::OnceLock<String> = std::sync::OnceLock::new();
        let stored = match stored {
            Some(hash) => hash,
            None => match DUMMY.get() {
                Some(hash) => hash.clone(),
                None => {
                    let hash = password_hash("invalid-login-sentinel")?;
                    let _ = DUMMY.set(hash.clone());
                    hash
                }
            },
        };
        Ok(PasswordHash::new(&stored).ok().is_some_and(|h| {
            Argon2::default()
                .verify_password(input.password.as_bytes(), &h)
                .is_ok()
        }))
    })
    .await?;
    if !valid || row.is_none() {
        return Err(fail(StatusCode::UNAUTHORIZED, "invalid login"));
    }
    let id: Uuid = row.unwrap().get("id");
    let value = secret();
    sqlx::query("INSERT INTO credentials(id,account_id,secret_hash,mode,label,expires_at) SELECT $1,id,$2,'session','browser',now()+interval '12 hours' FROM users WHERE id=$3 AND active")
        .bind(Uuid::new_v4()).bind(digest(&value)).bind(id).execute(&app.db).await?;
    Ok((
        [(header::SET_COOKIE, session_cookie(&app, &value))],
        Json(json!({"ok":true})),
    )
        .into_response())
}
pub(crate) fn session_cookie(app: &App, value: &str) -> String {
    format!(
        "commons_session={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200{}",
        if app.secure { "; Secure" } else { "" }
    )
}
