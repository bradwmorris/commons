//! OTLP/JSON span evidence within the existing capture and ten-table model.
use super::*;

pub const KIND: &str = "opentelemetry";

fn hex(value: &Value, len: usize, empty: bool) -> bool {
    value.as_str().is_some_and(|s| {
        (empty && s.is_empty())
            || (s.len() == len
                && s.bytes().all(|b| b.is_ascii_hexdigit())
                && s.bytes().any(|b| b != b'0'))
    })
}
fn nanos(v: &Value) -> Option<u64> {
    v.as_u64().or_else(|| v.as_str()?.parse().ok())
}

/// Preserve resource/scope/unknown extension fields and native IDs; never derive spans from text.
pub fn validate(source: &str, entries: &Value) -> Result<()> {
    let entries = entries
        .as_array()
        .ok_or_else(|| invalid("OTLP spans must be an array"))?;
    if entries.is_empty() || entries.len() > 2000 || !hex(&json!(source), 32, false) {
        return Err(invalid(
            "OTLP requires a native trace ID and 1–2000 spans per batch",
        ));
    }
    let mut seen = std::collections::HashSet::new();
    for entry in entries {
        let s = &entry["span"];
        if !entry["resource"].is_object()
            || !entry["scope"].is_object()
            || !s.is_object()
            || s["traceId"].as_str().map(str::to_ascii_lowercase)
                != Some(source.to_ascii_lowercase())
            || !hex(&s["spanId"], 16, false)
            || (!s["parentSpanId"].is_null() && !hex(&s["parentSpanId"], 16, true))
            || s["spanId"] == s["parentSpanId"]
            || s["name"].as_str().is_none_or(|n| n.is_empty())
            || nanos(&s["startTimeUnixNano"]).is_none_or(|n| n == 0)
            || nanos(&s["endTimeUnixNano"])
                .is_none_or(|n| n < nanos(&s["startTimeUnixNano"]).unwrap_or(u64::MAX))
            || !seen.insert(s["spanId"].as_str().unwrap_or("").to_ascii_lowercase())
            || (!s["kind"].is_null() && s["kind"].as_u64().is_none_or(|n| n > 5))
            || (!s["status"].is_null() && !s["status"].is_object())
            || (!s["status"]["code"].is_null()
                && s["status"]["code"].as_u64().is_none_or(|n| n > 2))
        {
            return Err(invalid(
                "Invalid OTLP span identity, parent, timing or status",
            ));
        }
        for key in ["attributes", "events", "links"] {
            if !s[key].is_null() && !s[key].is_array() {
                return Err(invalid("OTLP attributes, events and links must be arrays"));
            }
        }
        for link in s["links"].as_array().into_iter().flatten() {
            if !hex(&link["traceId"], 32, false) || !hex(&link["spanId"], 16, false) {
                return Err(invalid("Invalid OTLP span link"));
            }
        }
    }
    Ok(())
}

/// One resource/scope group per saved span is valid OTLP and preserves each context exactly.
pub fn export(entries: &Value) -> Value {
    json!({"resourceSpans": entries.as_array().into_iter().flatten().map(|e| {
        let mut scope = json!({"scope":e["scope"],"spans":[e["span"]]});
        if let Some(url) = e.get("scopeSchemaUrl") { scope["schemaUrl"] = url.clone(); }
        let mut resource = json!({"resource":e["resource"],"scopeSpans":[scope]});
        if let Some(url) = e.get("resourceSchemaUrl") { resource["schemaUrl"] = url.clone(); }
        resource
    }).collect::<Vec<_>>()})
}

pub async fn download(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Response> {
    let Json(detail) = conversations::read_run(State(app), headers, Path(id)).await?;
    let r = &detail["trace"];
    if r["kind"] != KIND {
        return Err(invalid(
            "This historical execution has no native OTLP spans",
        ));
    }
    let body = export(&r["trace"]);
    Ok((
        [(
            header::CONTENT_DISPOSITION,
            format!("attachment; filename=\"{id}.otlp.json\""),
        )],
        Json(body),
    )
        .into_response())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn entries() -> Value {
        json!([{"resource":{"attributes":[]},"scope":{"name":"synthetic"},"span":{
            "traceId":"11111111111111111111111111111111","spanId":"2222222222222222",
            "parentSpanId":"3333333333333333","name":"tool","startTimeUnixNano":"1700000000000000000",
            "endTimeUnixNano":"1700000000000000001","kind":1,"status":{"code":2},"events":[],"links":[]}}])
    }
    #[test]
    fn native_ids_timing_status_and_export_survive() {
        let v = entries();
        validate("11111111111111111111111111111111", &v).unwrap();
        assert_eq!(
            export(&v)["resourceSpans"][0]["scopeSpans"][0]["spans"][0],
            v[0]["span"]
        );
    }
    #[test]
    fn invalid_and_duplicate_spans_are_rejected() {
        let v = entries();
        let mut x = v.clone();
        x[0]["span"]["endTimeUnixNano"] = json!("1");
        assert!(validate("11111111111111111111111111111111", &x).is_err());
        assert!(validate("00000000000000000000000000000000", &v).is_err());
        assert!(validate("11111111111111111111111111111111", &json!([v[0], v[0]])).is_err());
    }
}
