//! Corrections retain exact originals in changes; ordinary bodies stay atomic.
use super::*;
pub async fn correct(tx: &mut atomic::Tx<'_>, a: &Actor, op: &Value) -> Result<Value> {
    let uid = |k: &str| -> Result<Uuid> {
        Uuid::parse_str(op[k].as_str().ok_or_else(|| invalid("UUID required"))?)
            .map_err(|_| invalid("invalid UUID"))
    };
    let oid = uid("object_id")?;
    let rev = op["expected_revision"]
        .as_i64()
        .ok_or_else(|| invalid("expected_revision required"))?;
    let kind = lock_object(tx, a, oid, rev).await?;
    let target = uid("target_id")?;
    let typ = op["target_type"]
        .as_str()
        .ok_or_else(|| invalid("target_type required"))?;
    let reason = op["reason"]
        .as_str()
        .filter(|s| !s.trim().is_empty() && s.len() <= 4000)
        .ok_or_else(|| invalid("short correction reason required"))?;
    let representation = &op["representation"];
    if !representation.is_object() || representation.to_string().len() > evidence::TEXT_LIMIT {
        return Err(invalid(
            "structured bounded correction representation required",
        ));
    }
    if typ == "object" {
        if target != oid {
            return Err(invalid("Object correction must target this Object"));
        }
        let old = atomic::object(tx, oid, false).await?;
        let title = representation["title"]
            .as_str()
            .or(old["title"].as_str())
            .unwrap();
        let desc = representation["description"]
            .as_str()
            .or(old["description"].as_str())
            .unwrap();
        let body = representation["body"]
            .as_str()
            .or(old["body"].as_str())
            .unwrap();
        atomic::validate(tx, &kind, title, desc, body, &old["fields"], Some(&old)).await?;
        sqlx::query("UPDATE objects SET title=$2,description=$3,body=$4 WHERE id=$1")
            .bind(oid)
            .bind(title)
            .bind(desc)
            .bind(body)
            .execute(&mut **tx)
            .await?;
    } else if typ == "artifact" {
        let owned=sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM artifacts WHERE id=$1 AND object_id=$2 AND deleted_at IS NULL)").bind(target).bind(oid).fetch_one(&mut **tx).await?;
        if !owned {
            return Err(invalid("Artifact must belong to this Object"));
        }
    } else if typ == "message" {
        if kind != "thread" || !sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM trace_items WHERE id=$1 AND thread_id=$2 AND kind IN('message','tool_call','tool_result','log'))").bind(target).bind(oid).fetch_one(&mut **tx).await? {
            return Err(invalid("Visible item must belong to this Thread"));
        }
    } else if !["run", "trace", "event"].contains(&typ) {
        return Err(invalid("Unsupported correction target"));
    }
    let supersedes=sqlx::query_scalar::<_,Uuid>("SELECT id FROM changes WHERE kind='correction' AND target_type=$1 AND target_id=$2 ORDER BY occurred_at DESC,id DESC LIMIT 1").bind(typ).bind(target).fetch_optional(&mut **tx).await?;
    let cid = Uuid::new_v4();
    sqlx::query("INSERT INTO changes(id,kind,object_id,target_type,target_id,revision,actor_id,credential_id,occurred_at,payload) VALUES($1,'correction',$2,$3,$4,$5,$6,$7,now(),$8)").bind(cid).bind(oid).bind(typ).bind(target).bind(rev+1).bind(a.id).bind(a.credential).bind(json!({"reason":reason,"representation":representation,"supersedes_correction_id":supersedes,"attribution":attribution::action(a)})).execute(&mut **tx).await?;
    bump(tx, a, oid, rev, "correct_evidence").await?;
    Ok(json!({"id":oid,"revision":rev+1,"correction_id":cid}))
}

