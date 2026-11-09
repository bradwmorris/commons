"""Authorized mutations: explicit operation schemas; Rust API is authoritative."""
from copy import deepcopy
from .client import Client, CommonsError
from .schema import REVISION, UUID_SCHEMA, WRITABLE_KINDS, obj, string, validate

NAME = "commons_write"
DESCRIPTION = (
    "Create/update/delete bounded atomic Objects, save long evidence as Artifacts, and create/update/delete explained Connections. "
    "Description must plainly state WHAT this record is, its subject/purpose—not a teaser; body supports the same idea. "
    "The server counts the whole formatted title+description+body with the pinned tokenizer (maximum500 tokens); "
    "oversize writes are rejected without saving. Never silently truncate/split/rewrite. Long material belongs in linked Artifacts. "
    "When saving useful knowledge, search relevant existing Objects and add justified specific Connections; no fixed link quota. "
    "Task creation requires fields.status, priority, owner_object_id (active User), due_at and work_kind; "
    "Source requires source_kind; Theme requires slug; Event starts_at should be supplied when known with matching starts_at_precision (year/month/day/instant); omit both when genuinely unknown. Never invent occurrence dates. "
    "Read current revisions first. Object fields are a PARTIAL merge; omitted keys/body/provenance remain unchanged; null removes an optional field. "
    "Use exact typed Connection endpoints/direction and a specific explanation. Creating links advances Object revisions; read back results. "
    "Save a new Object first: local_ref labels are not Connection endpoint UUIDs. Within a batch each link advances its Object endpoints by one; later links must use those advanced revisions. "
    "Default execute=false validates the atomic batch without saving. execute=true saves. Keep the same idempotency_key and identical operations "
    "for an uncertain execution retry; never blindly regenerate a key or overwrite a conflict. Validation is not a reservation: reread after conflict. "
    "Threads/capture, identities/credentials, chunks and history are not arbitrary editable tables. Authorized knowledge writes only."
)

TASK_FIELDS = {
    "status": {"type": "string", "enum": ["backlog", "todo", "doing", "review", "done", "blocked"]},
    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
    "owner_object_id": {**UUID_SCHEMA, "description": "Active dedicated User ID, not an Object or Entity."},
    "due_at": string("Required RFC3339 deadline with timezone; do not invent it."),
    "work_kind": {"type": "string", "enum": ["general", "code"]},
    "completed_at": {"type": ["string", "null"]}, "agent_suitable": {"type": ["boolean", "null"]},
    "blocked_reason": {"type": ["string", "null"]}, "project": {"type": ["string", "null"], "description": "Short project slug in fields.project, not a Project line in body."},
    "github_issue_url": {"type": ["string", "null"], "description": "Optional canonical GitHub Issue URL; ensure_task requires it."},
}
OTHER_FIELDS = {
    "happened_at": {"type": ["string", "null"]},
    "intent": {"type": "string", "enum": ["idea", "excerpt", "fact", "insight", "question"]},
    "content_format": {"type": "string", "enum": ["plain_text", "markdown", "plain"], "description": "Use plain_text or markdown for new Notes; plain is an accepted legacy alias when editing existing Notes."},
    "source_artifact_id": UUID_SCHEMA,
    "source_locator": {"type": "object", "description": "Excerpt locator, e.g. kind=text_offset,start,end in Unicode characters; body must equal original exactly."},
    "entity_kind": string(), "image_url": string(),
    "source_kind": {"type": "string", "enum": ["article", "paper", "podcast_episode", "video", "book", "report", "document", "dataset", "web_page", "social_post", "other"]},
    "canonical_uri": string(), "byline": string(), "publisher": string(),
    "published_at": string(), "published_at_precision": string(), "last_accessed_at": string(),
    "original_language": string(), "original_media_type": string(), "original_artifact_reference": string(),
    "current_artifact_id": UUID_SCHEMA, "slug": string("Required immutable Theme slug, lowercase words joined by hyphens."),
    "starts_at": string("Known Event occurrence: YYYY for year, YYYY-MM for month, YYYY-MM-DD for day, or RFC3339 for instant; pair with starts_at_precision. Omit when genuinely unknown; never invent dates."),
    "starts_at_precision": {"type": "string", "enum": ["year", "month", "day", "instant"], "description": "Must match the supplied starts_at value; omit with unknown starts_at."},
    "ends_at": string("Optional Event endpoint using the same formats as starts_at; supplied endpoints must have matching precision and nondecreasing order."),
    "ends_at_precision": {"type": "string", "enum": ["year", "month", "day", "instant"]},
    "timezone": string("Optional IANA timezone; supplied instant offsets must agree with it."),
}
# Per-kind allowed/required field combinations are server-validated; read schema or
# contract deliberately for installation details. This schema exposes known fields,
# not an unrestricted arbitrary JSON mutation channel.
FIELDS = obj({**TASK_FIELDS, **OTHER_FIELDS})
TITLE = string("Short one-line record name.", minLength=1, maxLength=200)
DESCRIPTION_FIELD = string("Explicitly what the record IS, what it concerns and its purpose. No invented attribution.", minLength=1, maxLength=600)
BODY = string("Bounded support for the same idea; full packet<=500 model tokens. Long exact text belongs in an Artifact.")
BASE = {"object_id": UUID_SCHEMA, "expected_revision": REVISION}
ARTIFACT = obj({
    "kind": string(), "title": {"type": ["string", "null"]}, "body": {"type": ["string", "null"]},
    "uri": {"type": ["string", "null"]}, "media_type": {"type": ["string", "null"]},
    "language": {"type": ["string", "null"]},
    "capture_outcome": {"type": "string", "enum": ["complete", "incomplete", "unavailable", "paywalled", "disallowed", "too_large", "unsupported"]},
    "capture_reason": {"type": ["string", "null"]}, "expected_size_bytes": {"type": ["integer", "null"]},
    "semantic_indexing_enabled": {"type": "boolean"}, "metadata": {"type": "object"},
    "supersedes_artifact_id": {"type": ["string", "null"], "format": "uuid"},
    "captured_at": {"type": ["string", "null"]}, "image_base64": {"type": ["string", "null"]},
})


