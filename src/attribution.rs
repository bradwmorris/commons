//! Stable authenticated Users, optional human context and contribution projections.
//! Model/provider telemetry describes execution; it never supplies User identity.
use super::*;

pub fn action(a: &Actor) -> Value {
    json!({"user_id":a.id,"on_behalf_of":a.on_behalf_of})
}
pub fn request_hash(raw: &Value, a: &Actor) -> String {
    // Preserve receipts made before optional context existed. Context changes are
    // different requests even when it was supplied through a transport header.
    if a.on_behalf_of.is_none() {
        digest(&raw.to_string())
    } else {
        digest(&json!({"request":raw,"attribution":action(a)}).to_string())
    }
}
pub async fn context(tx: &mut atomic::Tx<'_>, a: &mut Actor, value: &Value) -> Result<()> {
    if value.is_null() {
        return Ok(());
    }
    let id = Uuid::parse_str(
        value
            .as_str()
            .ok_or_else(|| invalid("on_behalf_of must reference a human User"))?,
    )
    .map_err(|_| invalid("invalid on_behalf_of User"))?;
    if a.on_behalf_of.is_some_and(|prior| prior != id) {
        return Err(invalid("conflicting on-behalf-of context"));
    }
    if !sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS(SELECT 1 FROM users WHERE id=$1 AND user_kind='human' AND active)",
    )
    .bind(id)
    .fetch_one(&mut **tx)
    .await?
    {
        return Err(invalid("on_behalf_of must reference an active human User"));
    }
    a.on_behalf_of = Some(id);
    Ok(())
}

