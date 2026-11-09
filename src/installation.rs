use super::*;

pub static MIGRATIONS: sqlx::migrate::Migrator = sqlx::migrate!();

/// Container secrets and native environment configuration use the same CLI.
/// Refuse ambiguous configuration rather than accidentally using an old credential.
pub fn secret_setting(name: &str) -> std::result::Result<String, Box<dyn std::error::Error>> {
    let direct = env::var(name).ok();
    let file = env::var(format!("{name}_FILE")).ok();
    let value = match (direct, file) {
        (Some(_), Some(_)) => return Err(format!("set only {name} or {name}_FILE").into()),
        (Some(value), None) => value,
        (None, Some(path)) => std::fs::read_to_string(path)
            .map_err(|_| format!("cannot read {name}_FILE"))?
            .trim_end_matches(['\r', '\n'])
            .to_owned(),
        (None, None) => return Err(format!("{name} or {name}_FILE is required").into()),
    };
    if value.is_empty() {
        return Err(format!("{name} must not be empty").into());
    }
    Ok(value)
}

pub async fn schema(db: &PgPool) -> Result<()> {
    let rows =
        sqlx::query("SELECT version,checksum,success FROM _sqlx_migrations ORDER BY version")
            .fetch_all(db)
            .await
            .map_err(|_| {
                fail(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "database schema unavailable; run the explicit migration command",
                )
            })?;
    if rows.len() != MIGRATIONS.iter().count()
        || rows.iter().zip(MIGRATIONS.iter()).any(|(row, migration)| {
            !row.get::<bool, _>("success")
                || row.get::<i64, _>("version") != migration.version
                || row.get::<Vec<u8>, _>("checksum") != migration.checksum.as_ref()
        })
    {
        return Err(fail(
            StatusCode::SERVICE_UNAVAILABLE,
            "database schema does not match this build; use a schema-compatible image",
        ));
    }
    let completed: Option<String> =
        sqlx::query_scalar("SELECT obj_description('objects'::regclass)")
            .fetch_one(db)
            .await?;
    if completed.as_deref() != Some("commons:atomic-packets:complete") {
        return Err(fail(
            StatusCode::SERVICE_UNAVAILABLE,
            "atomic packet conversion incomplete; resume the explicit migration command",
        ));
    }
    Ok(())
}

pub async fn migrate(db: &PgPool) -> std::result::Result<(), Box<dyn std::error::Error>> {
    MIGRATIONS.run(db).await?;
    bound_legacy_packets(db).await?;
    // Bulk migration creates new tables; prepare planner statistics before serving.
    // Explicit migrator command only, never an ordinary agent write.
    sqlx::query("ANALYZE objects, users, artifacts, changes, connections, chunks, traces, trace_items, request_receipts, credentials")
        .execute(db).await?;
    // The standalone lane's default DML grants must not make migration metadata writable.
    // Native development uses an isolated owner and need not provision these roles.
    sqlx::query("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='commons_app') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON _sqlx_migrations FROM commons_app;
        GRANT SELECT ON _sqlx_migrations TO commons_app;
        END IF; END $$").execute(db).await?;
    Ok(())
}

pub async fn health(State(app): State<App>) -> Result<Json<Value>> {
    schema(&app.db).await?;
    Ok(Json(json!({"status":"ok","milestone":"foundation-1",
        "version":env!("CARGO_PKG_VERSION"),"contract_version":"commons/0.1",
        "protected_demo":app.protected_demo_user.is_some(),
        "local_entry":app.local_user.is_some(),
        "branding":{"name":app.installation_name,"theme":app.theme},
        "schema_version":MIGRATIONS.iter().last().map(|m| m.version)})))
}

/// Preserve oversized legacy text once as an Artifact, then enforce the same
/// canonical tokenizer used by writes. This is part of the explicit migrate CLI.
async fn bound_legacy_packets(db: &PgPool) -> std::result::Result<(), Box<dyn std::error::Error>> {
    let mut tx = db.begin().await?;
    let completed: Option<String> =
        sqlx::query_scalar("SELECT obj_description('objects'::regclass)")
            .fetch_one(&mut *tx)
            .await?;
    if completed.as_deref() == Some("commons:atomic-packets:complete") {
        return Ok(());
    }
    let rows =
        sqlx::query_scalar::<_, Value>("SELECT to_jsonb(o) FROM objects o ORDER BY id FOR UPDATE")
            .fetch_all(&mut *tx)
            .await?;
    for o in rows {
        let id = Uuid::parse_str(o["id"].as_str().unwrap())?;
        let kind = o["kind"].as_str().unwrap();
        let old_title = o["title"].as_str().unwrap();
        let title = if old_title.chars().count() > 200
            || old_title.contains(['\n', '\r'])
            || old_title.trim().is_empty()
        {
            format!("Imported {kind} {id}")
        } else {
            old_title.into()
        };
        let mut desc = o["description"].as_str().unwrap_or("").to_owned();
        let mut body = o["body"].as_str().unwrap_or("").to_owned();
        if desc.trim().is_empty() || desc.chars().count() > 600 {
            desc = format!("A {kind} record titled “{title}”.");
        }
        if packet::count(&title, &desc, "").map_err(|e| e.1)? > packet::LIMIT {
            desc = format!("A {kind} record preserved from the earlier Commons database.");
        }
        let mut provenance = o["provenance"].clone();
        let original=sqlx::query_scalar::<_,Uuid>("SELECT id FROM changes WHERE kind IN('migration_original','category_original') AND target_id=$1 ORDER BY occurred_at LIMIT 1").bind(id).fetch_optional(&mut *tx).await?;
        if let Some(map) = provenance.as_object_mut() {
            map.remove("import");
            if let Some(change) = original {
                map.insert("original_change_id".into(), json!(change));
            }
        }
        let mut fields = o["fields"].clone();
        if fields.to_string().len() > 16384 {
            fields = match kind {
                "note" => json!({"intent":"idea","content_format":"markdown"}),
                _ => fields,
            };
        }
        if packet::count(&title, &desc, &body).map_err(|e| e.1)? > packet::LIMIT {
            let aid = Uuid::new_v4();
            let sha = format!("{:x}", Sha256::digest(body.as_bytes()));
            let format = if fields["content_format"] == "plain_text" {
                "text/plain"
            } else {
                "text/markdown"
            };
            sqlx::query("INSERT INTO artifacts(id,object_id,body,kind,title,media_type,sha256,size_bytes,semantic_indexing_enabled,metadata,provenance) VALUES($1,$2,$3,'migration_detail','Original detailed content',$4,$5,$6,$7,jsonb_build_object('migration','atomic-schema-10'),jsonb_build_object('original_change_id',$8::uuid))")
 .bind(aid).bind(id).bind(&body).bind(format).bind(sha).bind(body.len() as i64).bind(kind!="thread"&&fields["intent"]!="excerpt").bind(original).execute(&mut *tx).await?;
            provenance["extended_content_artifact_id"] = json!(aid);
            body = if kind == "task" {
                "The full task brief is preserved in the linked original-content Artifact.".into()
            } else {
                String::new()
            };
        }
        packet::validate(&title, &desc, &body).map_err(|e| e.1)?;
        sqlx::query("UPDATE objects SET title=$2,description=$3,body=$4,fields=$5,provenance=$6 WHERE id=$1").bind(id).bind(title).bind(desc).bind(body).bind(fields).bind(provenance).execute(&mut *tx).await?;
    }
    sqlx::query("COMMENT ON TABLE objects IS 'commons:atomic-packets:complete'")
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(())
}
