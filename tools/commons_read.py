"""Deliberate current/evidence/schema/relationship reads, never arbitrary URLs."""
from .client import Client, CommonsError
from .schema import KINDS, REVISION, UUID_SCHEMA, integer, obj, string, validate

NAME = "commons_read"
DESCRIPTION = (
    "Open a known Object with its complete bounded body and fields; related metadata is paged, not expanded original content. "
    "Connection endpoints are compact identities with read arguments; open an endpoint deliberately for its body/fields. "
    "Follow selected Artifact text windows, Connections, changes/history, Threads or Traces deliberately. "
    "For connections pass object_id to inspect links involving an Object/User/Artifact/Trace; query searches explanation text. "
    "Use schema for detailed installation field/type guidance and contract for API capabilities/identity when needed, not as mandatory startup calls. "
    "Users are separate identities; Threads are Objects, Traces are not. Credential secrets and binary content are never returned by this tool. "
    "Offsets for Artifact and thread_text reads are Unicode characters; follow next_offset. thread_text requires the revision returned by search. Object continuation requires expected_revision from the first page. "
    "For corrected-text matches follow match.read: correction+field body/text reads a bounded Unicode window of that exact representation, not the original Artifact. "
    "Full historical/correction evidence without a field is explicit and may be long; do not treat original corrected evidence as the current assertion."
)
RESOURCES = ["object", "artifact", "artifact_metadata", "connection", "connections", "history", "correction",
             "thread", "thread_text", "threads", "trace", "traces", "trace_history", "user", "users", "schema", "contract", "index", "issue_task", "objects"]
INPUT_SCHEMA = obj({
    "resource": {"type": "string", "enum": RESOURCES}, "id": UUID_SCHEMA,
    "object_id": {**UUID_SCHEMA, "description": "Endpoint filter for connections, including typed User/Artifact/Trace endpoints."},
    "query": string("Optional connection-explanation or Object title/description query."),
    "kind": {"type": "string", "enum": KINDS},
    "field": {"type": "string", "enum": ["body", "text"], "description": "Correction representation string field; enables offset/limit windows of corrected text."},
    "issue_url": string("Canonical GitHub Issue URL, for issue_task."),
    "limit": integer(1, 48000), "offset": integer(0, 2147483647), "expected_revision": REVISION,
}, ["resource"])
SINGLE = {"object": "objects", "artifact": "artifacts", "artifact_metadata": "artifacts", "connection": "connections",
          "thread_text": "threads", "history": "history", "correction": "corrections", "thread": "threads", "trace": "traces",
          "trace_history": "traces", "user": "users"}
COLLECTION = {"connections": "connections", "threads": "threads", "traces": "traces", "users": "users", "objects": "objects"}


def connection_summary(connection):
    """Keep relationship semantics; nested endpoints are discovery, not full reads."""
    result = dict(connection)
    for side in ("from_object", "to_object"):
        endpoint = result.get(side)
        if not isinstance(endpoint, dict):
            continue
        compact = {k: endpoint[k] for k in ("id", "kind", "endpoint_type", "title", "description", "revision", "object_id", "deleted") if k in endpoint}
        resource = {"object": "object", "user": "user", "artifact": "artifact", "trace": "trace"}.get(endpoint.get("endpoint_type"))
        if endpoint.get("kind") == "thread":
            resource = "thread"
        if resource and endpoint.get("id"):
            compact["read"] = {"resource": resource, "id": endpoint["id"]}
        result[side] = compact
    return result