def operation(name, properties, required):
    return obj({"op": {"const": name}, **properties}, ["op", *required])


CREATE = operation("create_object", {
    "local_ref": string("Label for returned ID; not yet usable as an endpoint UUID in this batch.", minLength=1),
    "kind": {"type": "string", "enum": WRITABLE_KINDS}, "title": TITLE,
    "description": DESCRIPTION_FIELD, "body": BODY, "fields": FIELDS,
}, ["local_ref", "kind", "title", "description", "fields"])
ENSURE = operation("ensure_task", {k: v for k, v in CREATE["properties"].items() if k not in ("op", "kind")},
                   ["local_ref", "title", "description", "fields"])
UPDATE_FIELDS = deepcopy(FIELDS)
for _field in UPDATE_FIELDS["properties"].values():
    # A null field patch removes an optional key; the complete candidate is checked
    # on the server so deleting a required field cannot create an invalid record.
    if "enum" in _field:
        _field["enum"] = [*_field["enum"], None]
    _type = _field.get("type")
    _field["type"] = list(dict.fromkeys((_type if isinstance(_type, list) else [_type]) + ["null"]))
UPDATE = operation("update_object", {**BASE, "title": TITLE, "description": DESCRIPTION_FIELD,
                   "body": BODY, "fields": UPDATE_FIELDS}, ["object_id", "expected_revision"])
ENDPOINTS = {f"{side}{suffix}": UUID_SCHEMA for side in ("from", "to")
             for suffix in ("_id", "_user_id", "_artifact_id", "_trace_id")}
