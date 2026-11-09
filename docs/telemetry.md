# Native Codex traces

Threads retain supplied visible messages and tool calls/results. Native traces
retain timed operations measured by Codex itself. Existing historical executions
remain historical executions; Commons does not manufacture spans from transcripts.

## Supported path

Codex → authenticated loopback OTLP/HTTP JSON receiver → per-turn business route
and source lifecycle checks → private durable capture outbox → authenticated
`POST /api/capture` → existing `traces` / `trace_items` → trace viewer and OTLP download.

The native exporter is separately configured as `otel.trace_exporter`.
`otel.exporter` controls logs; enabling logs alone does not supply native spans.
The first compatibility probe used the desktop-bundled Codex
`0.166.0-alpha.5.1` and managed-server `0.166.0`: deterministic loopback
Responses fixtures made model-transport requests and executed harmless commands
through the actual Codex runtime, including a controlled nonzero tool exit. It exported
native turn roots, model transport, tool and internal spans with parentage, timing,
conversation/turn IDs and events. This is runtime instrumentation evidence, not a
real-model quality or production completeness measurement. Recheck on upgrades.

## Opt-in host bridge

Run from an installed copy of `integrations/capture/` containing
`codex_otel.py`, `auto_capture.py` and `commons_capture.py`. Use a **new** private
bridge state directory, the existing automatic capture state as a read-only routing
source, and a separate owner-only loopback receiver credential (at least32 chars):

```sh
python3 -B /path/to/codex_otel.py \
  --capture-state /private/existing-capture-state \
  --state /private/native-telemetry-state \
  --token-file /private/receiver-token --port 18418
```

The bridge only binds `127.0.0.1`. It accepts uncompressed OTLP/HTTP JSON on
`POST /v1/traces`, with `Authorization: Bearer ...`. Binary protobuf, gRPC,
compressed requests, logs and metrics are not accepted by this narrow bridge.
A standard Collector can convert transports upstream if separately configured.
Authenticated `GET /` reports counts and a generic delivery error, never payloads.
Requests are capped at8 MiB /5000 spans. The receiver credential is separate from
the Commons API credential; it does not grant API access.

For a separately launched controlled Codex process, supply this user-level
configuration in a private, mode-0600 user config. Replace
`RECEIVER_TOKEN` with the token from the receiver's private file. Keep this file
out of Git. The tested bundled CLI sent the literal `${COMMONS_OTLP_TOKEN}`
placeholder as a header and the receiver returned 401.

```toml
[otel]
exporter = "none"
trace_exporter = { otlp-http = { endpoint = "http://127.0.0.1:18418/v1/traces", protocol = "json", headers = { Authorization = "Bearer RECEIVER_TOKEN" } } }
log_user_prompt = false
log_agent_responses = false
```

Codex ignores telemetry settings in project-local `.codex/config.toml`. Broad
user-level activation affects all clients using that config; exporter initialization
may require restarting the relevant client/server process. Validate the exact
installed build and its startup behavior before activating this for a desktop.
Do not restart an active coding process or silently extend capture to other domains.
Stopping the bridge and removing the added exporter setting stops future delivery;
rollback does not unsend data already accepted by Commons.

## Admission and coverage

The bridge waits for a completed native `run_turn` carrying explicit
`conversation.id` and `turn.id`, or the desktop `session_task.turn` carrying
`thread.id` and `turn.id`. Both identifiers must be unambiguous canonical UUID
strings. Numeric OS `thread.id` values are ignored; conflicting chat UUIDs are
rejected. If both correlated root names arrive, they must describe the same turn
and have a unique outer root proven by their span parentage. The existing
business routing, activation window and acknowledged source Thread checks apply
equally to either root format.
Only that span and its available descendants are selected. A conflicting explicit
thread/turn identity rejects the group. Startup, unrelated native traces and
unassociated or unsupported subagent traces are excluded. Native IDs, timestamps,
status, links, events, resources and instrumentation scopes are retained after
credential redaction; parent spans outside the selected boundary remain missing.

Before any shared persistence, the existing automatic capture state must establish
the following. Delivery holds its existing routing/scanner lock in shared mode
through the checked send, so a completed conflicting route or disable fences later
sends; the bridge does not modify that capture state:

- capture is enabled, the exact source is enabled and not stopped/deleted;
- this exact turn was routed `business`, inside its activation window;
- its rollout is still under active Codex sessions and the source turn exists;
- transcript capture has already established the destination Thread association;
- authenticated Thread readback matches provider, namespace and source thread ID.

Personal, mixed and unknown turns never enter the durable bridge outbox or Commons.
Pre-correlation spans are held only in bounded volatile memory (32 MiB,120 seconds
since the last span for a trace). Expiry, capacity eviction and process restart may
lose spans; counters expose expiry. These volatile spans are acknowledged to the
exporter before durable admission. This is explicitly **partial capture**, not
lossless delivery or full-model observability. Long-running turns may lose early
spans before their completed correlation parent arrives. No hidden reasoning or
complete transcript claim is made. Full tool bodies remain in the linked Thread.

