//! Privileged destination staging, not a source-store reader or migration runner.
use super::*;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImportedObject {
    pub id: Uuid,
    pub kind: String,
    pub title: String,
    pub description: String,
    pub fields: Value,
    pub revision: i64,
    pub created_by: Option<Uuid>,
    pub updated_by: Option<Uuid>,
    pub created_at: String,
    pub updated_at: String,
    pub archived_at: Option<String>,
    pub protected: bool,
    pub provenance: Value,
    pub authorship: Value,
    pub owner_mapping: Option<OwnerMapping>,
}
#[derive(Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct OwnerMapping {
    source_owner_id: Option<Uuid>,
    destination_owner_id: Uuid,
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Record {
    Object {
        object: Box<ImportedObject>,
    },
    Chat {
        chat: conversations::ImportedChat,
    },
    Message {
        message: conversations::ImportedMessage,
    },
    Run {
        run: conversations::ImportedRun,
    },
    RoutineResult {
        original: conversations::RoutineResult,
    },
    Category {
        category: records::CategoryInput,
        revision: i64,
        created_by: Option<Uuid>,
        updated_by: Option<Uuid>,
        created_at: String,
        updated_at: String,
        archived_at: Option<String>,
        provenance: Value,
    },
    Correction {
        id: Uuid,
        object_id: Uuid,
        target_type: String,
        target_id: Uuid,
        reason: String,
        representation: Value,
        supersedes_correction_id: Option<Uuid>,
        actor_id: Option<Uuid>,
        object_revision: i64,
        created_at: String,
        provenance: Value,
    },
    Artifact {
        id: Uuid,
        object_id: Uuid,
        created_by: Option<Uuid>,
        created_at: String,
        provenance: Value,
        sha256: String,
        artifact: Box<evidence::ArtifactInput>,
    },
    Connection {
        id: Uuid,
        from_id: Uuid,
        to_id: Uuid,
        kind: String,
        explanation: String,
        revision: i64,
        created_by: Option<Uuid>,
        created_at: String,
        updated_at: String,
        archived_at: Option<String>,
        protected: bool,
        provenance: Value,
    },
    History {
        id: Uuid,
        object_id: Option<Uuid>,
        run_id: Option<Uuid>,
        target_type: String,
        target_id: Uuid,
        action: String,
        revision: i64,
        actor_id: Option<Uuid>,
        occurred_at: String,
        before_state: Value,
        after_state: Value,
        provenance: Value,
    },
}
fn timestamp(value: &str) -> Result<()> {
    chrono::DateTime::parse_from_rfc3339(value)
        .map_err(|_| invalid("import timestamp must be RFC3339"))?;
    Ok(())
}
pub async fn apply(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    a: &Actor,
    store: &str,
    raw: Value,
) -> Result<Value> {
    a.admin()?;
    if store.trim().is_empty() || store.len() > 200 {
        return Err(invalid("source_store required, up to 200 bytes"));
    }
    let record: Record = serde_json::from_value(raw.clone())
        .map_err(|e| invalid(&format!("unsupported import record: {e}")))?;
    let (kind, id) = match &record {
        Record::Object { object } => ("object", object.id),
        Record::Chat { chat } => ("chat", chat.id),
        Record::Message { message } => ("message", message.id()),
        Record::Run { run } => ("run", run.run.id),
        Record::RoutineResult { original } => ("routine_result", original.id),
        Record::Artifact { id, .. } => ("artifact", *id),
        Record::Connection { id, .. } => ("connection", *id),
        Record::History { id, .. } => ("history", *id),
        Record::Correction { id, .. } => ("correction", *id),
        Record::Category { category, .. } => ("category", category.id),
    };
    let hash = digest(&raw.to_string());
    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))")
        .bind(format!("import:{store}:{kind}:{id}"))
        .execute(&mut **tx)
        .await?;
    // Check retained ownership and deletion before the replay registry. Its hash
    // proves request identity, not that removed content may be restored.
    let owners: Vec<Uuid> = sqlx::query_scalar("SELECT id FROM objects WHERE id=$1 UNION SELECT object_id FROM artifacts WHERE id=$1 UNION SELECT chat_object_id FROM chat_messages WHERE id=$1 UNION SELECT from_id FROM connections WHERE id=$1 UNION SELECT to_id FROM connections WHERE id=$1 UNION SELECT object_id FROM record_history WHERE id=$1 AND object_id IS NOT NULL UNION SELECT object_id FROM evidence_corrections WHERE id=$1 UNION SELECT chat_object_id FROM runs WHERE id=$1 AND chat_object_id IS NOT NULL")
        .bind(id).fetch_all(&mut **tx).await?;
    for owner in owners {
        conversations::active(tx, owner).await?;
    }
    let removed: bool = sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM runs WHERE id=$1 AND deleted_at IS NOT NULL) OR EXISTS(SELECT 1 FROM record_history WHERE id=$1 AND after_state->>'source_deleted'='true') OR EXISTS(SELECT 1 FROM evidence_corrections WHERE id=$1 AND representation->>'source_deleted'='true') OR EXISTS(SELECT 1 FROM artifacts WHERE id=$1 AND deleted_at IS NOT NULL)")
        .bind(id).fetch_one(&mut **tx).await?;
    if removed {
        return Err(fail(StatusCode::GONE, "import target was deleted"));
    }
    if let Some(previous) = sqlx::query_scalar::<_,String>("SELECT request_hash FROM import_items WHERE source_store=$1 AND record_type=$2 AND source_id=$3").bind(store).bind(kind).bind(id).fetch_optional(&mut **tx).await? {
        if previous!=hash { return Err(fail(StatusCode::CONFLICT,"import identity already staged with different content")); }
        return Ok(json!({"id":id,"imported":false}));
    }
    let provenance = json!({"source_store":store,"source_id":id,"source_record_type":kind,"importer_id":a.id,"authorship":"caller_attested_historical"});
    let parent;
    match record {
        Record::Chat { chat } => {
            parent = Some(chat.id);
            conversations::import_chat(tx, a, chat, provenance).await?;
        }
        Record::Message { message } => {
            parent = Some(message.chat_id);
            conversations::import_message(tx, a, message, provenance).await?;
        }
        Record::Run { run } => {
            parent = run.chat_object_id.or(run.run.primary_object_id);
            conversations::import_run(tx, a, run, provenance).await?;
        }
        Record::RoutineResult { original } => {
            parent = Some(original.task_id);
            conversations::import_routine_result(tx, original, raw["original"].clone(), provenance)
                .await?;
        }
        Record::Category {
            category,
            revision,
            created_by,
            updated_by,
            created_at,
            updated_at,
            archived_at,
            provenance: original,
        } => {
            if category.expected_revision != 0 || revision < 1 {
                return Err(invalid("category import creates a new identity"));
            }
            timestamp(&created_at)?;
            timestamp(&updated_at)?;
            if let Some(v) = &archived_at {
                timestamp(v)?;
            }
            records::save_category_in(tx, a, category).await?;
            sqlx::query("UPDATE entity_categories SET revision=$2,created_by=$3,updated_by=$4,created_at=$5::text::timestamptz,updated_at=$6::text::timestamptz,archived_at=$7::text::timestamptz,import_provenance=$8 WHERE id=$1")
                .bind(id).bind(revision).bind(created_by).bind(updated_by).bind(created_at).bind(updated_at).bind(archived_at).bind(json!({"import":provenance,"original":original})).execute(&mut **tx).await?;
            sqlx::query("UPDATE record_history h SET action='import_category',revision=c.revision,after_state=to_jsonb(c) FROM entity_categories c WHERE h.target_type='category' AND h.target_id=c.id AND c.id=$1").bind(id).execute(&mut **tx).await?;
            parent = None;
        }
        Record::Correction {
            id,
            object_id,
            target_type,
            target_id,
            reason,
            representation,
            supersedes_correction_id,
            actor_id,
            object_revision,
            created_at,
            provenance: original,
        } => {
            supported_parent(tx, object_id).await?;
            timestamp(&created_at)?;
            let valid =
                records::correction_target(tx, object_id, &target_type, target_id, true).await?;
            if !valid
                || object_revision < 1
                || reason.trim().is_empty()
                || !representation.is_object()
                || representation.to_string().len() > evidence::TEXT_LIMIT
            {
                return Err(invalid("unsupported correction target or representation"));
            }
            if let Some(previous) = supersedes_correction_id
                && !sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM evidence_corrections WHERE id=$1 AND object_id=$2 AND target_type=$3 AND target_id=$4 AND object_revision<$5)").bind(previous).bind(object_id).bind(&target_type).bind(target_id).bind(object_revision).fetch_one(&mut **tx).await? { return Err(invalid("correction predecessor must match target and precede revision"));
            }
            sqlx::query("INSERT INTO evidence_corrections(id,object_id,target_type,target_id,reason,representation,supersedes_correction_id,actor_id,object_revision,created_at,import_provenance) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::text::timestamptz,$11)").bind(id).bind(object_id).bind(target_type).bind(target_id).bind(reason).bind(representation).bind(supersedes_correction_id).bind(actor_id).bind(object_revision).bind(created_at).bind(json!({"import":provenance,"original":original})).execute(&mut **tx).await?;
            sqlx::query("UPDATE objects SET explicitly_corrected=true WHERE id=$1")
                .bind(object_id)
                .execute(&mut **tx)
                .await?;
            parent = Some(object_id);
        }
        Record::Object { object } => {
            let mut o = *object;
            if ![
                "user", "task", "memory", "note", "entity", "source", "theme", "event", "chat",
            ]
            .contains(&o.kind.as_str())
                || o.revision < 1
                || !o.provenance.is_object()
                || !o.authorship.is_object()
                || o.kind == "chat" && o.fields != json!({})
            {
                return Err(invalid(
                    "unsupported imported Object; historical Chat metadata belongs in the Chat subtype",
                ));
            }
            timestamp(&o.created_at)?;
            timestamp(&o.updated_at)?;
            if let Some(v) = &o.archived_at {
                timestamp(v)?;
            }
            let original_fields = o.fields.clone();
            if o.kind == "task" {
                let mapping = o.owner_mapping.as_ref().ok_or_else(|| {
                    invalid("Task import requires explicit source/destination owner mapping")
                })?;
                let original = o.fields["owner_object_id"]
                    .as_str()
                    .map(Uuid::parse_str)
                    .transpose()
                    .map_err(|_| invalid("invalid original owner"))?;
                if original != mapping.source_owner_id {
                    return Err(invalid(
                        "owner mapping must match original assigned/unassigned state",
                    ));
                }
                if !sqlx::query_scalar::<_, bool>(
                    "SELECT EXISTS(SELECT 1 FROM objects WHERE id=$1 AND kind='user')",
                )
                .bind(mapping.destination_owner_id)
                .fetch_one(&mut **tx)
                .await?
                {
                    return Err(invalid("mapped User must exist in this installation"));
                }
                o.fields["owner_object_id"] = json!(mapping.destination_owner_id);
            } else if o.owner_mapping.is_some() {
                return Err(invalid("only Tasks have owner mappings"));
            }
            if o.kind == "user"
                && (o.fields.as_object().is_none_or(|m| {
                    m.keys().any(|k| {
                        ![
                            "user_kind",
                            "avatar_asset_url",
                            "avatar_source",
                            "identities",
                        ]
                        .contains(&k.as_str())
                    })
                }) || !["human", "agent", "system"]
                    .contains(&o.fields["user_kind"].as_str().unwrap_or("")))
            {
                return Err(invalid(
                    "historical User fields only; no credentials or account grants",
                ));
            }
            if o.kind == "user"
                && o.fields.get("identities").is_some_and(|v| {
                    !v.is_array()
                        || v.to_string().len() > 262144
                        || v.as_array().unwrap().iter().any(|i| {
                            !i.is_object()
                                || ["id", "provider", "provider_user_id"]
                                    .iter()
                                    .any(|k| i[k].as_str().is_none_or(|s| s.trim().is_empty()))
                        })
                })
            {
                return Err(invalid(
                    "historical identities must be bounded profile objects, not login grants",
                ));
            }
            let mut provenance = provenance.clone();
            provenance["original_fields"] = original_fields;
            provenance["original_authorship"] = o.authorship;
            provenance["owner_mapping"] = json!(o.owner_mapping);
            sqlx::query("INSERT INTO objects(id,kind,title,description,fields,revision,created_by,updated_by,created_at,updated_at,archived_at,protected,provenance,import_provenance) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::text::timestamptz,$10::text::timestamptz,$11::text::timestamptz,$12,$13,$14)")
                .bind(o.id).bind(&o.kind).bind(&o.title).bind(&o.description).bind(&o.fields).bind(o.revision).bind(o.created_by).bind(o.updated_by).bind(o.created_at).bind(o.updated_at).bind(o.archived_at).bind(o.protected).bind(o.provenance).bind(provenance).execute(&mut **tx).await?;
            // References are checked after the whole batch, so Source + Artifact can stage atomically.
            parent = Some(o.id);
        }
        Record::Artifact {
            id,
            object_id,
            created_by,
            created_at,
            provenance: original,
            sha256,
            artifact,
        } => {
            supported_parent(tx, object_id).await?;
            timestamp(&created_at)?;
            evidence::insert(tx, a, object_id, *artifact, id, true).await?;
            let actual: String = sqlx::query_scalar("SELECT sha256 FROM artifacts WHERE id=$1")
                .bind(id)
                .fetch_one(&mut **tx)
                .await?;
            if actual != sha256 {
                return Err(invalid(
                    "imported artifact SHA-256 differs from supplied original bytes",
                ));
            }
            sqlx::query("UPDATE artifacts SET created_by=$2,created_at=$3::text::timestamptz,import_provenance=$4 WHERE id=$1").bind(id).bind(created_by).bind(created_at).bind(json!({"import":provenance,"original":original})).execute(&mut **tx).await?;
            parent = Some(object_id);
        }
        Record::Connection {
            id,
            from_id,
            to_id,
            kind,
            explanation,
            revision,
            created_by,
            created_at,
            updated_at,
            archived_at,
            protected,
            provenance: original,
        } => {
            supported_parent(tx, from_id).await?;
            supported_parent(tx, to_id).await?;
            timestamp(&created_at)?;
            timestamp(&updated_at)?;
            if let Some(v) = &archived_at {
                timestamp(v)?;
            }
            if from_id == to_id
                || revision < 1
                || explanation.trim().is_empty()
                || ![
                    "involves",
                    "about",
                    "related_to",
                    "depends_on",
                    "derived_from",
                    "themed",
                ]
                .contains(&kind.as_str())
            {
                return Err(invalid("invalid imported Connection"));
            }
            sqlx::query("INSERT INTO connections(id,from_id,to_id,kind,explanation,revision,created_by,created_at,updated_at,archived_at,protected,provenance,import_provenance) VALUES($1,$2,$3,$4,$5,$6,$7,$8::text::timestamptz,$9::text::timestamptz,$10::text::timestamptz,$11,$12,$13)")
                .bind(id).bind(from_id).bind(to_id).bind(kind).bind(explanation).bind(revision).bind(created_by).bind(created_at).bind(updated_at).bind(archived_at).bind(protected).bind(original).bind(provenance).execute(&mut **tx).await?;
            parent = Some(from_id);
        }
        Record::History {
            id,
            object_id,
            run_id,
            target_type,
            target_id,
            action,
            revision,
            actor_id,
            occurred_at,
            before_state,
            after_state,
            provenance: original,
        } => {
            if let Some(id) = object_id {
                supported_parent(tx, id).await?;
            }
            if target_type == "connection" {
                let endpoints: Vec<Uuid> = sqlx::query_scalar("SELECT from_id FROM connections WHERE id=$1 UNION SELECT to_id FROM connections WHERE id=$1")
                    .bind(target_id).fetch_all(&mut **tx).await?;
                for endpoint in endpoints {
                    conversations::active(tx, endpoint).await?;
                }
            }
            if let Some(run) = run_id {
                let row = sqlx::query("SELECT chat_object_id,deleted_at IS NOT NULL AS deleted FROM runs WHERE id=$1 FOR SHARE")
                    .bind(run).fetch_optional(&mut **tx).await?.ok_or_else(|| invalid("history Run must be staged first"))?;
                if row.get::<bool, _>("deleted") {
                    return Err(fail(StatusCode::GONE, "history Run deleted"));
                }
                if let Some(chat) = row.get::<Option<Uuid>, _>("chat_object_id") {
                    conversations::active(tx, chat).await?;
                }
            }
            timestamp(&occurred_at)?;
            let valid = target_type == "object" && Some(target_id) == object_id || target_type == "connection" && sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM connections WHERE id=$1 AND (from_id=$2 OR to_id=$2))").bind(target_id).bind(object_id).fetch_one(&mut **tx).await? || target_type == "entity_category" && object_id.is_none() && sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM entity_categories WHERE id=$1)").bind(target_id).fetch_one(&mut **tx).await?;
            if !valid
                || revision < 1
                || !after_state.is_null() && !after_state.is_object()
                || !before_state.is_null() && !before_state.is_object()
            {
                return Err(invalid(
                    "history must target its owning Object/Connection or an ownerless category",
                ));
            }
            sqlx::query("INSERT INTO record_history(id,object_id,target_type,target_id,action,revision,actor_id,occurred_at,before_state,after_state,import_provenance,run_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8::text::timestamptz,$9,$10,$11,$12)")
                .bind(id).bind(object_id).bind(target_type).bind(target_id).bind(action).bind(revision).bind(actor_id).bind(occurred_at).bind(before_state).bind(after_state).bind(json!({"import":provenance,"original":original})).bind(run_id).execute(&mut **tx).await?;
            parent = object_id;
        }
    }
    sqlx::query("INSERT INTO import_items(source_store,record_type,source_id,request_hash,destination_id,importer_id) VALUES($1,$2,$3,$4,$3,$5)").bind(store).bind(kind).bind(id).bind(hash).bind(a.id).execute(&mut **tx).await?;
    // Import observations do not rewrite original timestamps, revisions or actors.
    if let Some(parent) = parent {
        let revision: i64 = sqlx::query_scalar("SELECT revision FROM objects WHERE id=$1")
            .bind(parent)
            .fetch_one(&mut **tx)
            .await?;
        sqlx::query("INSERT INTO audit_events(object_id,actor_id,credential_id,action,revision) VALUES($1,$2,$3,'import_record',$4)").bind(parent).bind(a.id).bind(a.credential).bind(revision).execute(&mut **tx).await?;
        // Artifact/Connection staging must fence derived data without changing historical revision.
        sqlx::query("UPDATE objects SET revision=revision WHERE id=$1")
            .bind(parent)
            .execute(&mut **tx)
            .await?;
    }
    Ok(json!({"id":id,"imported":true,"object_id":parent}))
}

async fn supported_parent(tx: &mut sqlx::Transaction<'_, sqlx::Postgres>, id: Uuid) -> Result<()> {
    conversations::active(tx, id).await?;
    if !sqlx::query_scalar::<_, bool>("SELECT EXISTS(SELECT 1 FROM objects WHERE id=$1)")
        .bind(id)
        .fetch_one(&mut **tx)
        .await?
    {
        return Err(invalid("parent Object must be staged first"));
    }
    Ok(())
}
