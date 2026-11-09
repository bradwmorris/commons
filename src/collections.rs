//! Bounded public projections. Authentication data never travels with a User row.
use super::*;
pub const USER_JSON: &str = "jsonb_build_object('id',u.id,'title',u.title,'user_kind',u.user_kind,'username',u.username,'role',u.role,'active',u.active,'revision',u.revision,'profile',u.profile,'metadata',u.metadata,'provenance',u.provenance,'connection_count',(SELECT count(*) FROM connections c WHERE c.from_user_id=u.id OR c.to_user_id=u.id),'avatar_asset_url',CASE WHEN u.avatar_image IS NOT NULL THEN '/api/users/'||u.id::text||'/avatar?v='||u.revision::text END)";
pub const CONNECTION_JSON: &str = "to_jsonb(c)||jsonb_build_object('from_id',COALESCE(c.from_id,c.from_user_id,c.from_artifact_id,c.from_trace_id),'to_id',COALESCE(c.to_id,c.to_user_id,c.to_artifact_id,c.to_trace_id),'from_object',endpoint_json(c.from_id,c.from_user_id,c.from_artifact_id,c.from_trace_id),'to_object',endpoint_json(c.to_id,c.to_user_id,c.to_artifact_id,c.to_trace_id))";
#[derive(Default, Deserialize)]
#[serde(default)]
pub struct Search {
    q: String,
    kind: Option<String>,
    sort: Option<String>,
    limit: Option<i64>,
    offset: i64,
    archived: bool,
    object_id: Option<Uuid>,
}
impl Search {
    fn limit(&self) -> Result<i64> {
        let l = self.limit.unwrap_or(50);
        if !(1..=200).contains(&l) || self.offset < 0 || self.q.len() > 2000 {
            return Err(invalid(
                "limit1–200, nonnegative offset and bounded query required",
            ));
        }
        Ok(l)
    }
}
pub async fn list(
    State(app): State<App>,
    headers: HeaderMap,
    Query(q): Query<Search>,
) -> Result<Json<Value>> {
    let l = q.limit()?;
    if q.kind
        .as_ref()
        .is_some_and(|k| !atomic::KINDS.contains(&k.as_str()))
    {
        return Err(invalid("Unsupported Object kind"));
    }
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let filter = "($1='' OR to_tsvector('english',o.title||' '||o.description) @@ plainto_tsquery('english',$1)) AND ($2::text IS NULL OR o.kind=$2) AND (o.kind<>'thread' OR $2='thread') AND COALESCE(o.provenance->>'historical_only','false')<>'true' AND o.provenance->>'deleted_at' IS NULL AND o.provenance->'capture'->>'deleted_at' IS NULL AND NOT $3";
    let count =
        sqlx::query_scalar::<_, i64>(&format!("SELECT count(*) FROM objects o WHERE {filter}"))
            .bind(&q.q)
            .bind(&q.kind)
            .bind(q.archived)
            .fetch_one(&mut *tx)
            .await?;
    let sort = match q.sort.as_deref() {
        Some("connected") => "connection_count DESC,o.id",
        Some("updated") => "o.metadata->>'updated_at' DESC NULLS LAST,o.id",
        _ => "o.metadata->>'created_at' DESC NULLS LAST,o.id",
    };
    let rows=sqlx::query_scalar::<_,Value>(&format!("SELECT to_jsonb(o)||jsonb_build_object('connection_count',(SELECT count(*) FROM connections c WHERE c.from_id=o.id OR c.to_id=o.id)) FROM objects o WHERE {filter} ORDER BY {sort} LIMIT $4 OFFSET $5").replace("ORDER BY connection_count","ORDER BY (SELECT count(*) FROM connections c WHERE c.from_id=o.id OR c.to_id=o.id)"))
 .bind(&q.q).bind(&q.kind).bind(q.archived).bind(l).bind(q.offset).fetch_all(&mut *tx).await?;
    Ok(Json(
        json!({"objects":rows,"total":count,"limit":l,"offset":q.offset,"next_offset":(q.offset+l<count).then_some(q.offset+l)}),
    ))
}
pub async fn users(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let rows = sqlx::query_scalar::<_, Value>(&format!(
        "SELECT {USER_JSON} FROM users u ORDER BY lower(title),id"
    ))
    .fetch_all(&mut *tx)
    .await?;
    Ok(Json(json!({"users":rows})))
}
pub async fn user(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let user =
        sqlx::query_scalar::<_, Value>(&format!("SELECT {USER_JSON} FROM users u WHERE id=$1"))
            .bind(id)
            .fetch_optional(&mut *tx)
            .await?
            .ok_or_else(|| fail(StatusCode::NOT_FOUND, "User not found"))?;
    Ok(Json(json!({"user":user})))
}
pub async fn connection(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>> {
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let row = sqlx::query_scalar::<_, Value>(&format!(
        "SELECT {CONNECTION_JSON} FROM connections c WHERE id=$1"
    ))
    .bind(id)
    .fetch_optional(&mut *tx)
    .await?
    .ok_or_else(|| fail(StatusCode::NOT_FOUND, "Connection not found"))?;
    Ok(Json(json!({"connection":row})))
}
pub async fn connections(
    State(app): State<App>,
    headers: HeaderMap,
    Query(q): Query<Search>,
) -> Result<Json<Value>> {
    let l = q.limit()?;
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let filter = "($1::uuid IS NULL OR $1 IN(c.from_id,c.to_id,c.from_user_id,c.to_user_id,c.from_artifact_id,c.to_artifact_id,c.from_trace_id,c.to_trace_id)) AND ($2='' OR c.explanation ILIKE '%'||$2||'%')";
    let count = sqlx::query_scalar::<_, i64>(&format!(
        "SELECT count(*) FROM connections c WHERE {filter}"
    ))
    .bind(q.object_id)
    .bind(&q.q)
    .fetch_one(&mut *tx)
    .await?;
    let rows=sqlx::query_scalar::<_,Value>(&format!("SELECT {CONNECTION_JSON} FROM connections c WHERE {filter} ORDER BY c.id LIMIT $3 OFFSET $4")).bind(q.object_id).bind(&q.q).bind(l).bind(q.offset).fetch_all(&mut *tx).await?;
    Ok(Json(
        json!({"connections":rows,"total":count,"next_offset":(q.offset+l<count).then_some(q.offset+l)}),
    ))
}
#[derive(Default, Deserialize)]
#[serde(default)]
pub struct Participants {
    object_ids: String,
}
pub async fn participants(
    State(app): State<App>,
    headers: HeaderMap,
    Query(q): Query<Participants>,
) -> Result<Json<Value>> {
    let ids: Vec<Uuid> = q
        .object_ids
        .split(',')
        .filter(|s| !s.is_empty())
        .map(Uuid::parse_str)
        .collect::<std::result::Result<_, _>>()
        .map_err(|_| invalid("invalid Object IDs"))?;
    if ids.len() > 100 {
        return Err(invalid("at most100 Object IDs"));
    }
    let mut tx = app.db.begin().await?;
    actor(&app, &headers, &mut tx, false).await?;
    let mut rows = Vec::new();
    for id in ids {
        for user in attribution::users(&mut tx, id).await? {
            let full = sqlx::query_scalar::<_, Value>(&format!(
                "SELECT {USER_JSON} FROM users u WHERE u.id::text=$1"
            ))
            .bind(user["user_object_id"].as_str().unwrap())
            .fetch_one(&mut *tx)
            .await?;
            rows.push(
                json!({"object_id":id,"direction":"outgoing","user":full,"role":user["role"]}),
            );
        }
    }
    Ok(Json(json!({"participants":rows,"next_offset":null})))
}
