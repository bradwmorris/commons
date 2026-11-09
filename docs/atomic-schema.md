# Atomic Commons schema

Implementation contract for the schema-10 foundation (issue #31) and schema-11 Thread search extension. Fresh installs
and upgrades end with the same ten application tables. Migration bookkeeping is
not an application table. Private records and backups never belong in this file.

- `objects`: exactly `id, kind, title, description, body, fields, revision,
  metadata, provenance`. Kinds: task, note, entity, source, theme, event, thread.
  Task `fields.project` replaces parsing a Project line on each read. Migration
  extracts the existing single Project line, preserving the original brief.
  The body contains supporting content, not a second copy in fields.
- `users`: human/agent identity and authentication, including historical users
  without an active login; preserves IDs. No User Objects. Public user projections
  exclude password hashes and credential secrets. Avatars are stored here.
- `credentials`: existing hashed sessions and scoped tokens referencing users.
- `artifacts`: exact original text/binary versions and capture metadata. Binary
  payloads are explicit-download only. Long source text does not live in Objects.
- `changes`: retained mutation/history/correction/import evidence (explicit deletion scrubs owned content), with exact
  before/after representations and explicitly supplied versus observed attribution.
- `connections`: explained typed links. Object endpoints retain `from_id/to_id`;
  alternative nullable FK columns are `from_user_id/from_artifact_id/from_trace_id`
  and their `to_` counterparts. Exactly one endpoint on each side is populated.
  Each is an actual FK; no unchecked polymorphic IDs. This extends the approved
  eight-column Object-link shape by six endpoint columns for the already-required
  User/Artifact/Trace links. `metadata` holds writer/time; `provenance` holds bounded
  lineage, operation and Object revision references. Source-copy membership is an
  explicit typed `managed_copy` link, not inferred from a mutable pointer.
- `request_receipts`: namespace, owner ID, key, request hash and result. Generic
  writes are credential-scoped; capture batches are Thread-scoped across rotation.
- `traces`: observed request/legacy execution headers. Historical kinds and absent
  request correlation remain explicit. Thread stream items may lack a trace ID;
  migration must not invent request executions from messages alone.
- `trace_items`: independently paged messages, calls, results, logs and observed
  steps, with Thread ID and optional known Trace ID, stable source identity/order,
  immutable payload and known timestamps. A long Thread never expands Object body.
- `chunks`: derived current search entries, defined below. No generation table.

## Retrieval handoff

`chunks` columns: `id uuid`, `object_id uuid NOT NULL REFERENCES objects`,
`artifact_id uuid NULL REFERENCES artifacts`, `ordinal integer NOT NULL`,
`reference text NOT NULL`, `body text NOT NULL`, `input_hash text NOT NULL`,
`object_revision bigint NOT NULL`, `space text NOT NULL`,
`embedding vector(768) NULL`, `status text NOT NULL` (pending/processing/ready/failed),
`attempts integer NOT NULL DEFAULT 0`, `available_at timestamptz NOT NULL DEFAULT now()`,
`claim uuid NULL`, `claimed_at timestamptz NULL`, `error text NULL`,
`updated_at timestamptz NOT NULL DEFAULT now()`.

Unique `(object_id, ordinal)` where artifact_id IS NULL; ordinary Object ordinal=0; Thread conversation windows have increasing ordinals.
Unique `(artifact_id, ordinal)` where artifact_id IS NOT NULL. Object rows are
exactly one input each for ordinary Objects; Thread and Artifact rows may have multiple ordinals. Pending rows
with no vector represent required work; hash/config comparison detects absent or
stale entries. A ready vector is usable only for its current input hash/space.
Reconcile absence, Artifact edits/deletion/eligibility, claims and restart without
another source/job/generation table. Empty Artifacts require no chunks, distinct
from failed extraction/embedding. Do not split or combine Object and Artifact text.

Canonical Object input is `packet::input(title, description, body)`:
`title: {title} | text: {description}\n\n{body}`. Exact pinned tokenizer includes
BOS/EOS and rejects >500 tokens. It is local, not an inference request. The model
must receive this already-formatted input without adding the prefix again.
Title and description stay primary keyword signals; the single semantic vector
includes body. Public Object reads expose top-level body and structured metadata.
The API may retain explicit historical route aliases, not extra physical tables
or duplicated content. Derived entries must exclude deleted/raw managed capture,
superseded evidence and private historical change payloads.

## UI preservation

Use existing row/detail/editor components. Collection rows remain one line with
ellipsis; body and provenance do not become extra row previews. Task properties
remain a single vertical stack, label/value on each line. Users stay in the Users
screen, independent of Objects. Notes replace Memories; Themes replace Categories;
Threads replace Chats; Traces are separate readers, not Objects. Full content and
history are available on deliberate open. See issue #31 for visual acceptance.

## Historical records

Imported archived records can be retained as readable history, excluded from current lists/search. Migration marks
only those existing rows with provenance.historical_only=true, retaining IDs and
original changes/evidence. No Archive/Restore feature or mutable archive column
is added. Explicit reads/history links remain available; derived retrieval and
normal collection counts exclude them. This preserves prior exclusion rather
than silently reactivating old records.

## Existing field compatibility

Events retain year (`YYYY`), month (`YYYY-MM`), day (`YYYY-MM-DD`) and RFC3339
instant precision. Supply the value and matching precision together when known;
omit both when unknown. Preserve chronological order and IANA timezone checks.
New Notes use `plain_text` or `markdown`; legacy `plain` remains readable/editable.
Source current-Artifact pointers must identify their own complete text Artifact.
Publication timestamps retain their precision pairing. New excerpt bodies must
match immutable evidence, including validated Unicode offsets/page/time/section
locators. Unchanged migrated historical locators remain readable/editable.
The explicit migration command refreshes planner statistics after the bulk load.


Schema 11 adds bounded Thread conversation chunks: migration 0011 removes the former `artifact_id IS NOT NULL OR ordinal=0` check. Unique `(object_id,ordinal)` identity remains for non-Artifact chunks. Ordinary Objects still receive exactly one packet from application validation; Threads may receive multiple token-bounded windows with revision-fenced references. No original capture content is migrated or rewritten. Existing schema-10 images refuse the additional migration; deployment requires a reviewed compatible image and explicit migration.

Schema 12 adds a transactional GIN keyword index over visible capture item bodies.
The immutable lexeme function uses overlapping bounded windows, avoiding the
PostgreSQL tsvector size limit for large messages. Retrieval checks the current
correction and exact item window after candidate discovery; original bodies and
corrections remain unchanged. Native spans are excluded. The ten application
tables remain unchanged. Schema-11 images refuse this additional migration.
