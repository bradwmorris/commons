//! Immutable supplied captures and document/image versions, shared with future capture work.
use super::*;
use base64::Engine;

pub const TEXT_LIMIT: usize = 16 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ArtifactInput {
    pub kind: String,
    pub title: Option<String>,
    pub body: Option<String>,
    pub uri: Option<String>,
    pub media_type: Option<String>,
    pub language: Option<String>,
    pub capture_outcome: String,
    pub capture_reason: Option<String>,
    pub expected_size_bytes: Option<i64>,
    pub semantic_indexing_enabled: bool,
    pub metadata: Value,
    pub supersedes_artifact_id: Option<Uuid>,
    pub captured_at: Option<String>,
    pub image_base64: Option<String>,
}
impl Default for ArtifactInput {
    fn default() -> Self {
        Self {
            kind: "other".into(),
            title: None,
            body: None,
            uri: None,
            media_type: Some("text/plain".into()),
            language: None,
            capture_outcome: "complete".into(),
            capture_reason: None,
            expected_size_bytes: None,
            semantic_indexing_enabled: true,
            metadata: json!({}),
            supersedes_artifact_id: None,
            captured_at: None,
            image_base64: None,
        }
    }
}

pub async fn insert(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    a: &Actor,
    object_id: Uuid,
    mut input: ArtifactInput,
    id: Uuid,
    historical: bool,
) -> Result<Uuid> {
    conversations::active(tx, object_id).await?;
    if sqlx::query_scalar::<_, bool>("SELECT kind='thread' OR EXISTS(SELECT 1 FROM connections WHERE kind='managed_copy' AND to_id=$1) FROM objects WHERE id=$1")
        .bind(object_id).fetch_one(&mut **tx).await? {
        input.semantic_indexing_enabled = false;
    }
    if input.kind.trim().is_empty()
        || input.kind.len() > 100
        || input
            .title
            .as_ref()
            .is_some_and(|s| s.is_empty() || s.chars().count() > 500)
        || input
            .uri
            .as_ref()
            .is_some_and(|s| s.is_empty() || s.len() > 2000)
        || input
            .language
            .as_ref()
            .is_some_and(|s| s.is_empty() || s.len() > 35)
        || input
            .media_type
            .as_ref()
            .is_some_and(|s| s.is_empty() || s.len() > 255)
        || !input.metadata.is_object()
        || input.metadata.to_string().len() > 262144
        || input.expected_size_bytes.is_some_and(|s| s <= 0)
        || input.body.as_ref().is_some_and(|s| s.len() > TEXT_LIMIT)
        || ![
            "complete",
            "incomplete",
            "unavailable",
            "paywalled",
            "disallowed",
            "too_large",
            "unsupported",
        ]
        .contains(&input.capture_outcome.as_str())
    {
        return Err(invalid("invalid artifact metadata or text exceeds 16 MiB"));
    }
    if let Some(time) = &input.captured_at {
        chrono::DateTime::parse_from_rfc3339(time)
            .map_err(|_| invalid("captured_at must be RFC3339"))?;
    }
    if input.capture_outcome != "complete"
        && input
            .capture_reason
            .as_ref()
            .is_none_or(|s| s.trim().is_empty() || s.len() > 1000)
        || input.capture_outcome == "complete" && input.capture_reason.is_some()
    {
        return Err(invalid(
            "incomplete captures require a reason; complete captures have no reason",
        ));
    }
    let binary = if let Some(encoded) = &input.image_base64 {
        if input.body.as_ref().is_some_and(|s| !s.is_empty())
            || input.capture_outcome != "complete"
            || input.semantic_indexing_enabled
        {
            return Err(invalid(
                "images require empty text, complete capture and disabled semantic indexing",
            ));
        }
        let encoded = encoded.clone();
        let media_type = input.media_type.clone();
        Some(
            blocking::run(move || {
                let bytes = base64::engine::general_purpose::STANDARD
                    .decode(&encoded)
                    .map_err(|_| invalid("invalid image base64"))?;
                if bytes.is_empty() || bytes.len() > 20 * 1024 * 1024 {
                    return Err(invalid("image must be 1–20 MiB"));
                }
                let format = image::guess_format(&bytes).map_err(|_| invalid("invalid image"))?;
                if !matches!(
                    (media_type.as_deref(), format),
                    (Some("image/png"), image::ImageFormat::Png)
                        | (Some("image/jpeg"), image::ImageFormat::Jpeg)
                ) {
                    return Err(invalid("PNG/JPEG bytes and media type must agree"));
                }
                let mut reader =
                    image::ImageReader::with_format(std::io::Cursor::new(&bytes), format);
                let mut limits = image::Limits::default();
                limits.max_alloc = Some(128 * 1024 * 1024);
                reader.limits(limits);
                let decoded = reader
                    .decode()
                    .map_err(|_| invalid("invalid or oversized image"))?;
                if u64::from(decoded.width()) * u64::from(decoded.height()) > 24_000_000 {
                    return Err(invalid("image exceeds 24 megapixels"));
                }
                Ok((bytes, decoded.width() as i32, decoded.height() as i32))
            })
            .await?,
        )
    } else {
        if input.capture_outcome == "complete"
            && (input
                .media_type
                .as_ref()
                .is_some_and(|s| s.starts_with("image/"))
                || input.body.is_none())
        {
            return Err(invalid(
                "complete text requires body; complete images require original bytes",
            ));
        }
        None
    };
    let mut retained_unknown_media = false;
    if let Some(previous) = input.supersedes_artifact_id {
        let predecessor =
            sqlx::query("SELECT metadata,media_type FROM artifacts WHERE id=$1 AND object_id=$2")
                .bind(previous)
                .bind(object_id)
                .fetch_optional(&mut **tx)
                .await?
                .ok_or_else(|| invalid("predecessor must belong to this Object"))?;
        let metadata: Value = predecessor.get("metadata");
        if metadata["document_key"] != input.metadata["document_key"]
            || !historical && predecessor.get::<Option<String>, _>("media_type") != input.media_type
        {
            return Err(invalid("version must keep document key and media type"));
        }
        retained_unknown_media = input.media_type.is_none();
        if sqlx::query_scalar::<_, bool>(
            "SELECT EXISTS(SELECT 1 FROM artifacts WHERE supersedes_artifact_id=$1)",
        )
        .bind(previous)
        .fetch_one(&mut **tx)
        .await?
        {
            return Err(fail(
                StatusCode::CONFLICT,
                "document already has a newer version",
            ));
        }
    }
    if input.media_type.is_none() && !historical && !retained_unknown_media {
        return Err(invalid(
            "new captures require a media type; only historical imports or their versions may retain unknown media",
        ));
    }
    let bytes = binary.as_ref().map(|b| b.0.as_slice()).unwrap_or(
        input
            .body
            .as_deref()
            .unwrap_or(input.uri.as_deref().unwrap_or(""))
            .as_bytes(),
    );
    let hash = format!("{:x}", Sha256::digest(bytes));
    let size = bytes.len() as i64;
    sqlx::query("INSERT INTO artifacts(id,object_id,body,created_by,kind,title,uri,media_type,language,sha256,size_bytes,capture_outcome,capture_reason,expected_size_bytes,semantic_indexing_enabled,metadata,supersedes_artifact_id,captured_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::text::timestamptz)")
        .bind(id).bind(object_id).bind(input.body).bind(a.id).bind(input.kind).bind(input.title).bind(input.uri).bind(&input.media_type).bind(input.language).bind(hash).bind(size).bind(input.capture_outcome).bind(input.capture_reason).bind(input.expected_size_bytes).bind(input.semantic_indexing_enabled).bind({ let mut metadata=input.metadata; metadata["attribution"]=attribution::action(a); metadata }).bind(input.supersedes_artifact_id).bind(input.captured_at).execute(&mut **tx).await?;
    if let Some((bytes, width, height)) = binary {
        sqlx::query("UPDATE artifacts SET bytes=$2,width=$3,height=$4 WHERE id=$1")
            .bind(id)
            .bind(bytes)
            .bind(width)
            .bind(height)
            .execute(&mut **tx)
            .await?;
    }
    Ok(id)
}

