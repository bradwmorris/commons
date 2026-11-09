# Integration API — `commons/0.1`

This reference describes the **schema12 candidate source**, not deployment or full
release acceptance. Use [agent integration](agent-integration.md) for the adopter
journey, [MCP setup](connect/mcp.md) for packaging, and [the schema contract](atomic-schema.md)
for physical storage. The three Python tools call this same authenticated API.

## Authentication

Health and login are unauthenticated. Login requires the exact configured browser
Origin. Other routes require an active, unexpired, unrevoked credential:
browser `commons_session` cookie or `Authorization: Bearer <agent-token>`.
A browser session is not a bearer token. Browser mutations require matching
`Origin`; caller-supplied actor headers grant no identity. Reads are shared across
the installation, not confidential per-team partitions.

Admin/member sessions can perform permitted writes; readers cannot. Agent tokens
also need the owning kind's scope. User creation, delegated token issuance and
retrieval rebuild require the appropriate browser session authority. Sessions
expire after 12 hours, tokens after 30 days unless revoked earlier.
No database credential is given to agents.

## Endpoints

Paths below are relative to the configured origin.

| Method and path | Current contract |
| --- | --- |
| GET `/api/health` | DB/schema readiness and build versions, not complete product/index readiness |
| POST `/api/login` | `{username,password}`, exact Origin; establishes HttpOnly SameSite session |
| POST `/api/logout` | Revokes current credential and clears browser cookie; browser Origin applies |
| GET `/api/me` | `{id,role,mode,write_kinds}` |
| GET `/api/contract` | Installed schema version, identity/scopes, operations, kinds and limits |
| GET `/api/schema` | Authenticated installed table/column/relationship snapshot |
| GET `/api/users` | `{users:[...]}` dedicated public identity projections, including retained historical identities; no password/token secrets |
| GET `/api/users/{id}` | `{user:...}`, not an Object read |
| POST `/api/users` | Admin session: `{username,title,role,user_kind?,password?}`; human default requires password; agent forbids password/admin role |
| GET `/api/participants?object_ids=UUID,UUID` | Up to 100 IDs; contribution User projections with role text (assignment is separate) and `next_offset:null`; not paged explained `involves` edges |
| GET `/api/tokens` | Own token metadata array; admin sessions see all; no token secrets |
| POST `/api/tokens` | Session: `{label,write_kinds,account_id?}`; token shown once. Only admin can target another active agent identity; no reader writes |
| POST `/api/tokens/{id}/revoke` | Session; own token or admin authority |
| GET `/api/users/{id}/avatar` | Authenticated raster bytes |
| POST `/api/users/{id}/avatar?expected_revision=N&source=TEXT` | Admin session; raw PNG/JPEG/WebP with matching MIME, at most 256 KiB; source 1–600 bytes; increments User revision |
| GET `/api/tasks/by-issue?github_issue_url=URL` | Current non-historical Task by canonical URL, `{object}`; 404 if absent |
| GET `/api/objects?q=words&kind=note&sort=recent&limit=50&offset=0` | Lexical title/description listing; details below |
| GET `/api/objects/{id}?limit=20&offset=0` | Complete bounded Object plus paged related metadata, never implicit full evidence |
| GET `/api/history/{id}` | Deliberate full stored change representation, `{history:...}` |
| GET `/api/corrections/{id}` | Deliberate full stored correction representation, `{correction:...}` |
| GET `/api/artifacts/{id}` | `{artifact:...}`, original stored text/metadata; binary bytes omitted |
| GET `/api/artifacts/{id}/text?offset=0&limit=24000` | Exact original Unicode text window |
| GET `/api/artifacts/{id}/content` | Exact stored text/binary content; 404 when content is not stored |
| GET `/api/connections?object_id=UUID&q=words&limit=50&offset=0` | Explained links; endpoint filter accepts Object/User/Artifact/Trace ID; `q` matches explanation |
| GET `/api/connections/{id}` | `{connection:...}` with typed endpoint projections |
| GET `/api/retrieve?q=words&scope=objects&limit=5&budget=24000` | Compact ranked candidates and bounded connected context; see [retrieval](retrieval.md) |
| GET `/api/orientation?limit=10` | Connection-degree overview, not truth/importance or a search boundary |
| GET `/api/retrieval/status` | Configured model, space and current chunk status |
| POST `/api/retrieval/rebuild` | Admin session/Origin, configured model required; resets derived work, returns rebuilding/keyword-only state |
| POST `/api/apply` | Atomic authorised mutations with validation, revisions and receipt |
| POST `/api/capture` | Separate `commons.capture/1` envelope; `thread` write scope, not automatic client capture |
| GET `/api/threads` | Paged current Threads |
| GET `/api/threads/{id}?limit=50&offset=0` | Thread and ordered observable items |
| GET `/api/threads/{id}/relationships` | Existing links and bounded Trace references |
| GET `/api/threads/{id}/text?expected_revision=2&offset=0&limit=1000` | Exact bounded conversation-search projection; 409 on stale revision |
| POST `/api/threads/{id}/delete` | Owner or admin session, `thread` scope; `{expected_revision,acknowledge_managed_copy_deletion:true}` |
| GET `/api/traces` | Paged retained execution headers |
| GET `/api/traces/{id}` | Trace details and available ordered items |
| GET `/api/traces/{id}/relationships` | Existing linked evidence references |
| GET `/api/traces/{id}/history` | Stored supplied/observed change representations |

