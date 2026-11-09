//! Explicit document-only sessions; API traffic never authenticates itself.
//! Protected demo requires authenticated ingress; local entry trusts the local host.
use super::*;
use crate::error::Error;
use axum::{extract::Request, middleware::Next};

pub async fn configured_user(
    db: &PgPool,
    setting: &str,
) -> std::result::Result<Option<Uuid>, Box<dyn std::error::Error>> {
    let value = match env::var(setting) {
        Ok(value) if !value.is_empty() => value,
        Ok(_) => return Ok(None),
        Err(env::VarError::NotPresent) => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let id = Uuid::parse_str(&value)?;
    let allowed: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM users WHERE id=$1 AND active AND role='member')",
    )
    .bind(id)
    .fetch_one(db)
    .await?;
    if !allowed {
        return Err(
            format!("{setting} must identify an existing active member, never an admin").into(),
        );
    }
    Ok(Some(id))
}

pub async fn document_session(
    State(app): State<App>,
    mut request: Request,
    next: Next,
) -> Result<Response> {
    let navigation = request.method() == axum::http::Method::GET
        && !request.uri().path().starts_with("/api/")
        && request.uri().path() != "/api"
        && !request.headers().contains_key(header::AUTHORIZATION)
        && request
            .headers()
            .get(header::ACCEPT)
            .and_then(|h| h.to_str().ok())
            .is_some_and(|h| {
                h.split(',')
                    .any(|part| part.trim().split(';').next() == Some("text/html"))
            });
    let headers = request.headers().clone();
    let entry_user = app.protected_demo_user.or(app.local_user);
    if navigation && app.local_user.is_some() {
        // Prevent a nonlocal Host (including DNS rebinding) from receiving a local session.
        // This is an origin check, not trust in forwarded identity headers.
        let expected = app.origin.strip_prefix("http://").unwrap();
        if headers.get(header::HOST).and_then(|h| h.to_str().ok()) != Some(expected) {
            return Err(fail(
                StatusCode::FORBIDDEN,
                "local entry requires the configured loopback host",
            ));
        }
    }
    if navigation && entry_user.is_some() {
        request.headers_mut().remove(header::IF_MODIFIED_SINCE);
        request.headers_mut().remove(header::IF_NONE_MATCH);
    }
    let mut response = next.run(request).await;
    let Some(id) = entry_user.filter(|_| navigation) else {
        return Ok(response);
    };
    if !response.status().is_success()
        || !response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|h| h.to_str().ok())
            .is_some_and(|h| h.starts_with("text/html"))
    {
        return Ok(response);
    }
    // Never cache a document that carries a private session, including conditional reloads.
    response
        .headers_mut()
        .insert(header::CACHE_CONTROL, "private, no-store".parse().unwrap());
    if app.local_user.is_some() {
        response
            .headers_mut()
            .insert(header::X_FRAME_OPTIONS, "DENY".parse().unwrap());
    }
    let mut tx = app.db.begin().await?;
    match actor(&app, &headers, &mut tx, false).await {
        Ok(_) => return Ok(response), // Preserve an explicitly signed-in account.
        Err(Error(StatusCode::UNAUTHORIZED, _)) => {}
        Err(error) => return Err(error),
    }
    let value = secret();
    let label = if app.local_user.is_some() {
        "trusted local"
    } else {
        "protected demo"
    };
    let inserted = sqlx::query("INSERT INTO credentials(id,account_id,secret_hash,mode,label,expires_at) SELECT $1,id,$2,'session',$4,now()+interval '12 hours' FROM users WHERE id=$3 AND active AND role='member'")
        .bind(Uuid::new_v4()).bind(digest(&value)).bind(id).bind(label).execute(&mut *tx).await?;
    if inserted.rows_affected() != 1 {
        return Err(fail(
            StatusCode::FORBIDDEN,
            "configured browser member is unavailable",
        ));
    }
    tx.commit().await?;
    response.headers_mut().insert(
        header::SET_COOKIE,
        session_cookie(&app, &value).parse().unwrap(),
    );
    Ok(response)
}
