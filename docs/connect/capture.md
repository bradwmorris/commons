# Optional conversation capture

Context access and capture are separate. An agent can use the ordinary
[authenticated API](../agent-integration.md) without uploading its conversation.
Capture is off by default. Everyone authenticated in the selected installation,
including connected agents, can read a submitted conversation. This does not make
the endpoint public or send anything to another installation.

**Implementation status:** Canonical storage, UI and the manual outbox are delivered.
The [opt-in host adapters](automatic-capture.md) add Codex/Amp reconciliation and
per-turn routing. They require separate reviewed installation and real-client
acceptance; this manual guide installs no vendor adapter or scheduler.
Synthetic transport tests are not evidence that a vendor's full interaction was
captured. No hidden reasoning, summaries, agent runtime or automatic knowledge
curation is required or supplied.

## The manual format is explicit, not an arbitrary export importer

`POST /api/capture` accepts `commons.capture/1`. Use an authenticated writer with
the `thread` write kind on schema 12. Reads remain organisation-shared. Source identity is
`provider` + `namespace` + `thread_id`, independent of token rotation. The first
accepted submission binds its writing identity; another writer cannot take over
that source. Sender User IDs are supplied attribution, not authenticated proof
of who spoke. Unknown speakers may remain null; historical User Objects do not
need accounts.

Example **synthetic** normalized envelope (replace speaker IDs only with Users
read from the selected installation):

```json
{
  "contract_version": "commons.capture/1",
  "source": {"provider": "manual", "namespace": "synthetic-host", "thread_id": "example-1"},
  "batch_id": "example-1-batch-1",
  "title": "Synthetic delivery check",
  "history": false,
  "coverage": {
    "status": "partial",
    "messages": "Selected visible messages only",
    "tools": "Not supplied",
    "attachments": "Not supplied",
    "history": "From explicit activation; earlier turns excluded",
    "gaps": ["This manual example is not full client capture"]
  },
  "items": [{
    "id": "f2389efb-821a-4ad9-a502-4555c27fcfc8",
    "source_item_id": "message-1",
    "turn_id": "turn-1",
    "position": 0,
    "kind": "message",
    "role": "human",
    "speaker_id": null,
    "source_created_at": null,
    "body": "Synthetic visible message",
    "artifact_ids": []
  }],
  "attachments": [],
  "runs": []
}
```

Keep source/item UUIDs, batch ID, exact body and ordering stable across retries.
Equal delivery returns the original result; changed content under an existing
identity conflicts. A new token does not create a new source identity. `position`
orders items, not arrival time; preserve unknown original timestamps as null.
Do not turn an observation timestamp into an invented source timestamp.

Items are `message`, `tool_call`, `tool_result` or `log`, with roles `human`,
`agent`, `tool` or `system`. Optional `tool_name`, `tool_call_id` and `status`
connect visible activity. Bodies are bounded at 1 MiB; each batch permits 200
items, 20 attachments and 50 Run reports, within a 30 MiB serialized envelope.
Split at item boundaries; never silently truncate. Run reports describe external
work, not server execution. Updates use the current `expected_revision`.

Attachments use `{ "id": "stable UUID", "artifact": { ... } }` and the shared
`save_artifact` input shape. Message `artifact_ids` reference attachments of the
same conversation. Text and supported PNG/JPEG original bytes use canonical
Artifacts; raw capture attachments are excluded from general semantic indexing.
A path, URL or rendered export is not original bytes. Unsupported, missing,
redacted and oversized content must have explicit coverage/reasons. Fetch only
approved attachment locations; do not follow arbitrary transcript URLs with
credentials or read arbitrary paths mentioned in tool output.

For unavailable image originals, preserve `media_type`, omit `body`/`image_base64`,
and set `capture_outcome: "unavailable"` with `capture_reason`. The UI shows the
reason without a download link. “Complete” images still require decoded PNG/JPEG
bytes. An envelope's overall coverage is caller-attested, not certified by Commons.

Historical submissions require an administrator session plus `history: true`.
That is a separate import decision, not an enable-capture side effect. The manual
outbox also requires `--approve-history`. It never discovers or scans history.

## Private outbox and simple controls

Run `python3 integrations/capture/commons_capture.py --help` from a product
checkout. Python 3.11+ and its standard library are sufficient. Install or copy
the generic executable to the execution host; organisation-specific routing
belongs in private host configuration, not this repository.

Choose a separate state directory per installation/provider/host:

- Linux/Orbs: `$XDG_STATE_HOME/commons/capture/<installation>/<provider>/<host>`;
  use `~/.local/state` when `XDG_STATE_HOME` is unset.
- macOS: `~/Library/Application Support/commons/capture/<installation>/<provider>/<host>`.

The directory must be private (0700). `delivery.sqlite3` contains the outbox and
source cursors; SQLite may also create `delivery.sqlite3-wal` and
`delivery.sqlite3-shm`. The database and WAL are private;
credentials live separately in an owner-only regular token file (0600). Do not
put either in Git, prompts or shared logs. HTTPS is required except loopback
development. The uploader does not follow redirects or inherit proxy routing.

The command sequence is:

1. `init --url <approved-origin> --installation <operator-label>` binds
   this outbox permanently to one destination. The label identifies your routing
   configuration; it is not a server-verified installation identity. It enables no source.
2. `enable --provider <provider> --namespace <namespace> --thread <thread-id>
   --scope <approved-scope> --acknowledge-shared-readership` explicitly enables
   exactly that source. Vendor adapters must establish an activation cutoff;
   this generic uploader does not read the vendor at all.
3. `enqueue <normalized-envelope.json> --cursor <source-cursor>` stores the batch
   and cursor atomically. The cursor is optional for manual submissions.