`/api/chats` and `/api/runs` retain explicit aliases of the corresponding
Thread/Trace routes, including detail, relationships, Thread deletion and Trace
history. They are compatibility names, not extra Object kinds or physical tables.
There are no entity-category routes, User Objects, Memory kind, archive/protection
operation or built-in comparison API in this candidate.

### Collections and historical records

Object and Connection lists default to 50, accept `limit` 1–200, nonnegative
`offset` and `q` at most 2,000 bytes. Object lists accept one of seven `kind`
values. Threads are omitted unless `kind=thread` is explicit. Current lists exclude
`provenance.historical_only=true` and deleted records; retained historical Objects
can still be explicitly opened by ID. The legacy `archived=true` query produces no
current rows; it is not a historical browsing/restore API.

Object `sort=updated` uses metadata update time; `connected` uses edge count;
default/`recent` uses creation time, with stable ID ties. Object lists return
`objects,total,limit,offset,next_offset`; Connections return
`connections,total,next_offset`. Follow `next_offset`. Offset pages are current
snapshots, not one frozen inventory. Users is a separate unpaged projection.
Thread/Trace lists default to 50, accept 1–200 and nonnegative offset.

## Minimal HTTP examples

Use synthetic data and the selected installation's actual origin. Load
`COMMONS_TOKEN` from private client secret storage; never paste credentials into
source, prompts or saved evidence. These variables are client configuration.

```sh
curl --fail-with-body -sS "$COMMONS_URL/api/contract" \
  -H "Authorization: Bearer $COMMONS_TOKEN"

curl --fail-with-body -sS --get "$COMMONS_URL/api/objects" \
  -H "Authorization: Bearer $COMMONS_TOKEN" \
  --data-urlencode 'q=onboarding' --data-urlencode 'kind=note'

curl --fail-with-body -sS --get "$COMMONS_URL/api/retrieve" \
  -H "Authorization: Bearer $COMMONS_TOKEN" \
  --data-urlencode 'q=How do new colleagues obtain access?' \
  --data-urlencode 'scope=objects'

# OBJECT_ID must be an actual returned ID.
curl --fail-with-body -sS "$COMMONS_URL/api/objects/$OBJECT_ID" \
  -H "Authorization: Bearer $COMMONS_TOKEN"
```

Create `apply-request.json` privately with a stable action-specific key:

```json
{
  "contract_version":"commons/0.1",
  "idempotency_key":"synthetic-onboarding-note-1",
  "validate_only":true,
  "operations":[{
    "op":"create_object","local_ref":"note","kind":"note",
    "title":"Synthetic workshop onboarding",
    "description":"An access checklist for the fictional workshop.",
    "body":"Confirm the named owner before granting workshop access.",
    "fields":{"intent":"fact"}
  }]
}
```

