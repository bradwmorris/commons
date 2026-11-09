//! Safe public errors; never reflect database payloads.
use axum::{
    Json,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use serde_json::json;
#[derive(Debug)]
pub(crate) struct Error(pub(crate) StatusCode, pub(crate) String);
impl IntoResponse for Error {
    fn into_response(self) -> Response {
        (self.0, Json(json!({"error":self.1}))).into_response()
    }
}
impl From<sqlx::Error> for Error {
    fn from(e: sqlx::Error) -> Self {
        if let sqlx::Error::Database(ref db) = e
            && db.is_unique_violation()
        {
            return fail(
                StatusCode::CONFLICT,
                "identity already exists; look up the existing User or Issue Task",
            );
        }
        if let sqlx::Error::Database(ref db) = e
            && db.code().as_deref() == Some("23514")
            && db.message() == "conversation evidence deleted"
        {
            return fail(StatusCode::GONE, "conversation evidence deleted");
        }
        // Database detail can contain rejected supplied transcript values.
        eprintln!("database operation failed (details omitted)");
        Self(
            StatusCode::INTERNAL_SERVER_ERROR,
            "database operation failed".into(),
        )
    }
}
pub(crate) type Result<T> = std::result::Result<T, Error>;
pub(crate) fn fail(code: StatusCode, msg: &str) -> Error {
    Error(code, msg.into())
}
pub(crate) fn invalid(msg: &str) -> Error {
    fail(StatusCode::UNPROCESSABLE_ENTITY, msg)
}
