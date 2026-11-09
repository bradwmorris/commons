//! Read-only snapshot exported by the overlay maintainer.
use crate::{Actor, App, Result, actor, fail};
use axum::{
    Json,
    extract::State,
    http::{HeaderMap, StatusCode, header},
    response::IntoResponse,
};
use serde::{Deserialize, Serialize};
use std::{env, fs::File, io::Read, sync::Arc};

const MAX_BYTES: u64 = 1024 * 1024;

#[derive(Clone)]
pub enum Inventory {
    Disabled,
    Unavailable,
    Ready(Arc<Snapshot>),
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    version: u8,
    installation: String,
    revision: String,
    entries: Vec<Entry>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Entry {
    category: Category,
    path: String,
    text: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Category {
    Instructions,
    Skill,
    Tool,
    Workflow,
}

impl Inventory {
    pub fn configured(installation: &str) -> Self {
        let Some(path) = env::var_os("COMMONS_OVERLAY_INVENTORY_FILE").filter(|p| !p.is_empty())
        else {
            return Self::Disabled;
        };
        let snapshot = (|| {
            // Reject special files and bound the read even if the file changes.
            if !std::fs::metadata(&path).ok()?.is_file() {
                return None;
            }
            let mut bytes = Vec::new();
            File::open(path)
                .ok()?
                .take(MAX_BYTES + 1)
                .read_to_end(&mut bytes)
                .ok()?;
            if bytes.len() as u64 > MAX_BYTES {
                return None;
            }
            let snapshot: Snapshot = serde_json::from_slice(&bytes).ok()?;
            (snapshot.version == 1 && snapshot.installation == installation).then_some(snapshot)
        })();
        match snapshot {
            Some(snapshot) => Self::Ready(Arc::new(snapshot)),
            None => {
                eprintln!(
                    "Overlay inventory unavailable: check the snapshot and installation name"
                );
                Self::Unavailable
            }
        }
    }

    pub fn enabled(&self) -> bool {
        !matches!(self, Self::Disabled)
    }
}

pub fn can_browse(viewer: &Actor) -> bool {
    viewer.mode == "session" && matches!(viewer.role.as_str(), "admin" | "member")
}

pub async fn read(State(app): State<App>, headers: HeaderMap) -> Result<impl IntoResponse> {
    if !app.overlay_inventory.enabled() {
        return Err(fail(StatusCode::NOT_FOUND, "unknown API route"));
    }
    let mut tx = app.db.begin().await?;
    let viewer = actor(&app, &headers, &mut tx, false).await?;
    if !can_browse(&viewer) {
        return Err(fail(
            StatusCode::FORBIDDEN,
            "member or administrator session required",
        ));
    }
    let Inventory::Ready(snapshot) = &app.overlay_inventory else {
        return Err(fail(
            StatusCode::SERVICE_UNAVAILABLE,
            "Overlay inventory is unavailable.",
        ));
    };
    Ok((
        [(header::CACHE_CONTROL, "no-store")],
        Json(snapshot.as_ref()),
    )
        .into_response())
}