4. `flush --token-file <private-token-file>` sends eligible queued batches.
5. `status` reports queued/acknowledged/failed/deleted states without bodies.
6. `disable --provider <provider> --namespace <namespace> --thread <thread-id>`
   stops collection admission and pending sends. A request already in flight may
   finish before disable returns. Previously saved conversations remain.

Every command also requires `--state <directory>` before its subcommand. No
service, hook or scheduler is installed by these commands. Uninstall removes
the executable and any separately installed owned hook/service, not unrelated
client configuration. Disable first and reconcile the private outbox before
removing its state. Never automatically replay a restored outbox.

The outbox caps pending bodies at 32 MiB/500 batches. Full queues stop admission
without advancing the cursor. Transient network/408/429/5xx failures back off with
jitter for at most eight attempts; authentication, schema, redirect and conflict
errors stop that batch. Later batches of the same source wait. Fix the cause and
explicitly `retry --provider ... --namespace ... --thread ... --batch <id>`;
the saved body/identity stay unchanged. A 410 deletion response clears pending
bodies for that source and prevents re-enabling its deleted identity.

An offline, disabled or revoked client cannot receive that deletion response.
Its pending local copies remain until a later authorized delivery gets 410 or an
operator runs `purge-local --provider ... --namespace ... --thread ...`. This
irreversibly discards local pending bodies/cursors and keeps the source disabled
with a replay tombstone. It needs no server connection and **does not delete the
server conversation**. Reconcile every participating execution host; server
deletion is not proof that an unreachable host erased its queue.

This is a transient transport outbox, not a second conversation store or an
authoritative backup. A server dump cannot recover never-uploaded events. If
state is lost, reconcile against only approved source history and stable IDs;
do not silently restart from the beginning. If an operator copies an outbox,
stop its writer first or use SQLite's backup API; copying only the main database
while its WAL is active is not a consistent snapshot. Recovered state remains
sensitive and must not reconnect/replay automatically.

## Historical records remain passive

Existing historical Chats, messages and Runs retain supplied provenance, original
identifiers and missing/deleted references. They do not create accounts, launch
agents, enable schedules or resume old work. The compatibility implementation is
in `src/imports.rs` and `src/conversations.rs`; ordinary new writes still require
valid references. No missing Object or deleted content is reconstructed.

## Deletion and historical backups are different

Saved conversations remain until explicitly deleted; this stage adds no automatic
time-based expiry. Failed/disabled outbox batches likewise require reconciliation
or local purge rather than silently expiring and losing never-uploaded events.

Commons deletion removes managed conversation payloads, attachments, tracked
raw excerpts (including registered copies whose evidence pointer later changed),
linked Run payloads, payload history/corrections and derived indexes.
Payload-free identity tombstones prevent ordinary resubmission/retry from
restoring them. Independently authored knowledge may remain with deleted-source
lineage. Untracked retyped quotes, downloaded exports, vendor originals, operator
backups and forensic database/WAL erasure are outside that guarantee.

An old PostgreSQL backup can revive deleted content and credentials that were
valid when it was taken. Restore only into isolation, review manually, and do
not automatically reconnect capture or replay queues. No backup service,
deletion ledger, global session reset or deletion-safe historical restore is
promised here. See [installation lifecycle](../installation-lifecycle.md).

## Acceptance still required for real clients

Real-client acceptance must cover the selected client’s available visible
interaction under explicit capture consent. Record the exact installed versions,
speakers/order, commentary/final messages, tools, original attachment bytes,
fork/resume/compaction, restart/outage recovery and disable/deletion. Display
gaps; a text-only fixture or manual import is not a silent substitute.

Claude Code and local Amp remain additional #9 environments, not support inferred
from another client. Their tested setup/version/coverage must be recorded before
advertising automatic support. See [client interface evidence](clients.md).

### Thread and Run relationships

The UI labels Chats as **Threads**; existing `/chats` URLs and capture contracts
remain stable. Thread pages show authored Connections alongside supplied speakers,
parent thread, Runs, their actors and primary work. Run pages show actor, thread,
primary object, consulted objects and parent/child Runs. Both have Connection maps.

`GET /api/chats/{id}/relationships` and `GET /api/runs/{id}/relationships` return
`references` and `next_offset`, with the usual authenticated shared readership and
`limit` (1–200)/`offset` pagination. Each reference has `id`, `relation`, `title`,
`kind`, `archived_at`; missing targets retain the ID with null title/kind. The
read model deduplicates repeated references of the same relation; original Run
consulted order/repetitions remain unchanged. References are supplied claims, not
authored Connections or verified participation. Reading creates no records. The
map shows the current reference page and up to 200 saved Connections, with a
visible truncation notice; the related list retains all saved Connections. No schema migration,
backfill or relationship inference from prose is performed.

A paired Commons tool-call Trace may supply up to 50 `object_effects` with an
Object `id`, its observed positive `revision` and an `operation` of `read`,
`created` or `updated`. Capture saves a Connection for each available Object and
operation. An unavailable or deleted Object is skipped. A Thread includes the
Object references from its Traces, deduplicated by Object and relationship kind.

### Thread participants

Thread collections return a distinct `participants` array with User IDs, names, kinds and current avatar URLs. Both collection avatars and Thread relationship references include recorded speakers, linked Run actors, and active `involves` Connections to Users in either direction. Multiple humans and agents are supported; repeated appearances are deduplicated. Historical archived User identities remain attributable. The upload credential owner is not automatically treated as a participant, and missing speaker IDs are not guessed. Later captured speakers join the same participant set. These explicit references do not manufacture authored Connections.