pub async fn users(tx: &mut atomic::Tx<'_>, id: Uuid) -> Result<Vec<Value>> {
    // Every source here is a saved contribution or its human context. Assignment,
    // consulted edges, searches and reads are deliberately absent. Corrections
    // resolve attribution without rewriting the original immutable action.
    let rows=sqlx::query_scalar::<_,Value>(r#"
WITH actions AS (
 SELECT c.*,COALESCE(x.payload->>'user_id',c.actor_id::text) effective_actor,
 CASE WHEN x.payload->>'on_behalf_of_supplied'='true' THEN x.payload->>'on_behalf_of' ELSE c.payload->'attribution'->>'on_behalf_of' END human
 FROM changes c LEFT JOIN LATERAL (SELECT payload FROM changes x WHERE x.kind='attribution_correction' AND x.target_type='change' AND x.target_id=c.id ORDER BY x.occurred_at DESC,x.id DESC LIMIT 1) x ON true
 WHERE c.object_id=$1 OR c.target_id=$1
), contributions AS (
 SELECT metadata->>'created_by' uid, 'created by' role FROM objects WHERE id=$1
 UNION ALL SELECT metadata->>'on_behalf_of','on behalf of' FROM objects WHERE id=$1
 UNION ALL SELECT c.effective_actor,'contributor' FROM actions c WHERE c.object_id=$1 AND c.kind IN('history','trace','correction')
 UNION ALL SELECT c.human,'on behalf of' FROM actions c WHERE c.object_id=$1 AND c.kind IN('history','trace','correction')
 UNION ALL SELECT created_by::text,'evidence contributor' FROM artifacts WHERE object_id=$1 AND deleted_at IS NULL
 UNION ALL SELECT metadata->'attribution'->>'on_behalf_of','on behalf of' FROM artifacts WHERE object_id=$1 AND deleted_at IS NULL
 UNION ALL SELECT actor_id::text,'created by' FROM traces WHERE id=$1 AND deleted_at IS NULL
 UNION ALL SELECT c.effective_actor,'contributor' FROM actions c WHERE c.target_id=$1 AND c.kind='trace'
 UNION ALL SELECT c.human,'on behalf of' FROM actions c WHERE c.target_id=$1 AND c.kind='trace'
 UNION ALL SELECT i.speaker_id::text,'speaker' FROM trace_items i WHERE i.thread_id=$1
 UNION ALL SELECT speaker_id::text,'speaker' FROM trace_items WHERE id=$1
 UNION ALL SELECT provenance->'attribution'->>'user_id','recorded by' FROM trace_items WHERE id=$1
 UNION ALL SELECT provenance->'attribution'->>'on_behalf_of','on behalf of' FROM trace_items WHERE id=$1
 UNION ALL SELECT created_by::text,'created by' FROM artifacts WHERE id=$1 AND deleted_at IS NULL
 UNION ALL SELECT actor_id::text,'recorded by' FROM changes WHERE id=$1
), grouped AS (SELECT uid,string_agg(DISTINCT role,', ' ORDER BY role) role FROM contributions WHERE uid IS NOT NULL GROUP BY uid)
SELECT jsonb_build_object('user_object_id',u.id,'title',u.title,'user_kind',u.user_kind,'role',g.role,'avatar_asset_url',CASE WHEN u.avatar_image IS NOT NULL THEN '/api/users/'||u.id::text||'/avatar?v='||u.revision::text END)
FROM grouped g JOIN users u ON u.id::text=g.uid ORDER BY CASE WHEN g.role LIKE '%created by%' THEN 0 ELSE 1 END,u.title,u.id
"#).bind(id).fetch_all(&mut **tx).await?;
    Ok(rows)
}

pub async fn correct(tx: &mut atomic::Tx<'_>, a: &Actor, op: &Value) -> Result<Value> {
    a.admin()?;
    let parse = |key: &str| -> Result<Uuid> {
        Uuid::parse_str(
            op[key]
                .as_str()
                .ok_or_else(|| invalid("attribution correction IDs required"))?,
        )
        .map_err(|_| invalid("invalid attribution correction ID"))
    };
    let oid = parse("object_id")?;
    let target = parse("target_id")?;
    let uid = parse("user_id")?;
    let rev = op["expected_revision"]
        .as_i64()
        .ok_or_else(|| invalid("expected_revision required"))?;
    atomic::lock_object(tx, a, oid, rev).await?;
    if !sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS(SELECT 1 FROM users WHERE id=$1 AND user_kind IN('human','agent'))",
    )
    .bind(uid)
    .fetch_one(&mut **tx)
    .await?
    {
        return Err(invalid("real human or agent User required"));
    }
    let reason = op["reason"]
        .as_str()
        .filter(|s| !s.trim().is_empty() && s.len() <= 4000)
        .ok_or_else(|| invalid("bounded correction reason required"))?;
    if !op["evidence"].is_array()
        || op["evidence"].as_array().unwrap().is_empty()
        || op["evidence"].as_array().unwrap().iter().any(|v| {
            v.as_str()
                .is_none_or(|s| s.trim().is_empty() || s.len() > 2000)
        })
        || op["evidence"].to_string().len() > 8192
    {
        return Err(invalid("supporting evidence references required"));
    }
    let typ = op["target_type"].as_str().unwrap_or("");
    let before=match typ {
        "object" if target==oid => {
            let before=atomic::object(tx,oid,false).await?;
            sqlx::query("UPDATE objects SET metadata=metadata||jsonb_build_object('created_by',$2::uuid)||CASE WHEN metadata->>'updated_by'=metadata->>'created_by' THEN jsonb_build_object('updated_by',$2::uuid) ELSE '{}'::jsonb END WHERE id=$1").bind(oid).bind(uid).execute(&mut **tx).await?;
            before
        },
        "capture_owner" if target==oid => {
            let before=atomic::object(tx,oid,false).await?;
            if before["kind"]!="thread" || !before["provenance"]["capture"].is_object() { return Err(invalid("capture owner requires a captured Thread")); }
            if !sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM users WHERE id=$1 AND active AND user_kind IN('agent','human'))").bind(uid).fetch_one(&mut **tx).await? { return Err(invalid("capture owner must be an active User")); }
            sqlx::query("UPDATE objects SET provenance=jsonb_set(provenance,'{capture,owner_id}',to_jsonb($2::uuid)) WHERE id=$1").bind(oid).bind(uid).execute(&mut **tx).await?;
            before
        },
        "change" => sqlx::query_scalar::<_,Value>("SELECT to_jsonb(c) FROM changes c WHERE id=$1 AND object_id=$2 AND kind IN('history','trace','correction')").bind(target).bind(oid).fetch_optional(&mut **tx).await?.ok_or_else(||invalid("change must belong to Object"))?,
        "artifact" => {
            let before=sqlx::query_scalar::<_,Value>("SELECT to_jsonb(e)-'body'-'bytes' FROM artifacts e WHERE id=$1 AND object_id=$2 AND deleted_at IS NULL FOR UPDATE").bind(target).bind(oid).fetch_optional(&mut **tx).await?.ok_or_else(||invalid("Artifact must belong to Object"))?;
            sqlx::query("UPDATE artifacts SET created_by=$2 WHERE id=$1").bind(target).bind(uid).execute(&mut **tx).await?;
            before
        },
        "connection" => {
            let before=sqlx::query_scalar::<_,Value>("SELECT to_jsonb(c) FROM connections c WHERE id=$1 AND ($2=from_id OR $2=to_id) FOR UPDATE").bind(target).bind(oid).fetch_optional(&mut **tx).await?.ok_or_else(||invalid("Connection must involve Object"))?;
            sqlx::query("UPDATE connections SET metadata=metadata||jsonb_build_object('created_by',$2::uuid),revision=revision+1 WHERE id=$1").bind(target).bind(uid).execute(&mut **tx).await?;
            before
        },
        "trace" => {
            let before=sqlx::query_scalar::<_,Value>("SELECT to_jsonb(t) FROM traces t WHERE id=$1 AND thread_id=$2 AND deleted_at IS NULL").bind(target).bind(oid).fetch_optional(&mut **tx).await?.ok_or_else(||invalid("trace must belong to Thread"))?;
            sqlx::query("UPDATE traces SET actor_id=$2,revision=revision+1 WHERE id=$1").bind(target).bind(uid).execute(&mut **tx).await?;
            before
        },
        "trace_item" | "trace_item_recorder" => {
            let before=sqlx::query_scalar::<_,Value>("SELECT to_jsonb(i) FROM trace_items i WHERE id=$1 AND thread_id=$2").bind(target).bind(oid).fetch_optional(&mut **tx).await?.ok_or_else(||invalid("item must belong to Thread"))?;
            if typ=="trace_item_recorder" {
                sqlx::query("UPDATE trace_items SET provenance=jsonb_set(provenance,'{attribution}',COALESCE(provenance->'attribution','{}'::jsonb)||jsonb_build_object('user_id',$2::uuid)) WHERE id=$1").bind(target).bind(uid).execute(&mut **tx).await?;
            } else {
            sqlx::query("UPDATE trace_items SET speaker_id=$2 WHERE id=$1").bind(target).bind(uid).execute(&mut **tx).await?;
            }
            before
        },
        _=>return Err(invalid("unsupported attribution correction target"))
    };
    let mut human = a.clone();
    human.on_behalf_of = None;
    context(tx, &mut human, &op["on_behalf_of"]).await?;
    if typ == "object" && op.get("on_behalf_of").is_some() {
        sqlx::query("UPDATE objects SET metadata=metadata||jsonb_build_object('on_behalf_of',$2::uuid) WHERE id=$1").bind(oid).bind(human.on_behalf_of).execute(&mut **tx).await?;
    }
    if op.get("on_behalf_of").is_some() {
        if typ == "artifact" {
            sqlx::query("UPDATE artifacts SET metadata=metadata||jsonb_build_object('attribution',COALESCE(metadata->'attribution','{}'::jsonb)||jsonb_build_object('user_id',$2::uuid,'on_behalf_of',$3::uuid)) WHERE id=$1").bind(target).bind(uid).bind(human.on_behalf_of).execute(&mut **tx).await?;
        } else if typ == "connection" {
            sqlx::query("UPDATE connections SET metadata=metadata||jsonb_build_object('attribution',COALESCE(metadata->'attribution','{}'::jsonb)||jsonb_build_object('user_id',$2::uuid,'on_behalf_of',$3::uuid)) WHERE id=$1").bind(target).bind(uid).bind(human.on_behalf_of).execute(&mut **tx).await?;
        } else if typ == "trace" {
            sqlx::query("UPDATE traces SET details=details||jsonb_build_object('attribution',COALESCE(details->'attribution','{}'::jsonb)||jsonb_build_object('on_behalf_of',$2::uuid)) WHERE id=$1").bind(target).bind(human.on_behalf_of).execute(&mut **tx).await?;
        } else if typ == "trace_item_recorder" {
            sqlx::query("UPDATE trace_items SET provenance=provenance||jsonb_build_object('attribution',COALESCE(provenance->'attribution','{}'::jsonb)||jsonb_build_object('on_behalf_of',$2::uuid)) WHERE id=$1").bind(target).bind(human.on_behalf_of).execute(&mut **tx).await?;
        }
    }
    let cid = Uuid::new_v4();
    let payload = json!({"reason":reason,"evidence":op["evidence"],"before":before,"user_id":uid,"on_behalf_of":human.on_behalf_of,"attribution":action(a),"on_behalf_of_supplied":op.get("on_behalf_of").is_some()});
    sqlx::query("INSERT INTO changes(id,kind,object_id,target_type,target_id,revision,actor_id,credential_id,occurred_at,payload) VALUES($1,'attribution_correction',$2,$3,$4,$5,$6,$7,now(),$8)").bind(cid).bind(oid).bind(typ).bind(target).bind(rev+1).bind(a.id).bind(a.credential).bind(payload).execute(&mut **tx).await?;
    atomic::bump(tx, a, oid, rev, "correct_attribution").await?;
    Ok(json!({"id":oid,"revision":rev+1,"correction_id":cid}))
}
