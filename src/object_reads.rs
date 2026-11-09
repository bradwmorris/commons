//! Bounded current reads with deliberate access to original change evidence.
use super::*;
#[derive(Default, Deserialize)]
#[serde(default)]
pub struct ReadOptions {
    view: Option<String>,
    limit: Option<i64>,
    offset: i64,
    expected_revision: Option<i64>,
}
pub async fn read(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
    Query(q): Query<ReadOptions>,
) -> Result<Json<Value>> {
    let l = q.limit.unwrap_or(20);
    if !(1..=200).contains(&l) || q.offset < 0 || q.offset > 0 && q.expected_revision.is_none() {
        return Err(invalid(
            "limit1–200 and nonnegative offset; continuation requires expected_revision",
        ));
    }
    let mut tx = app.db.begin().await?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        .execute(&mut *tx)
        .await?;
    actor(&app, &headers, &mut tx, false).await?;
    conversations::active(&mut tx, id).await?;
    let object = atomic::object(&mut tx, id, false).await?;
    if q.expected_revision
        .is_some_and(|r| object["revision"].as_i64() != Some(r))
    {
        return Err(fail(
            StatusCode::CONFLICT,
            "Object changed; restart read from zero",
        ));
    }
    let artifacts=sqlx::query_scalar::<_,Value>("SELECT jsonb_build_object('id',id,'object_id',object_id,'title',title,'kind',kind,'created_at',created_at,'media_type',media_type,'sha256',sha256,'size_bytes',size_bytes,'capture_outcome',capture_outcome,'capture_reason',capture_reason,'supersedes_artifact_id',supersedes_artifact_id,'body_omitted',body IS NOT NULL,'metadata',jsonb_build_object('filename',metadata->'filename','original_filename',metadata->'original_filename'),'read','/api/artifacts/'||id::text) FROM artifacts WHERE object_id=$1 AND deleted_at IS NULL ORDER BY created_at,id LIMIT $2 OFFSET $3").bind(id).bind(l+1).bind(q.offset).fetch_all(&mut *tx).await?;
    let connections=sqlx::query_scalar::<_,Value>(&format!("SELECT {} FROM connections c WHERE c.from_id=$1 OR c.to_id=$1 ORDER BY c.id LIMIT $2 OFFSET $3",collections::CONNECTION_JSON)).bind(id).bind(l+1).bind(q.offset).fetch_all(&mut *tx).await?;
    let history=sqlx::query_scalar::<_,Value>("SELECT jsonb_build_object('id',id,'target_type',target_type,'target_id',target_id,'action',COALESCE(payload->>'action',kind),'revision',revision,'actor_id',actor_id,'attribution',payload->'attribution','occurred_at',occurred_at,'state_omitted',true,'read','/api/history/'||id::text) FROM changes WHERE object_id=$1 AND kind IN('history','migration_original','attribution_correction') ORDER BY occurred_at,id LIMIT $2 OFFSET $3").bind(id).bind(l+1).bind(q.offset).fetch_all(&mut *tx).await?;
    let corrections=sqlx::query_scalar::<_,Value>("SELECT jsonb_build_object('id',id,'target_type',target_type,'target_id',target_id,'reason',payload->>'reason','object_revision',revision,'actor_id',actor_id,'created_at',occurred_at,'supersedes_correction_id',payload->'supersedes_correction_id','representation_omitted',true) FROM changes WHERE object_id=$1 AND kind='correction' ORDER BY occurred_at,id LIMIT $2 OFFSET $3").bind(id).bind(l+1).bind(q.offset).fetch_all(&mut *tx).await?;
    let mut result = json!({"object":object,"artifacts":artifacts,"connections":connections,"history":history,"corrections":corrections,"audit_events":[],"view":q.view.unwrap_or("compact".into())});
    let mut pages = json!({});
    let mut more = false;
    for key in ["artifacts", "connections", "history", "corrections"] {
        let arr = result[key].as_array_mut().unwrap();
        let m = arr.len() > l as usize;
        arr.truncate(l as usize);
        pages[key] = json!(m.then_some(q.offset + l));
        more |= m;
    }
    result["page"] = json!({"limit":l,"offset":q.offset,"next_offset":more.then_some(q.offset+l),"sections":pages});
    Ok(Json(result))
}
pub async fn history(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>> {
    entry(&app, &headers, id, false).await
}
pub async fn correction(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>> {
    entry(&app, &headers, id, true).await
}
async fn entry(app: &App, headers: &HeaderMap, id: Uuid, correction: bool) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(app, headers, &mut tx, false).await?;
    let row=sqlx::query_scalar::<_,Value>("SELECT payload||jsonb_build_object('id',id,'target_type',target_type,'target_id',target_id,'revision',revision,'actor_id',actor_id,'attribution',payload->'attribution','occurred_at',occurred_at,'created_at',occurred_at,'action',COALESCE(payload->>'action',kind),'after_state',CASE WHEN kind='migration_original' THEN jsonb_build_object('object',payload) ELSE payload->'after_state' END) FROM changes WHERE id=$1").bind(id).fetch_optional(&mut *tx).await?.ok_or_else(||fail(StatusCode::NOT_FOUND,"Change not found"))?;
    Ok(Json(
        json!({if correction{"correction"}else{"history"}:row}),
    ))
}
