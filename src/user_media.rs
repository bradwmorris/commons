//! Installation-owned profile media, served only to authenticated readers.
use super::*;
use axum::body::Bytes;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Upload {
    expected_revision: i64,
    source: String,
}

pub async fn upload(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
    Query(input): Query<Upload>,
    image: Bytes,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    let a = actor(&app, &headers, &mut tx, true).await?;
    a.admin()?;
    // Raster formats only: no SVG/HTML, remote URL fetching or arbitrary files.
    let mime = headers
        .get(header::CONTENT_TYPE)
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    let matches = match mime {
        "image/png" => image.starts_with(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg" => image.starts_with(b"\xff\xd8\xff"),
        "image/webp" => image.starts_with(b"RIFF") && image.get(8..12) == Some(b"WEBP"),
        _ => false,
    };
    if !matches
        || image.len() > 262144
        || input.source.trim().is_empty()
        || input.source.len() > 600
    {
        return Err(invalid(
            "PNG, JPEG or WebP up to 256 KiB and a source/provenance (1–600 bytes) required",
        ));
    }
    let revision: i64 = sqlx::query_scalar("SELECT revision FROM users WHERE id=$1 FOR UPDATE")
        .bind(id)
        .fetch_optional(&mut *tx)
        .await?
        .ok_or_else(|| fail(StatusCode::NOT_FOUND, "User not found"))?;
    if revision != input.expected_revision {
        return Err(fail(
            StatusCode::CONFLICT,
            "revision conflict; reload before uploading",
        ));
    }
    sqlx::query("UPDATE users SET avatar_content_type=$2,avatar_image=$3,revision=revision+1,profile=profile||jsonb_build_object('avatar_source',$4::text),metadata=metadata||jsonb_build_object('updated_by',$5::uuid,'updated_at',now()) WHERE id=$1").bind(id).bind(mime).bind(image.as_ref()).bind(input.source).bind(a.id).execute(&mut *tx).await?;
    let url = format!("/api/users/{id}/avatar?v={}", revision + 1);
    audit(&mut tx, &a, id, revision + 1, "update_avatar").await?;
    tx.commit().await?;
    Ok(Json(
        json!({"id":id,"revision":revision+1,"avatar_asset_url":url}),
    ))
}

pub async fn read(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Response> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let row = sqlx::query("SELECT avatar_content_type AS content_type,avatar_image AS image FROM users WHERE id=$1 AND avatar_image IS NOT NULL")
        .bind(id)
        .fetch_optional(&mut *tx)
        .await?
        .ok_or_else(|| fail(StatusCode::NOT_FOUND, "avatar not found"))?;
    Ok((
        [
            (header::CONTENT_TYPE, row.get::<String, _>("content_type")),
            (header::CACHE_CONTROL, "private, no-store".into()),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff".into()),
            (
                header::CONTENT_SECURITY_POLICY,
                "default-src 'none'; sandbox".into(),
            ),
        ],
        row.get::<Vec<u8>, _>("image"),
    )
        .into_response())
}