async def execute(arguments: dict, client: Client) -> dict:
    validate(arguments, INPUT_SCHEMA)
    resource = arguments["resource"]
    allowed = {"resource"}
    params = {}
    if resource in SINGLE:
        allowed.add("id")
        if "id" not in arguments:
            raise CommonsError("invalid_arguments", "id is required for this resource", saved=False)
        path = f"/api/{SINGLE[resource]}/{arguments['id']}"
        if resource == "thread_text":
            path += "/text"
            allowed |= {"limit", "offset", "expected_revision"}
            if "expected_revision" not in arguments:
                raise CommonsError("invalid_arguments", "thread_text requires expected_revision from search", saved=False)
            params = {"limit": arguments.get("limit", 24000), "offset": arguments.get("offset", 0), "expected_revision": arguments["expected_revision"]}
        elif resource == "artifact":
            path += "/text"
            allowed |= {"limit", "offset"}
            params = {"limit": arguments.get("limit", 24000), "offset": arguments.get("offset", 0)}
        elif resource == "correction" and "field" in arguments:
            allowed |= {"field", "limit", "offset"}
        elif resource == "trace_history":
            path += "/history"
        elif resource in ("object", "thread"):
            allowed |= {"limit", "offset"}
            params = {"limit": arguments.get("limit", 20), "offset": arguments.get("offset", 0)}
            if resource == "object":
                allowed.add("expected_revision")
                if params["offset"] and "expected_revision" not in arguments:
                    raise CommonsError("invalid_arguments", "Object continuation needs expected_revision from first read", saved=False)
                if "expected_revision" in arguments:
                    params["expected_revision"] = arguments["expected_revision"]
    elif resource in COLLECTION:
        path = f"/api/{COLLECTION[resource]}"
        if resource != "users":
            allowed |= {"limit", "offset"}
            params = {"limit": arguments.get("limit", 20), "offset": arguments.get("offset", 0)}
        if resource in ("objects", "connections"):
            allowed.add("query")
            params["q"] = arguments.get("query", "")
        if resource == "connections":
            allowed.add("object_id")
            if "object_id" in arguments:
                params["object_id"] = arguments["object_id"]
        if resource == "objects":
            allowed.add("kind")
            if "kind" in arguments:
                params["kind"] = arguments["kind"]
    else:
        path = {"schema": "/api/schema", "contract": "/api/contract", "index": "/api/retrieval/status",
                "issue_task": "/api/tasks/by-issue"}[resource]
        if resource == "issue_task":
            allowed.add("issue_url")
            if "issue_url" not in arguments:
                raise CommonsError("invalid_arguments", "issue_url required", saved=False)
            params["github_issue_url"] = arguments["issue_url"]
    if set(arguments) - allowed:
        raise CommonsError("invalid_arguments", "arguments not supported for selected resource", saved=False)
    if resource not in ("artifact", "correction", "thread_text") and params.get("limit", 1) > 200:
        raise CommonsError("invalid_arguments", "metadata page limit is at most 200", saved=False)
    result = await client.request("GET", path, params=params or None)
    if isinstance(result.get("connections"), list):
        result = {**result, "connections": [connection_summary(c) for c in result["connections"]]}
    if isinstance(result.get("connection"), dict):
        result = {**result, "connection": connection_summary(result["connection"])}
    if resource == "artifact_metadata":
        artifact = result.get("artifact", {})
        result = {"artifact": {k: artifact.get(k) for k in (
            "id", "object_id", "title", "kind", "media_type", "sha256", "size_bytes",
            "capture_outcome", "capture_reason", "supersedes_artifact_id", "created_at")},
            "body_omitted": artifact.get("body") is not None}
    if resource == "correction" and "field" in arguments:
        correction = result.get("correction", {})
        field = arguments["field"]
        text = correction.get("representation", {}).get(field)
        if not isinstance(text, str):
            raise CommonsError("unsupported_correction_text", "Selected correction field is not a text string", saved=False)
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 24000)
        end = min(offset + limit, len(text))
        result = {"correction_id": correction.get("id", arguments["id"]), "target_id": correction.get("target_id"),
                  "field": "representation." + field, "text": text[offset:end], "offset": offset, "limit": limit,
                  "total_characters": len(text), "next_offset": end if end < len(text) else None}
    # Ordinary browse remains selectable metadata even if UI API uses rich rows.
    if resource == "objects":
        result = {**result, "objects": [{k: o[k] for k in ("id", "kind", "title", "description", "revision") if k in o}
                   | {"read": f"/api/objects/{o['id']}"} for o in result.get("objects", [])]}
    return result
