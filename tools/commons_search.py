"""Compact discovery, with deliberate Artifact scope and connected context."""
from .client import Client, CommonsError
from .schema import KINDS, UUID_SCHEMA, integer, obj, string, validate

NAME = "commons_search"
DESCRIPTION = (
    "Find relevant shared knowledge as compact Objects, starting with title/description signals. "
    "One semantic vector includes the whole bounded Object (body too); it is not summary-only semantic search. "
    "Default scope=objects includes stored visible Thread bodies; threads selects only those conversations, excluding native span telemetry. Follow thread_text references with expected_revision. Incomplete Source evidence stays excluded; inspect exclusion counts. Use artifacts or all to search long original evidence, optionally within object_id. "
    "Results contain IDs, kind, title, description, revision and read references, never full bodies. "
    "Follow match.read/field/locator for exact Artifact or correction text; corrected offsets never address the original Artifact. "
    "Direct matches and bounded connected context are labelled separately with actual relationship explanations. "
    "limit counts direct matches; neighbours can add context. Read selected Objects/Artifacts with commons_read. "
    "Check mode, reason, index.scope_pending/scope_failed and truncated: requested-scope model/index problems return keyword-only results. index.coverage states whether counts are requested-scope or global. Use commons_read resource=index for global diagnostics; Object search does not hash long Artifact bodies. "
    "No result is proof of truth; missing results are not proof that knowledge does not exist."
)
INPUT_SCHEMA = obj({
    "query": string("Question, keywords, exact title or known Object UUID; at most 500 UTF-8 bytes.", minLength=1, maxLength=500),
    "kind": {"type": "string", "enum": KINDS, "description": "Optional Object-type filter, applied before ranking."},
    "object_id": {**UUID_SCHEMA, "description": "Optional owning Object scope; use with Artifact evidence searches."},
    "scope": {"type": "string", "enum": ["objects", "artifacts", "threads", "all"], "default": "objects"},
    "limit": integer(1, 10, 5), "neighbours": integer(0, 5, 5),
    "budget": {**integer(2000, 24000, 24000), "description": "Maximum UTF-8 bytes of returned context, excluding envelope."},
}, ["query"])


async def execute(arguments: dict, client: Client) -> dict:
    validate(arguments, INPUT_SCHEMA)
    if not arguments["query"].strip() or len(arguments["query"].encode("utf-8")) > 500:
        raise CommonsError("invalid_arguments", "query must be nonblank and at most 500 UTF-8 bytes", saved=False)
    params = {"q": arguments["query"], **{k: v for k, v in arguments.items() if k != "query"}}
    return await client.request("GET", "/api/retrieve", params=params)