FROM_REVISION = {**REVISION, "description": "Current from-endpoint revision. Exact name: from_revision. Required for Object/User/Trace, omitted for Artifact."}
TO_REVISION = {**REVISION, "description": "Current to-endpoint revision. Exact name: to_revision. Required for Object/User/Trace, omitted for Artifact."}
CONNECTION_REVISION = {**REVISION, "description": "Current Connection's own revision; separate from endpoint from_revision/to_revision."}
LINK = operation("create_connection", {**ENDPOINTS, "from_revision": FROM_REVISION, "to_revision": TO_REVISION,
    "kind": {"type": "string", "enum": ["involves", "about", "related_to", "depends_on", "derived_from", "themed"]},
    "explanation": string("Specific supported reason for this directed link; at most4000 UTF-8 bytes.", minLength=1, maxLength=4000),
}, ["kind", "explanation"])
OPERATIONS = [CREATE, ENSURE, UPDATE,
    operation("delete_object", {**BASE, "acknowledge_owned_content_deletion": {"const": True, "description": "Remove this ordinary Object and owned evidence/history content; ID tombstone and deletion audit remain. Independent connected Objects survive. Threads require separate managed deletion."}}, ["object_id", "expected_revision", "acknowledge_owned_content_deletion"]),
    operation("append_artifact", {**BASE, "body": string("Original evidence text; maximum16 MiB UTF-8.")}, ["object_id", "expected_revision", "body"]),
    operation("save_artifact", {**BASE, "artifact": ARTIFACT}, ["object_id", "expected_revision", "artifact"]), LINK,
    operation("update_connection", {"connection_id": UUID_SCHEMA, "expected_revision": CONNECTION_REVISION,
        "explanation": LINK["properties"]["explanation"], "from_revision": FROM_REVISION, "to_revision": TO_REVISION},
        ["connection_id", "expected_revision", "explanation"]),
    operation("delete_connection", {"connection_id": UUID_SCHEMA, "expected_revision": CONNECTION_REVISION,
        "from_revision": FROM_REVISION, "to_revision": TO_REVISION}, ["connection_id", "expected_revision"]),
    operation("correct_evidence", {**BASE, "target_type": {"type": "string", "enum": ["object", "artifact", "message", "trace", "run", "event"]},
        "target_id": UUID_SCHEMA, "reason": string(minLength=1, maxLength=4000),
        "representation": {"type": "object", "description": "Explicit correction assertion; original evidence remains readable. Empty object withdraws an assertion."}},
        ["object_id", "expected_revision", "target_type", "target_id", "reason", "representation"]),
]
INPUT_SCHEMA = obj({
    "idempotency_key": string("Stable per-user execution key; preserve exact operations on retry.", minLength=1, maxLength=200),
    "operations": {"type": "array", "minItems": 1, "maxItems": 50, "items": {"oneOf": OPERATIONS}},
    "execute": {"type": "boolean", "default": False},
    "on_behalf_of": {"anyOf": [UUID_SCHEMA, {"type":"null"}], "description":"Known human User context, separate from task assignment. Null explicitly leaves it unknown; omission uses configured context, if any."},
}, ["idempotency_key", "operations"])


async def execute(arguments: dict, client: Client) -> dict:
    # Discriminate by op before validating a union so a wrong argument gets an
    # actionable operation-specific error instead of an opaque oneOf failure.
    shallow = {**INPUT_SCHEMA, "properties": {**INPUT_SCHEMA["properties"], "operations": {
        **INPUT_SCHEMA["properties"]["operations"], "items": {"type": "object"}}}}
    validate(arguments, shallow)
    shapes = {shape["properties"]["op"]["const"]: shape for shape in OPERATIONS}
    for index, op in enumerate(arguments["operations"]):
        name = op.get("op")
        if not isinstance(name, str) or name not in shapes:
            raise CommonsError("invalid_arguments", f"operations[{index}]: unsupported op; accepted: {', '.join(shapes)}", saved=False)
        shape = shapes[name]
        unknown = set(op) - set(shape["properties"])
        if unknown:
            detail = f"operations[{index}] {name}: unsupported fields {', '.join(sorted(unknown))}. Accepted fields: {', '.join(shape['properties'])}."
            if name in ("create_connection", "update_connection", "delete_connection"):
                detail += " Endpoint revisions are from_revision and to_revision; expected_revision is the Connection's own revision for update/delete. No expected_* endpoint aliases are accepted."
            raise CommonsError("invalid_arguments", detail, saved=False)
        validate(op, shape, f"operations[{index}] {name}")
    if not arguments["idempotency_key"].strip() or len(arguments["idempotency_key"].encode()) > 200:
        raise CommonsError("invalid_arguments", "idempotency_key must be nonblank and at most200 UTF-8 bytes", saved=False)
    for op in arguments["operations"]:
        if op["op"] == "create_connection":
            for side in ("from", "to"):
                endpoints = [f"{side}{suffix}" for suffix in ("_id", "_user_id", "_artifact_id", "_trace_id") if f"{side}{suffix}" in op]
                if len(endpoints) != 1:
                    raise CommonsError("invalid_arguments", "Exactly one typed endpoint required on each side", saved=False)
                if not endpoints[0].endswith("_artifact_id") and f"{side}_revision" not in op:
                    raise CommonsError("invalid_arguments", "Current Object/User/Trace endpoint revisions required", saved=False)
        if op["op"] == "ensure_task" and not op["fields"].get("github_issue_url"):
            raise CommonsError("invalid_arguments", "ensure_task requires fields.github_issue_url", saved=False)
    payload = {"contract_version": "commons/0.1", "idempotency_key": arguments["idempotency_key"],
               "operations": deepcopy(arguments["operations"]), "validate_only": not arguments.get("execute", False)}
    if "on_behalf_of" in arguments:
        payload["on_behalf_of"] = arguments["on_behalf_of"]
    return await client.request("POST", "/api/apply", json=payload)