```sh
curl --fail-with-body -sS "$COMMONS_URL/api/apply" \
  -H "Authorization: Bearer $COMMONS_TOKEN" \
  -H 'Content-Type: application/json' --data-binary @apply-request.json
```

Validate first, then set `validate_only:false` and submit the reviewed execution.
Read back `local_refs.note`; a dry-run ID is provisional and does not exist.
Successful execution returns `local_refs,changes,validated_only:false,saved:true`.
Validation rolls back and saves no receipt.

**HTTP defaults to execution if `validate_only` is omitted.** The product
`commons_write` tool instead defaults `execute:false` and translates it to
`validate_only:true`. Do not confuse these two interfaces.

## Writes and validation

An Object has exactly nine columns: `id,kind,title,description,body,fields,revision,
metadata,provenance`. There are seven kinds: task, note, entity, source, theme,
event, thread. The first six are writable through apply; Threads use capture.
Users, traces, chunks and history are not arbitrary writable Objects.

The entire formatted `title + description + body` uses the pinned local tokenizer
and must fit **500 tokens**, including formatting/special tokens. No silent
truncation, splitting or rewriting occurs. Title is one nonblank line, at most
200 characters; description is required, at most 600; body also has a 32 KiB byte
guard. Long exact material belongs in Artifacts. `fields` is at most 16 KiB and
accepts only the selected kind's keys. Server metadata/attribution is not writable.

| Operation | Arguments |
| --- | --- |
| `create_object` | `local_ref,kind,title,description,fields`; optional `body` |
| `ensure_task` | `local_ref,title,description,fields`; optional `body`; canonical Issue required |
| `update_object` | `object_id,expected_revision`; optional `title,description,body,fields` |
| `append_artifact` | `object_id,expected_revision,body` |
| `save_artifact` | `object_id,expected_revision,artifact` |
| `create_connection` | One typed endpoint each side, required endpoint revisions, `kind,explanation` |
| `update_connection` | `connection_id,expected_revision,explanation`; optional endpoint revisions |
| `delete_object` | `object_id,expected_revision,acknowledge_owned_content_deletion:true`; ordinary Objects only; see deletion semantics below |
| `delete_connection` | `connection_id,expected_revision`; optional endpoint revisions |
| `correct_evidence` | `object_id,expected_revision,target_type,target_id,reason,representation` |

Operations reject unknown keys. Omitted Object values remain unchanged; `fields`
partially merges keys and explicit null removes an optional key. The server
validates the resulting whole Object. ID/kind and server metadata cannot be patched.
An empty `body` clears it only if the resulting Object remains valid.

Batch size is 1–50 operations within the 32 MiB HTTP JSON body limit. A failed
transaction has no committed partial effects. Revisions advance after parent effects,
including Artifact writes and Connection changes. Read back before subsequent edits.
A `local_ref` resolves a returned ID; it is not a Connection endpoint within that batch.

### Type-specific fields

- Task requires `status` (backlog/todo/doing/review/done/blocked), `priority`
  (low/medium/high), `owner_object_id` (active dedicated User UUID), `due_at`
  (RFC3339 with timezone), `work_kind` (general/code). Nonblank body is required
  before doing. Optional `project` is a short slug in `fields.project`, not a
  parsed body line; also `agent_suitable,blocked_reason,completed_at,github_issue_url`.
- Note accepts `happened_at,intent,content_format,source_artifact_id,source_locator`.
  Intent is idea/excerpt/fact/insight/question; format is plain_text/markdown.
  A new text-offset excerpt must match the original Artifact exactly.
- Entity accepts `entity_kind,image_url`; no category membership fields.
- Source requires supported `source_kind`; optional `canonical_uri,byline,publisher,
  published_at,published_at_precision,last_accessed_at,original_language,
  original_media_type,original_artifact_reference,current_artifact_id`.
- Theme requires an immutable lowercase hyphenated `slug`.
- Event accepts `starts_at,starts_at_precision,ends_at,ends_at_precision,timezone`.
  Supply starts_at when the occurrence date is known; omit it when genuinely
  unknown. Never invent a timestamp. Supplied timestamps must be RFC3339 and
  supplied precision must be year/month/day/instant; preserve the known precision.