/// Ordinary Object deletion is intentionally separate from managed capture erasure.
/// Foreign-key identities survive; owned content is removed, independent knowledge is not.
pub async fn delete(tx: &mut atomic::Tx<'_>, a: &Actor, op: &Value) -> Result<Value> {
    let oid = op["object_id"]
        .as_str()
        .and_then(|s| Uuid::parse_str(s).ok())
        .ok_or_else(|| invalid("object_id required"))?;
    let rev = op["expected_revision"]
        .as_i64()
        .filter(|r| *r > 0)
        .ok_or_else(|| invalid("positive expected_revision required"))?;
    let kind = lock_object(tx, a, oid, rev).await?;
    if kind == "thread" {
        return Err(invalid(
            "Threads require owner/admin managed deletion through /api/threads/{id}/delete",
        ));
    }
    if op["acknowledge_owned_content_deletion"] != true {
        return Err(invalid("acknowledge_owned_content_deletion must be true"));
    }
    // Registered capture copies must retain their source lifecycle and replay guard.
    if sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS(SELECT 1 FROM connections WHERE kind='managed_copy' AND (to_id=$1 OR to_artifact_id IN(SELECT id FROM artifacts WHERE object_id=$1)))",
    )
    .bind(oid)
    .fetch_one(&mut **tx)
    .await?
    {
        return Err(invalid(
            "Managed copies must be deleted through their owning Thread",
        ));
    }
    let aids = sqlx::query_scalar::<_, Uuid>("SELECT id FROM artifacts WHERE object_id=$1")
        .bind(oid)
        .fetch_all(&mut **tx)
        .await?;
    let cids = sqlx::query_scalar::<_,Uuid>("SELECT id FROM connections WHERE from_id=$1 OR to_id=$1 OR from_artifact_id=ANY($2) OR to_artifact_id=ANY($2)")
        .bind(oid).bind(&aids).fetch_all(&mut **tx).await?;
    // Incident links retain identity but not authored explanations copied from removed evidence.
    sqlx::query("UPDATE connections SET explanation='Relationship to deleted Object.',provenance=jsonb_build_object('deleted_source_id',$1::uuid),revision=revision+1 WHERE id=ANY($2)")
        .bind(oid).bind(&cids).execute(&mut **tx).await?;
    sqlx::query("UPDATE artifacts SET body=NULL,bytes=NULL,metadata='{}',title=NULL,uri=NULL,language=NULL,capture_reason=NULL,provenance='{}',deleted_at=now(),semantic_indexing_enabled=false WHERE object_id=$1")
        .bind(oid).execute(&mut **tx).await?;
    sqlx::query("DELETE FROM chunks WHERE object_id=$1 OR artifact_id=ANY($2)")
        .bind(oid)
        .bind(&aids)
        .execute(&mut **tx)
        .await?;
    let targets: Vec<Uuid> = aids
        .iter()
        .chain(&cids)
        .copied()
        .chain(std::iter::once(oid))
        .collect();
    sqlx::query("UPDATE changes SET payload=jsonb_build_object('deleted_source_id',$1::uuid) WHERE object_id=$1 OR target_id=ANY($2)")
        .bind(oid).bind(&targets).execute(&mut **tx).await?;
    for path in ["before_state", "after_state"] {
        sqlx::query(&format!("UPDATE changes h SET payload=jsonb_set(h.payload,'{{{path},connections}}',(SELECT COALESCE(jsonb_agg(CASE WHEN e.value->>'id'=ANY(SELECT x::text FROM unnest($1::uuid[]) x) THEN jsonb_build_object('id',e.value->'id','deleted_source_id',$2::uuid) ELSE e.value END),'[]'::jsonb) FROM jsonb_array_elements(h.payload->'{path}'->'connections') e)) WHERE jsonb_typeof(h.payload->'{path}'->'connections')='array'"))
            .bind(&cids).bind(oid).execute(&mut **tx).await?;
    }
    sqlx::query("UPDATE objects SET title='Deleted Object',description='Deleted Object; owned content removed.',body='',fields='{}',provenance=jsonb_build_object('deleted_at',now()),metadata=jsonb_build_object('created_by',metadata->'created_by') WHERE id=$1")
        .bind(oid).execute(&mut **tx).await?;
    bump(tx, a, oid, rev, "delete_object").await?;
    Ok(
        json!({"id":oid,"revision":rev+1,"deleted":true,"owned_artifacts":aids.len(),"incident_connections":cids.len()}),
    )
}
