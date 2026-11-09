# Search and retrieval

This describes **schema12 candidate source**, not deployment or a new benchmark.
Objects and original Artifacts are authoritative; `chunks` is a derived index.
External agents reason; Commons supplies matching and explicit deeper reads.

## What is searched

The Threads screen searches stored visible content and opens exact matching windows. Other UI collection searches match titles/descriptions lexically. `commons_search`
uses the separate authenticated `GET /api/retrieve` endpoint:

| Scope | Content |
| --- | --- |
| `objects` (default) | Atomic Object title, description and body; Thread metadata and stored visible bodies |
| `threads` | Captured Thread metadata and visible message/tool/log bodies, including current message corrections |
| `artifacts` | Eligible current evidence or its current correction representation |
| `all` | Both scopes |

`kind` filters a seven-kind Object type; `object_id` scopes an owning Object before
ranking. The `threads` scope narrows eligibility before readiness calculations; unrelated Source evidence does not contribute to its pending, failed or incomplete-Artifact counts. Managed captured copies, deleted/historical-only records,
superseded/ineligible evidence, credentials and historical change payloads are
excluded. Native OpenTelemetry span attributes/events and execution headers are not conversation bodies and remain excluded. Retained evidence/history can still be read deliberately.

Incomplete Source captures remain excluded from Artifact search, even when some text is stored. This preserves the complete-original evidence contract; it is not a claim that no text was captured. Read the Source’s Artifacts deliberately. `index.excluded_incomplete_artifacts` reports these exclusions separately from pending/failed indexing; `excluded_native_trace_items` reports excluded native telemetry. Counts follow the requested kind/Object filters. Thread capture coverage may be partial: matching stored visible text does not imply a complete transcript.

Each ordinary Object has **one vector**, not one per field or multiple Object chunks.
Its exact formatted title+description+body must fit 500 tokens, including formatting
and special tokens. Title/description keyword priority does not exclude semantic
body matching. See [the knowledge model](schema.md).

Long Artifacts and Thread conversation projections are chunked. Current source starts with up to 1,000 Unicode
characters, shrinks until formatted input fits 500 tokens, and overlaps up to 100
characters (at most a tenth of that window). There is no old 512-passage cap or
generation/job table. Originals are not rewritten to fit embedding input. Empty
text is distinct from failed extraction/embedding.

<a id="api-and-bounds"></a>

## Search, then read

```json
{"query":"fictional workshop access checklist","scope":"objects","limit":5,"neighbours":3}
```

Queries are nonblank, at most 500 UTF-8 bytes. `limit` counts 1–10 direct matches;
`neighbours` permits 0–5 additional connected Objects. `budget` is 2,000–24,000
UTF-8 context bytes, excluding envelope. Bounded existing Connections/explanations
are labelled separately from direct matches.

Results contain compact IDs, kind, title, description, revision and read references,
not full bodies/documents. Search `artifacts` for evidence-only terms, optionally
under `object_id`; follow `match.read`, field and locator with `commons_read`.
Corrected windows address the correction; Artifact offsets are Unicode characters.
Follow `next_offset` rather than assuming the first window is complete.

Thread matches return `match.read` with `resource=thread_text`, the owning Thread ID, `expected_revision`, `offset` and `limit`. `GET /api/threads/{id}/text` reads that exact Unicode window of the current title/description followed by ordered visible bodies separated by newlines. A stale revision returns 409: repeat search. This projection includes current explicit message correction text; original items remain deliberately readable via the Thread reader. It excludes arbitrary payload JSON, model metadata and native spans. Lexical windows are at most 32,000 characters; semantic windows use the same bounded token packets as long Artifacts.

Ranking combines English full-text keyword matches and cosine semantic matches
through reciprocal-rank fusion; exact IDs/titles receive priority. Read supporting
evidence: neighbours are not verified answers and a miss is not proof of absence.

Inspect `mode`, `reason`, `index`, `truncated`. Missing/unavailable model or
incomplete/rebuilding index gives explicit keyword-only degradation. An unconfigured
model reports `lexical_only` / `model_not_configured`. Health alone proves neither
complete embeddings nor useful retrieval.

## Model and operations

One configured model is supported: pinned local Ollama 0.40.5 with
`embeddinggemma-2:270m-q8_0-text`, 768-dimensional normalised vectors and pgvector
cosine distance. Clients cannot select arbitrary models/providers per query. This
is embedding, not bundled reasoning. Exact pins/input rules are in
`src/retrieval.rs`, `src/packet.rs`, provisioning source and the
[schema contract](atomic-schema.md). See [notices](../THIRD_PARTY_NOTICES.md).

Follow [Compose provisioning](installation-lifecycle.md#first-empty-installation).
For native Linux development use the pinned runtime/cache with
`scripts/provision-model`, then configure server `COMMONS_OLLAMA_URL` for the
approved loopback service. Compose uses private `http://ollama:11434`. An unset
URL explicitly disables semantic indexing; keyword retrieval and writes remain
available. Do not expose Ollama or substitute an unreviewed model to bypass errors.

Read `/api/retrieval/status` (`commons_read`, `resource: "index"`) for configured
model, space and chunk state. An authorised administrator session can POST `{}`
to `/api/retrieval/rebuild`; it resets derived work and reports rebuilding/keyword-only
state. It neither changes canonical knowledge nor migrates storage. There is no
prior active-generation availability guarantee in this candidate.

Chunks carry current input hash/space, Object revision, claim and retry state.
Reconciliation removes stale entries/resumes work; publication rechecks current
eligibility/hash and claim. Eight failed attempts leave visible failure; correct
the cause before rebuilding. A rebuild cannot recover missing original evidence
or silently repair canonical content.

## Verification boundary

[Testing](testing.md) names foundational and separate real-model commands. Old
Issue #8 measurements and prepared-host reports describe the earlier schema/index;
their recall, latency, passage counts and rollback results are not schema10 evidence.

Model-free candidate API/tool checks establish declared keyword degradation, not
semantic quality. Real-model correctness/quality/resources, final packaged tool
integration, business adaptation and installation walkthroughs need their exact
candidate/environment. This documentation update checks links/source consistency only.

Schema 12 discovers captured-body keyword candidates through a transactional GIN
lexeme index. Keyword matching combines Thread title/description with windows of
individual visible message, tool or log bodies; it does not combine separate items
into one keyword passage. Current corrections replace original bodies at query
time. Exact result offsets still address the ordered full Thread projection,
including empty items and Unicode characters. Keyword discovery does not wait for
semantic embeddings; semantic coverage is reported separately.