Validated migrated imports can retain an already-missing Task due date or historical
owner on unrelated edits. This is evidence-backed compatibility, not permission to
omit required values on new Tasks or fabricate import provenance.

## Typed Connections

Each side selects exactly one of `from_id/from_user_id/from_artifact_id/from_trace_id`
and the corresponding `to_*` field. Object/User/Trace creation endpoints require
current **`from_revision`/`to_revision`**. Artifacts are immutable and have no endpoint
revision. On update/delete the Connection's own `expected_revision` is required;
supplied non-Artifact endpoint revisions are checked, but not required by Rust.

Object scope is required for Object endpoints, parent scope for owned Artifacts,
`thread` scope for Traces; orphan Artifact endpoints and User-to-User links require
admin session authority. A link does not grant read or mutation permission.

Public kinds: involves/about/related_to/depends_on/derived_from/themed.
Endpoints must differ. Explanation is nonblank, at most 4,000 UTF-8 bytes.
Internal managed-copy/capture links are not arbitrary user-create kinds.
Object endpoint revisions advance; User/Trace references do not imply their revision
was incremented. Read Connections before update/delete to use their actual endpoints.

Connection response projections include `from_object/to_object` for typed endpoint
navigation; these can represent Users/Artifacts/Traces, not only Objects. Their
compatibility `from_id/to_id` projection must not be blindly reused as Object
endpoint input: inspect the typed FK columns.

## Issue-Task pairing

An optional canonical `https://github.com/OWNER/REPO/issues/POSITIVE_INTEGER`
belongs in `fields.github_issue_url`. No query, fragment, trailing slash or leading
zero Issue number. Repository identity is case-insensitive. Ordinary Tasks need
no Issue. `ensure_task` returns an existing current matching Task unchanged;
otherwise it validates/creates one. Read `local_refs` and the current Object rather
than expecting a `created` boolean or treating an old receipt as current progress.

```json
{
  "op":"ensure_task","local_ref":"task",
  "title":"Verify synthetic onboarding",
  "description":"A fictional installation verification task.",
  "body":"Save and read back a synthetic Note; record the result.",
  "fields":{
    "status":"todo","priority":"medium",
    "owner_object_id":"ACTUAL_ACTIVE_USER_UUID",
    "due_at":"AGREED_RFC3339_TIME_WITH_OFFSET","work_kind":"general",
    "project":"demo",
    "github_issue_url":"https://github.com/OWNER/REPO/issues/123"
  }
}
```

Replace placeholders from the selected installation and agreed deadline before
validation. Commons neither creates GitHub Issues nor verifies their existence/state.
This is not synchronisation or agent dispatch.

## Retry identity and attribution

Generic write receipts are scoped to authenticated **credential**, key and complete
execution request hash. Retain the exact execution body/key after a lost response.
Changing that body under the same key gives 409. A new credential is a new namespace,
not source deduplication; revocation/expiry prevents replay. Capture receipts use a
separate Thread-scoped identity across token rotation.

Auth/revision/schema checks and receipt persistence are server behavior. Caller
claims do not become server-observed actions or verified remote origin. The tools
never automatically retry writes or silently choose another store. An interrupted
POST can have committed: reconcile/read back before retrying; `saved:null` means
unknown at the tool transport, not proven failure.

## Source and Artifact ingestion

Extract with authorised external tools. Create a bounded Source; save the exact
capture with `save_artifact`, then read back the returned Artifact ID and fresh
parent revision. If needed, patch `fields.current_artifact_id`; do not replace
unrelated Source fields. Storage success does not prove remote completeness.

```json
{
  "op":"save_artifact","object_id":"ACTUAL_SOURCE_UUID","expected_revision":1,
  "artifact":{
    "kind":"article_text","title":"Supplied capture","body":"Exact extracted text",
    "media_type":"text/plain","capture_outcome":"complete",
    "semantic_indexing_enabled":true,
    "metadata":{"extractor":"external-client","original_reference":"https://example.test/article"}
  }
}
```