After admission, the existing bounded capture outbox preserves stable request
bodies and retry keys across restart. Every delivery rechecks that batch's turn;
a later permitted turn cannot unlock an earlier denied batch. HTTP410 purges and
fences that source under the existing deletion contract. Other stopped/denied
batches remain fenced for explicit reconciliation. No queue reset or backfill.
Terminal failure and outbox capacity require attention; the status endpoint and
private outbox metadata expose them without exposing transcript bodies.

## API and storage

Native spans use the existing `commons.capture/1` `runs` field:

- `kind: "opentelemetry"`, `source_run_id`: native32-hex trace ID;
- `id`: stable Commons UUID, `expected_revision`: current revision for appends;
- `trace`: array of `{resource, scope, resourceSchemaUrl?, scopeSchemaUrl?, span}`;
- `span`: OTLP JSON span with native IDs, parent, nanosecond start/end and fields;
- `input`: correlation IDs; `review`: explicit coverage, boundary and gaps;
- `status: "ended"` means the measured span ended, not that the task succeeded.

Each append is bounded by the existing1 MiB trace-array limit. The bridge uses
900,000-byte chunks. Span IDs are immutable deduplication keys; a changed existing
span conflicts. Native trace ID, owning Thread and kind cannot change. Timestamps,
IDs, status and basic OTLP structure are validated before the transaction commits.
Trace append does not replace transcript coverage. No schema migration or eleventh
table is required. Native data remains caller-supplied evidence, not verified truth.

Open a native trace under `/traces/{commons-id}` for the span tree, timing waterfall,
selected-span attributes/events/links, exact nanosecond values, coverage and linked
Thread. Missing parents and unset status are explicit. Historical records keep
their existing raw-step presentation.

`GET /api/traces/{id}/otlp` downloads an OTLP JSON `ExportTraceServiceRequest` with
`resourceSpans`, resources, scopes and saved spans. It uses the same authentication
and managed deletion boundary as trace inspection. Legacy executions without native
spans cannot be exported as OTLP. Exports group each span with its exact saved
resource/scope; grouping is not a new span or parent. Downloads are independent
copies outside managed deletion.

## Standards and verification

- [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference)
  documents trace/log exporters, endpoint/protocol/headers and scope restrictions.
- [Codex telemetry](https://learn.chatgpt.com/docs/config-file/config-advanced#observability-and-telemetry)
  describes opt-in emission, context and batching.
- [OTLP](https://opentelemetry.io/docs/specs/otlp/) defines JSON field names,
  hex IDs, numeric enums, decimal64-bit timestamps and export request shape.
- [OTel trace API](https://opentelemetry.io/docs/specs/otel/trace/api/)
  defines parentage, timing, status, events and links.

Preserve native instrumentation names and attributes rather than claiming a
complete GenAI semantic-convention mapping. The Codex tracing surface can evolve
independently of Commons. Normal Commons API/browser checks cover append, exact
export, permissions and managed deletion. Capture tests cover native admission,
late/out-of-order delivery, restart/replay, redaction and route fences. Use only
isolated synthetic data for verification.

## Browsing traces

The Traces collection uses compact table rows with source, status, duration, native
span count and source start time. Missing start times remain unavailable. It
defaults to native traces; Other executions and All activity remain available. `GET /api/traces?format=native`
(or `history` / `all`) filters before pagination and counts. Omitting the filter
keeps the API's existing all-activity behavior. Native lists include `provider`,
`thread_title` and `span_count`; legacy steps are not counted as native spans.

Native detail defaults to an agent view: turn roots, model calls, named tool
executions and reported errors. Internal transport, filesystem and bookkeeping
spans are hidden until **Show internal spans** is enabled. Displayed descendants
retain their order and nesting through hidden ancestors; source parent IDs and
raw/exported spans are unchanged. Usage-bearing model records take precedence over
generic transport wrappers, including wrappers exported as siblings. Codex
`handle_responses` usage records are labelled Model response; their duration
measures response processing, not the full model request latency, and tool observations/broker wrappers are not counted
as additional executions merely because they carry a tool name.

The compact summary shows the reported model and input/output/cached-input tokens.
Reported turn usage takes precedence over child usage; totals never add both.
Without a single root usage record, the fallback sums disjoint leaf model-usage
spans. A missing field remains unavailable if any selected call omits it; zero
remains zero. Cached input and reasoning output are subsets, not extra tokens.
Per-call usage appears in the tree and selected-span Overview. Explicit recorded
input/output values are displayed when present; missing bodies are not invented.

The tree and relative timing waterfall sit alongside a selected-span inspector.
Expand/collapse, ancestor-preserving search within the current view, Overview,
Attributes, Events and Raw tabs preserve the supplied graph and content. The
source Thread link leads to available messages and tool bodies; missing model
inputs are not reconstructed. Timing bars show measured source start/end, and
unknown status remains unknown. The first host bridge delivers completed turns;
it does not stream unfinished spans into the UI while a turn is still running.

The audit view keeps one compact trace summary; trace identity remains in the
breadcrumb. Generic Span badges, repeated duration/title text, boilerplate and
empty inspector tabs are omitted. Raw retains each complete original span with
IDs/exact timing/resource/scope/events/links; Trace details retains source
correlation and coverage/gaps. Source thread and standard OTLP export remain
available. Older executions omit empty Input/Result/Review/consulted sections.