pub async fn read(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Response> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let row = sqlx::query("SELECT to_jsonb(a)-'bytes' AS artifact,object_id,deleted_at IS NOT NULL AS deleted FROM artifacts a WHERE id=$1")
        .bind(id).fetch_optional(&mut *tx).await?.ok_or_else(|| fail(StatusCode::NOT_FOUND,"artifact not found"))?;
    conversations::active(&mut tx, row.get("object_id")).await?;
    if row.get::<bool, _>("deleted") {
        return Err(fail(StatusCode::GONE, "conversation evidence deleted"));
    }
    Ok((
        [(header::CACHE_CONTROL, "private, no-store")],
        Json(json!({"artifact":row.get::<Value, _>("artifact")})),
    )
        .into_response())
}

pub async fn download(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Response> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let row = sqlx::query("SELECT a.object_id,a.deleted_at IS NOT NULL AS deleted,a.body,a.media_type,a.bytes FROM artifacts a WHERE a.id=$1")
        .bind(id).fetch_optional(&mut *tx).await?.ok_or_else(|| fail(StatusCode::NOT_FOUND,"artifact not found"))?;
    conversations::active(&mut tx, row.get("object_id")).await?;
    if row.get::<bool, _>("deleted") {
        return Err(fail(StatusCode::GONE, "conversation evidence deleted"));
    }
    let bytes: Option<Vec<u8>> = row.get("bytes");
    let body: Option<String> = row.get("body");
    if bytes.is_none() && body.is_none() {
        return Err(fail(
            StatusCode::NOT_FOUND,
            "original content is not stored; only its reference is available",
        ));
    }
    let media: Option<String> = row.get("media_type");
    // Never serve untrusted HTML/SVG as active content.
    let content_type = if bytes.is_some() {
        media.as_deref().unwrap()
    } else {
        "text/plain; charset=utf-8"
    };
    Ok((
        [
            (header::CONTENT_TYPE, content_type),
            (header::CACHE_CONTROL, "private, no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        bytes.unwrap_or_else(|| body.unwrap().into_bytes()),
    )
        .into_response())
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TextWindow {
    offset: i32,
    limit: i32,
}

impl Default for TextWindow {
    fn default() -> Self {
        Self {
            offset: 0,
            limit: 24000,
        }
    }
}

/// Unicode-character windows of immutable original text; full-byte download stays separate.
pub async fn text_window(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
    Query(window): Query<TextWindow>,
) -> Result<Response> {
    if window.offset < 0
        || window.offset > TEXT_LIMIT as i32
        || !(1..=48000).contains(&window.limit)
    {
        return Err(invalid(
            "offset must be 0–16777216; limit must be 1–48000 Unicode characters",
        ));
    }
    let mut tx = app.db.begin().await?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        .execute(&mut *tx)
        .await?;
    actor(&app, &headers, &mut tx, false).await?;
    // Slice in PostgreSQL: neither the API nor the client materializes the entire body.
    let row = sqlx::query("SELECT a.object_id,a.deleted_at IS NOT NULL AS deleted,a.sha256,a.size_bytes,a.media_type,char_length(a.body) AS total,substring(a.body FROM $2 FOR $3) AS text FROM artifacts a WHERE a.id=$1")
        .bind(id).bind(window.offset + 1).bind(window.limit)
        .fetch_optional(&mut *tx).await?
        .ok_or_else(|| fail(StatusCode::NOT_FOUND,"artifact not found"))?;
    conversations::active(&mut tx, row.get("object_id")).await?;
    if row.get::<bool, _>("deleted") {
        return Err(fail(StatusCode::GONE, "conversation evidence deleted"));
    }
    let total: Option<i32> = row.get("total");
    if total.is_some_and(|total| window.offset > total) || total.is_none() && window.offset != 0 {
        return Err(invalid(
            "offset exceeds stored text; non-text artifacts require offset zero",
        ));
    }
    let end = window.offset + window.limit;
    Ok(([(header::CACHE_CONTROL, "private, no-store")], Json(json!({
        "artifact_id":id,"text":row.get::<Option<String>, _>("text"),
        "media_type":row.get::<Option<String>, _>("media_type"),
        "sha256":row.get::<String, _>("sha256"),"bytes":row.get::<i64, _>("size_bytes"),
        "offset":window.offset,"limit":window.limit,"total_characters":total,
        "next_offset":total.filter(|total| end < *total).map(|_| end),
        "content_url":format!("/api/artifacts/{id}/content"),
        "note":if total.is_none() { Some("No stored text; inspect metadata or original content in Commons") } else { None }
    }))).into_response())
}