Accepted Artifact keys are `kind,title,body,uri,media_type,language,capture_outcome,
capture_reason,expected_size_bytes,semantic_indexing_enabled,metadata,
supersedes_artifact_id,captured_at,image_base64`.
Default kind is other, MIME text/plain, outcome complete, indexing enabled and
metadata empty. A complete text capture requires stored text. Incomplete,
unavailable, paywalled, disallowed, too_large or unsupported captures require a
reason; complete captures cannot have one. Null evidence stays null. Text is at
most 16 MiB UTF-8; current PNG/JPEG original-byte support is bounded separately
(at most 20 MiB/24 megapixels), complete and non-indexed. Ordinary reads omit bytes.

Versions append; they do not overwrite originals. Supersession must retain parent,
document key and media type. Hashes/sizes describe stored bytes, not unverified URL
targets. There is no built-in OCR/PDF/YouTube extractor or model-driven curator.

## Exact evidence and correction reads

Artifact `/text` accepts `offset` 0–16,777,216 and `limit` 1–48,000 Unicode
characters (default 24,000). Response includes `text,offset,limit,total_characters,
next_offset,sha256,bytes`. Follow until `next_offset:null`. Null text means no stored
text, not complete empty capture. Offset cannot exceed stored length. Full content
and deliberate Artifact metadata/text reads remain authenticated; downloads are
private/no-store and nosniff. Deleted managed evidence returns 410.

Object reads return their complete bounded body/fields and metadata-only pages of
Artifacts, Connections, history and corrections. Related sections default to 20,
maximum 200. Follow `page.next_offset`; nonzero offset needs `expected_revision`
from the first page and a changed Object gives 409. Each read is one repeatable-read
snapshot; separate pages are not a frozen multi-page inventory.

The candidate always uses that bounded read shape, even without `view=compact`.
The optional `view` value does not restore the old unpaged full-payload response.
`audit_events` is an empty compatibility array; changes/history are separate
deliberate reads. Long original snapshots can exceed an ordinary agent context.

`correct_evidence` records a reason (1–4,000 bytes), structured representation
(up to 16 MiB), ancestry and parent revision. Object corrections validate/apply
supplied title/description/body while retaining original change evidence.
Artifact corrections preserve the immutable original and affect the current
matching representation. Other accepted target names are message/run/trace/event;
their presence is not a guarantee of identical target-ownership validation.
An empty representation records withdrawal; it does not restore earlier Object text.

For original evidence read `/api/artifacts/{id}/text`. For corrected matches follow
the returned `match.read`: the Python read tool can window correction
`representation.body` or `representation.text` using `resource:"correction"`,
`field:"body"` or `"text"`, `offset`, `limit`. Those are tool arguments;
the HTTP correction route returns the full representation, not a server-side text
window. Corrected offsets must never be applied to the original Artifact.

## Errors and installation

401: invalid/expired/revoked credential. 403: scope/role/Origin. 404: unknown ID or
unstored original bytes. 409: stale revision/request-hash conflict. 410: deleted
conversation evidence. 422: unsupported/invalid data; framework parse errors can
precede domain validation. A timeout is not evidence of rollback.

`commons version` reports package/contract without DB access. `commons migrate`
is explicit; serve/bootstrap verify migration compatibility and never migrate on
startup. Mounted `DATABASE_URL_FILE` and `COMMONS_ADMIN_PASSWORD_FILE` are alternatives
to direct environment values; setting both forms fails. See
[installation lifecycle](installation-lifecycle.md) for the runnable sequence and
its current verification limits. Documentation changes run no migration.


## Stable identity and contribution attribution

Humans and agents are Users. Give each agent its own agent User and scoped token;
keep that User across chats and model changes. Model/provider authentication is
independent of Commons authentication. Never substitute a model name for a User.

`on_behalf_of` is an optional active human User UUID in `/api/apply` and
`/api/capture`. `X-Commons-On-Behalf-Of` supports other authenticated mutation
clients. If both are supplied they must agree. This is asserted human context,
not an identity override or a permission grant. Missing context permits agent-only
saves; assignment never supplies it. MCP can set `COMMONS_ON_BEHALF_OF` privately.
Context participates in receipt identity; keep it unchanged on retries.

The server preserves Object creators, records each action's authenticated User and
human context in change history, and records evidence creators and trace/log
recorders. Later edits add contributors without replacing the creator. Trace
updates retain their original actor. Participants project saved creation, editing,
evidence and conversation contributions with sourced private avatars. Assignment,
reads, searches and consulted links do not add participants to the consulted item.
Unknown imported identities remain unknown; there is no fabricated backfill.

Attribution on compact rows/cards and opened records uses icons only, with accessible
names and no native title/hover/focus tooltips. Users administration and deliberate
textual audit reads retain names and roles. Task assignment remains a separate API
field. The Task detail's Status, Assigned to, Due, Priority, Project and Work type
properties are display-only; their stored values and API mutation support remain.
Historical User avatars can be uploaded without reactivating the User.

Capture items accept an optional bounded `model` object containing observed `id`
and `provider`; missing fields remain unknown. Pi records initial model selection,
selection changes and response metadata in lifecycle traces/items. Codex uses actual
turn-context model metadata when supplied; native traces retain original telemetry.
New optional metadata does not rewrite acknowledged transcripts. Neither branding
nor a default model setting proves which model produced a historical response.

An admin session may submit `correct_attribution` in the normal validated/revisioned
apply transaction. Required: `object_id`, `expected_revision`, `target_type`,
`target_id`, `user_id`, nonempty bounded `reason`, and an `evidence` reference array.
Targets are `object` (the owning Object's creator), `artifact`, `connection`, `change` (effective attribution
for one retained original action), `trace`, `trace_item` (speaker), or
`trace_item_recorder`, or `capture_owner` (the authenticated submitter allowed to
continue an existing captured Thread, with an active real User). Optional `on_behalf_of` corrects known human context; omission
preserves prior context, explicit null leaves it unspecified. Each correction retains
its before-state, authenticated corrector and evidence in a separate change. Original
action payloads and trace-item hashes remain unchanged. Corrections appear in Object
history; read their full records deliberately through `/api/history/{id}`. Correct
only exact evidence-supported targets, never all activity by the shared credential.


## Ordinary Object deletion

`delete_object` uses normal `/api/apply` authorization (member/admin and the Object kind's write scope), validation-only rollback, atomic batches, current expected revision and credential-scoped stable retry keys. It supports Tasks, Notes, Sources, Entities, Themes and Events. Read before deleting; validate the exact batch, then execute and preserve the body/key on uncertain retries. A replay returns the original receipt. A different request under the same key returns 409.

Deletion removes current title/description/body/fields/provenance content, owned Artifact text/binary/metadata, derived search chunks and stored content/correction history for those targets. It retains an ID/kind/revision tombstone and attributed deletion audit. Normal Object and Artifact reads return 410; current lists/search omit them; writes and stale index jobs cannot resurrect them. This is removal, with no archive/restore action. Historical backups, external originals, exports and independently authored copies may retain content.

Incident Connections retain their IDs/endpoints with a neutral explanation and revised link revision; their saved explanation snapshots are scrubbed. Independent connected Objects, Users and Traces are not deleted or edited. An independent excerpt Note may retain its own content but becomes ineligible for retrieval when its original Artifact is deleted. Registered managed capture copies cannot be deleted with this operation: use their source Thread lifecycle. Deletion audit/history is deliberately readable by authenticated installation members; it contains tombstone information rather than removed original content.

Threads continue to use `POST /api/threads/{id}/delete`: `thread` scope, owner or admin session, current revision and explicit managed-copy acknowledgement. This separate endpoint removes the managed conversation/evidence/linked execution closure described in [capture](connect/capture.md). It is not `/api/apply`, has no generic write receipt, and clients must reconcile a lost response via reads rather than assume retry success. Traces are not ordinary Objects and have no standalone generic deletion operation; affected Traces are erased through that managed Thread lifecycle. Ordinary Object deletion does not erase independent Trace payloads that mention it.
