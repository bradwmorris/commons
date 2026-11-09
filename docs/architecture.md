# Commons v1: organisation-owned Context and shared capabilities

**Schema10 candidate:** use [the exact ten-table contract](atomic-schema.md),
[adopter knowledge model](schema.md), [retrieval](retrieval.md) and
[MCP reference](connect/mcp.md) for current shapes. The detailed staged design
below is historical pre-schema10 material; its old tables, User/Memory/Chat kinds,
archive/protection, generation indexing and comparison assumptions are superseded.
It is not a current implementation/acceptance checklist. Full architecture
consolidation follows the verified candidate; [feature status](feature-status.md)
keeps earlier evidence distinct from current acceptance.**

Implementation Issue #1 · [Requirements](requirements.md)

## Architecture

Install **Rust API + React Context UI + PostgreSQL**, with external agents supplying reasoning in their own environments. Issue #8 adds a private local EmbeddingGemma 2 text-only service and pgvector for hybrid retrieval. Keep durable business records, relationships, provenance/history, authenticated identities/permissions and a real shared-capabilities layer. The product does not host agent sessions, generative inference or model-driven memory maintenance.

The organisation owns an embedding-only service, not a reasoning model, harness lifecycle, token stream, agent sandbox or provider billing integration. There is no prompt-to-agent chat panel in Commons v1; Chat records and submitted transcripts are records, not a hosted assistant. The earlier blanket model-free/no-embeddings decision is superseded only for local retrieval. The UI collection search remains lexical metadata search. The separate authenticated retrieval API searches evidence and semantic candidates with explicit degraded modes; see [retrieval](retrieval.md).

This document describes the design contract. [Feature status](feature-status.md)
distinguishes delivered behavior from planned capabilities. New Tasks require a
`due_at`; imported Tasks may retain a missing date only with validated import
provenance. GitHub Issue links are optional. External Issue/Task pairing does not
impose a planning process on product contributors or launch an agent.

### Rich-record storage and capture ownership

The [schema](schema.md) defines canonical Objects, evidence and history.
`artifacts` retains nullable text and immutable versions; `artifact_binary_payloads`
retains original PNG/JPEG bytes in PostgreSQL. Record history and evidence
corrections retain supplied historical assertions separately from authenticated
audit events. Historical User Objects grant no accounts or credentials.

#9 extends these canonical tables with `capture_sources`, `chat_messages` and `runs`,
plus source receipts and registered raw-copy lineage; no second content/history store.
Artifact reads and references require authentication within the installation;
shared IDs are not access grants. All authenticated users/agents can read conversations.
Unknown import shapes reject atomically. The [capture contract](connect/capture.md)
defines explicit delivery, correction targets, original provenance and deletion.
Historical missing Run targets must remain explicit supplied references with purge
evidence where available, not fabricated Objects or permissive ordinary writes.
Deletion takes an exclusive transaction advisory lock while apply/capture take its
shared form, so cleanup waits for admitted writes and fences late imports/corrections.
Raw Chats and registered excerpts stay out of general retrieval. The host SQLite
outbox is transient transport, not canonical storage or backup. Opt-in Codex/Amp adapters have separate real-client evidence and coverage limits
in [feature status](feature-status.md#automatic-capture-implemented-with-explicit-limits).

External extraction tools supply Source/Artifact bytes through the
[normal API](foundation-api.md#source-and-artifact-ingestion). No new URL/PDF/video
extractor or workflow engine is part of #11. All canonical rich data is covered by
a whole-PG snapshot; referenced external originals are not. Historical restoration
can revive old content/access and is not a conversation-deletion guarantee.

## Where the database and Rust API live

```diagram
┌──────────────────────┐        ┌────────────────────────┐
│ Context UI / browser │        │ External Amp / Codex   │
│ Named user session   │        │ Own models and runtime │
└──────────┬───────────┘        └───────────┬────────────┘
           │                               │ scoped token / MCP or HTTP
           └──────────────┬────────────────┘
                          ▼
┌────────────────────────────────────────────────────────┐
│ Commons: Rust API + built React UI                      │
│ Context • identities • catalog • fixed operations       │
│ Small deterministic job worker (same Rust executable)   │
└──────────────┬─────────────────────────────┬────────────┘
               ▼                             ▼
┌──────────────────────────┐   ┌─────────────────────────┐
│ PostgreSQL + pgvector    │   │ Private local Ollama    │
│ Persistent org storage   │   │ EmbeddingGemma 2        │
│ Records + derived index │   │ Text-only retrieval     │
└──────────────────────────┘   └─────────────────────────┘
```

**Confirmed initial baseline: one organisation per Docker Compose installation with organisation-shared records, local login and basic authorization on a trusted host.** Confidential team partitions and company SSO are not launch requirements; authentication, scoped agent credentials and admin/member/reader checks remain required. The `app` serves the UI/API and a bounded in-process Rust job loop; `db` is PostgreSQL on a private Compose network with a persistent named volume. The browser and external agents never connect to PostgreSQL. The database is not in an agent workspace, the browser, Amp or a transient Orb. A separately configured managed PostgreSQL is an operator alternative, subject to TLS, version and role checks; ownership need not mean physically self-hosting every component. Durable storage/restart persistence and #7's explicit operator snapshots are distinct; neither promises deletion-safe historical recovery.

Use one logical database with distinct canonical, capability and operational tables; no second execution database, Redis, separate vector database, graph database, Python workflow host, Pi/Node server runtime or Kubernetes requirement. Node remains a **frontend build** dependency. Retrieval adds pgvector to PostgreSQL and an Ollama embedding service on the private network; see [operations and evidence](retrieval.md). Preserve canonical IDs/contracts where retained, but version the Commons contract for changed permissions and policies; do not advertise drop-in Context 1.2 compatibility.

Only the app is exposed through the documented HTTPS/reverse-proxy boundary. DB ports remain private. The trusted app role can mutate canonical state; a separate migration role owns schema changes. Run fixed handlers under an explicit initiating principal and restricted service identity, using the same authorization/domain transaction path as API requests—not unrestricted SQL written by workflows. A later worker process split may reuse this executable if measured load demands it; it is not a v1 architectural prerequisite.

### Local retrieval build (Issue #8)

The Rust API/worker calls Ollama running **EmbeddingGemma 2, text-only 270M**; vectors live beside canonical records in PostgreSQL/pgvector. Optional allowlisted service adapters such as GitHub issue reads remain separate. The [retrieval contract](retrieval.md) pins runtime/model artifacts, dimensions, prompts, chunking and bounded defaults. Provisioning downloads weights (or uses pre-provisioned artifacts); normal indexing/querying needs no external egress or model API keys. Never expose the embedding endpoint to browsers or external agents.

Semantic and lexical matches select Objects, then bounded existing Connections return context with explanations and evidence references. Object titles/descriptions, Note content, Task briefs and Artifact passages retain parent IDs and source revisions. The bounded high-degree organisation map does not restrict query search. Exact scan and English keyword stemming are current limits, not a large-store capacity claim. Resource and retrieval results are synthetic measurements, not guesses from model size.

Canonical records remain authoritative; embeddings are replaceable derived data. Admit indexing work with accepted source mutations, fence stale results by source revision and deletion state, and recover bounded work after restart. A failed model request cannot invalidate a committed record or make stale vectors appear current. Expose pending/failure and lexical-only states. Rebuild into a separate generation and switch only when validated, accounting for concurrent changes; never mix model spaces or resurrect deleted content via late jobs or rollback. Model changes can require re-embedding but must not rewrite Object IDs, evidence, audit or Connections.

No chat generation, inferred relationships, internal curation, hosted fallback, reranker or multimodal ingestion is part of this build. This index lifecycle is not completion of the separately planned conversation-deletion feature. See [retrieval requirements](requirements.md#retrieval-with-local-embeddings) for agent guidance and acceptance.

## Identity, permissions and data leaving Commons

Use organisation-shared records, local login and basic admin/member/reader authorization for v1. Bootstrap one administrator with a one-time secret; browser sessions use secure cookies, CSRF protection and server-bound active Users. Admin provisions/disables users and integrations, with a documented local login reset path. Members edit supported records; readers cannot mutate, run effectful capabilities or submit progress. User/role administration is not exposed through ordinary `context_apply` despite inherited generic User operations. Keep auth secrets out of canonical User snapshots/history. Simple installation does not mean unauthenticated access.

An agent credential is hashed at rest and bound to its issuing human or explicit service account, client identity, scopes, expiry and revocation. Store initiating human, acting agent/service and optional conversation/external-run correlation separately. Headers/body fields are correlation, not authority. Requested human attribution is unverified unless supplied by a trusted authenticated mapping; a tool reporting an action is not proof that a human said it or that an external side effect occurred.

Proposed scopes: Context read; permitted-kind write (including Memory when granted); source intake; capability read/invoke by handler; own external-attempt reporting; transcript submission. Capability/service/identity administration remains separate. Delegation cannot exceed the user's role; deactivation/revocation blocks invocation, results and replay. Check authority at the common domain boundary and hold/recheck it through commit, including queued effects. Artifact writes and corrections inherit parent authorization; relationship changes require authorized endpoints and effects, including evidence links. HTTP, MCP and fixed handlers cannot bypass this path. Audit refusals without logging secrets.

Returned Context data is visible to the connected external agent and potentially its own model provider. Commons cannot control that environment, guarantee its reasoning privacy, enforce its tool use, or cancel its computation. Explain this in onboarding and let admins restrict available tools/data. Organisation-shared records do not imply tokens/secrets are shared records. Service credentials live in operator secret storage referenced by opaque integration IDs, never in capability documents, model keys or client tool results. Private GitHub access may need a read-only repository token; local auth, DB and TLS credentials remain necessary even with zero model keys.

## Shared capabilities: definitions plus actual implementations

Use one versioned capability content model, not separate skill/process/workflow engines. Store organisation-authored instructions and structured procedure steps with stable ID, owner, publication status, linked evidence and executor (`external_agent` or `server_operation`). Code-owned registered handlers define callable input/output schemas, permissions and implementation versions; documents cannot override those contracts or register code. Attempts pin the published content/handler revision. A changed definition cannot silently change an in-flight attempt. Retired/missing implementations are visibly unavailable. Skills are instructions/data, not trusted executable plugins; no dependency scheduler is implied.

API and UI support list/read/edit/publish/history for authorized users; external clients read approved versions. Use operational/capability tables linked to canonical records rather than inventing arbitrary new Object kinds. A supported adapter exports portable Markdown skills/procedures; an agent fetches/pins a version explicitly—no claim all harnesses automatically install it. A compatibility manifest and onboarding example state which MCP transport/client version was actually tested. Use a thin MCP tool surface over the Rust HTTP/domain contract; ordinary authenticated HTTP remains usable by clients without MCP. MCP does not supply an agent loop.

| Shipped capability (proposed) | Executor and real implementation | Boundaries |
| --- | --- | --- |
| `context.search/read/apply` | Rust domain/API handlers, exposed through authenticated HTTP and MCP | Scoped record writes including authorized Memory create/update/connect, atomic receipts/revisions; no identity override, direct SQL or shell. |
| `source.capture_text` | Fixed Rust intake handler validates a supplied UTF-8 capture manifest, commits Source+artifact+provenance and returns IDs/readiness | Bounded bytes, exact SHA-256 and completeness; source identity/revision conflicts. It does not fetch arbitrary URLs, summarise, infer links or transcribe. A URI is provenance, not permission to fetch. |
| `github.issue_read` | New fixed read-only GitHub API adapter: configured repository ID + issue number → bounded issue title/body/URL/state and observed timestamp | Configured host/repository allowlist; no caller-supplied endpoint/credential, arbitrary proxy, comments/write scope or recursive traversal. Strict timeout/size/rate limits; no redirects outside approved host. Optional integration is disabled until configured. Returned text remains untrusted content. |
| `source_intake` shared workflow and skill | External agent reads pinned steps: obtain supplied capture or call issue adapter → commit source → read back → optionally write its own evidence-linked Note/explicit Event → report progress | Reasoning, relevance decisions and any summaries happen outside Commons. Server validates allowed fields/evidence references, not semantic truth. Optional Note failure does not roll back a saved Source. |
| Selective Memory skill | Versioned external-agent instructions using ordinary supported Context handlers, not a new proposal engine | Search first; update/link when useful or create otherwise, with useful references and uncertainty. No per-change human approval, automatic curation, global deduplication or write quota. |

The GitHub adapter is a recommended bounded first service integration, not a finding that a reusable public adapter already exists. Implement it in Commons; inspect official API/version/permissions at its implementation stage. Acceptance needs a real read against an explicitly approved synthetic fixture repository, plus controlled local failure tests. That is not permission to post or change anything in GitHub. Other adapters require an implementation, threat/credential review and contract tests; storing their names does not make them callable.

## Memory write contract: authorized external writes

Authorized agents write Memories through the same validated API as other records.
There is no separate proposal table, promotion token or per-change review queue.

1. An authorized external agent creates, updates and connects Memories using ordinary authenticated Context API/tools. Scope, role, target revision and referenced-record permissions are validated in the same transaction boundary as other writes; agents never access tables directly. No per-change human approval or model-produced preview is needed.
2. Cover all effects: artifact append/update, correction and relationship endpoints cannot provide an alternate write path for a reader or agent lacking the relevant Memory permission. Existing protection/data-integrity rules remain explicit server rules, not caller flags that grant authority. Rejected or stale batches have no partial effects; two competing updates cannot silently overwrite each other.
3. Server-generated Object Events record the accepted write, authenticated actor, server time and revisions atomically with the record/Run/receipt. Agent-authored real-world Event Objects or Memory claims are attributed supplied content, not proof an event occurred. Clients cannot insert/alter audit identities, timestamps or claimed server observations. Keep credentials out of User snapshots.
4. Guidance encourages search first, then update/link existing records when useful or create otherwise. Preserve useful source references/history and uncertainty in existing fields; no new mandatory rationale schema is implied. A durable policy may be worth saving, whereas “capture finished” usually belongs in progress/audit. Zero writes is valid; duplicates are acceptable. No global merge/deduplication engine, save-everything instruction or per-interaction prompt.
5. If evidence changes, authorized external agents can inspect references/history and update the Memory using expected revisions. Commons does not infer new truth or automatically rewrite/retract it. **Optional recommendation, not a confirmed requirement:** a small deterministic changed/missing-evidence indicator if existing revision references support it cheaply. No stale-evidence subsystem is a launch gate.

UI reads show saved Memories, attribution, references, history and ordinary conflict/permission states—not a pending human-promotion queue. This full v1 contract extends beyond the implemented foundation: see [feature status](feature-status.md) and milestone evidence, rather than treating every design paragraph as delivered functionality.

## Request receipts and minimal origin metadata

Bind receipts to authenticated principal + operation namespace + request key, with payload hash. Atomically store the accepted mutation/result receipt, including concurrent sync/job calls; equal requests from that principal return the committed result, changed payloads conflict. Check current authorization before disclosure/replay. Subsequent record edits do not rerun an old accepted write. If deletion removed result payload, return deletion status, never deleted text or a new write.

Source identity is a separate policy: two callers' identical request keys never collide, inherit receipts or attribution. Where an explicit Source identity calls for canonical reuse, keep that behavior while issuing independent caller receipts. Occasional duplicate records under different requests are acceptable. Do not build global exactly-once orchestration. Context intake needs adaptation: `source_intake.rs:135–139,436` assumes a configured principal/raw batch key, and `intake.rs:1082–1090,1478–1496` derives IDs/receipts from batch alone; the generic replay path is not proof that this intake path is safe unchanged.

A hash validates supplied bytes, not remote authenticity. Caller-supplied capture is labelled caller-attested even with a GitHub URL and valid recomputed hash. A deterministic server adapter can fetch data without any internal agent/model; only its recorded response bytes, resource and observation time are server-fetched. Preserve that minimal binding when recording its result as a Source; agent-edited returned text is a new caller-supplied capture, not the original server observation. Do not introduce a signature service, general authenticity engine or completeness guarantee.

## Minimal jobs, progress, retries and disconnect behavior

Recommend a **small PostgreSQL job table and Rust polling worker**, without a general orchestration engine. Jobs accept only registered deterministic handler IDs with pinned versions, scoped input, initiating identity, idempotency key/hash, state, attempt, lease generation/deadline, next retry, result IDs and bounded error metadata. Atomic admission and terminal writes; `SKIP LOCKED` claim; fenced commits reject stale attempts. A handler version must remain available for existing jobs or mark them blocked after an upgrade.

| Work | Needed in v1? | Recovery/limits |
| --- | --- | --- |
| Bounded source intake / configured issue fetch | **Yes**, durable admission/results for work that outlives an HTTP request; small synchronous operations can use the same contracts directly | Exponential backoff with jitter, handler-specific attempt/time cap; retry reads/typed transient failures. Intake uses canonical idempotency/reconciliation after lost response. Validation/auth errors are terminal, not retried. |
| Job lease reclaim and external-attempt expiry | **Yes**, small periodic DB housekeeping | Resume safe registered jobs with a new lease generation; external attempts become stalled, never relaunched. Avoid a second scheduler service. |
| Search indexing | **Yes**, full-text plus local embedding indexing under Issue #8 | Derived vectors with source revision/deletion fencing, bounded durable recovery and explicit safe rebuild. Model failure leaves writes intact and search visibly degraded. |
| Token expiry and explicit deletion cleanup | **Yes for expiry enforcement and deletion completion** | Enforce expiry on every access. Conversations do not expire automatically; explicit deletion removes tracked raw copies and fences work. No inferred deletion of knowledge or intelligent maintenance. |
| Cron/scheduled business workflows or agent starts | **Deferred** | No v1 dispatcher/wakeup guarantee. External schedulers may call authorized operations later, but are not supplied by Commons. |
| Summaries, Event extraction, synthesis/dreaming | **Excluded from v1** | No jobs queued waiting for a generative model key; no automatic retries via a subscription broker. |

Server operation state: queued → running → succeeded / failed / needs-reconciliation / cancelled; retry-wait is visible and bounded. Cancellation prevents unstarted effects and fences further commits; it does not undo an already committed record or prove an in-flight upstream request was cancelled. Expose partial result IDs. Unknown external side effects require reconciliation, never an exactly-once promise. The proposed v1 adapter is read-only; do not generalize its safe retries to future write adapters.

For external procedures, record a **reporting attempt**, not a server execution: pinned definition/input reference, initiating user/client, claim token/generation, last report/expiry, per-step reported status, evidence/result IDs and monotonic event cursor. States include claimed/running, waiting-for-human, stalled, interrupted, completed, failed and cancelled. A separate heartbeat daemon is not required; ordinary reports may refresh inactivity expiry. Reports carry stable IDs and deduplicate; only the bound principal and current generation may report. Label agent-reported success separately from server-confirmed writes/readiness.

If an agent disconnects, completed canonical writes and progress remain; admitted independent server jobs may finish under still-valid authority. Commons does not infer the disconnect immediately, resume reasoning, start a replacement agent or finish remaining procedure steps. Lease expiry marks the reporting attempt stalled. Reconnect must explicitly reclaim (new generation) and inspect committed results; a human/authorized client may abandon it and start a linked new attempt. Old generations are fenced from progress and attempt-bound mutations. Independent authorized writes by an agent are still possible and audited, but are not silently attributed as results of a cancelled/stalled workflow. Unknown external effects require operator/agent reconciliation. Explicit long human-wait states have configured expiry and do not consume a running job slot.

## Capture, interpretation and explicit records are separate

Keep deterministic mutation audit automatically. Explicit transcript submission is opt-in, disabled until the organisation-shared visibility and deletion boundary are disclosed and the submitter confirms supported scope. Retain submitted conversations until explicit deletion, not automatic age expiry. Accept only the documented bounded message-envelope format (source/session/message IDs, sender mapping, source/recording timestamps, redaction/completeness flags); refuse cross-user attribution and protect retries. Human sender claims from untrusted imports stay unverified. Missing/truncated/redacted coverage is visible. Store readable transcript data, not inferred facts or hidden reasoning.

No native Amp/Codex hook capture is a launch claim. A later connector must prove consent, routing, credentials, runtime version and gaps separately. External agents can explicitly save a Note or Event with source evidence and uncertainty through allowed interfaces. A deterministic audit entry such as “source committed” is not automatic interpretation of a conversation or proof of every action the agent took elsewhere. No generated chat-summary column silently fills; unsupported UI actions are removed/labelled.

## Conversation deletion contract

**Delete is not archive/hide.** Before confirmation, show that deletion removes the submitted conversation and Commons-managed raw copies, while separately saved knowledge may remain. Retain conversations until this explicit action. Use existing permissions and a bounded deletion path, not the reference fixture-purge engine or a general retention platform.

- Record a payload-free tombstone for the source/session/message identities and make raw content inaccessible immediately. Remove messages, raw artifacts, tracked copied excerpts and payload snapshots from active Context/history/Run surfaces, search indexes, receipts and job input/results. Preserve only non-content audit facts/IDs/deletion status; do not embed the old text in a deletion event, log or error. Required deletion work persists across restart and reports completion or failure honestly.
- Cancel/fence pending work using that raw content. A late job, lost-response replay, history read or repeated submission under the deleted capture identity must not resurrect it. The common mutation path checks deletion state through commit. Use linked payload references rather than making untracked copies; each supported copying operation must register its lineage so cleanup covers it. Logs never store raw transcripts by default.
- A separately saved Memory/Note/explicit Event may remain as independent knowledge, with source-deleted lineage visible. This exception is **not** a loophole to keep managed raw quotations: tracked verbatim excerpts are removed/redacted even within saved records/history; independently authored knowledge remains. Do not silently delete all derived knowledge or promise semantic discovery of every manually retyped quote. Similarity search does not reliably identify all unlabelled paraphrases or independently reintroduced text; disclose this limit and support explicit deletion of remaining records separately. Derived evidence chunks/vectors and pending indexing work are included in managed-copy cleanup.
- No promise to erase data already downloaded to an external agent, user export or operator-managed copy, nor physical forensic erasure of PostgreSQL storage/WAL. #7's explicit historical snapshot restoration can reintroduce deleted data and formerly valid credentials. It requires isolated operator review, never automatic client replay, and is not deletion-safe recovery. No backup service/UI or restored-authority machinery is introduced.

Acceptance uses a unique synthetic raw marker through every documented managed copy (including correction history, receipts and queued results), deletes it, restarts, retries/reports from old clients and queries UI/API/search/history. The raw marker stays absent; payload-free audit survives and independently authored saved knowledge has honest deleted-source lineage. This is future application acceptance, not deletion of any existing deployed data.

## End-to-end onboarding and shared-capability demonstration

1. Operator installs a separate empty stack, provisions the pinned local embedding model, initializes DB through explicit migration command and bootstraps admin. No agent harness, hosted provider choice or inference keys. Admin creates synthetic Alice and Bob, configures a read-only fixture GitHub repository integration if using the adapter, and publishes the example procedure/skill.
2. Alice opens Context, issues a scoped client credential including Memory write when appropriate, and follows the tested Amp onboarding example (endpoint, secret reference, contract preflight). Read selective search-first guidance: update/link when useful or create otherwise; no save-everything or per-interaction prompts. The external Amp environment already supplies its own model access; Commons does not provision it. Verify ordinary HTTP independently. Codex compatibility is claimed only after its own client test, not from an Amp pass.
3. Amp lists/reads the published `source_intake` revision and required scopes; a reader credential cannot invoke intake. It calls the actual `github.issue_read` with fixture repository ID/issue number. The adapter records its fetched bytes/origin; a subsequent Source capture retains that binding only for the actual fetched bytes. Agent-edited text is caller-supplied. Alternative supplied text works without any service credential/network.
4. Amp opens an externally executed reporting attempt, calls `source.capture_text` with a stable caller-scoped key, polls the durable result and reads the Source/artifact back. It optionally analyses externally and saves its own evidence-linked Note or Memory through authorized apply. UI shows source, relationships, human/agent/service attribution, Runs, hashes and progress, not a claim that Commons reasoned or verified truth.
5. Kill/restart Commons after source commit but before client acknowledgement: same key returns the same IDs and no duplicate Source. Stop the external agent after that step: UI later shows stalled, not completed or automatically resumed. A lost optional Note leaves the Source intact. Reclaim explicitly and finish/report or abandon with a reason.
6. A second independent external task retrieves query-relevant context using hybrid search, follows relationships and reads evidence to reuse saved knowledge and capabilities. Use the implemented hybrid API for paraphrase and evidence-only retrieval; publish misses and degraded-index behavior honestly. UI metadata search alone still misses these cases.
7. Amp searches existing Memories, directly saves/updates/connects useful lasting knowledge through its authorized API credential, and retrieves it immediately with references/history—no human-promotion step. Race two updates; one stale revision fails without overwriting the winner. Bob with a reader/unscoped token cannot mutate Memory through apply, artifact, correction or relationship paths. Contrast routine transient work with zero Memory writes. Correct source evidence, let the external agent update with the new Memory revision, and inspect the preserved lineage; no internal automatic rewrite or mandatory warning subsystem.
8. Separately consent to a supported synthetic transcript, retain it through restart, then explicitly delete it. Verify the deletion contract across active copies/history/receipts/jobs and repeated same-identity submission. Independently saved knowledge remains only within the disclosed boundary.

## Licence

New Commons code uses Apache-2.0. Preserve the applicable upstream licences and
[third-party notices](../THIRD_PARTY_NOTICES.md). Software licensing does not
change ownership or disclosure permissions for installation data and credentials.

## Implementation acceptance

The stages below describe acceptance targets, not an agent assignment or proof
of delivery. Use current Issues and feature status to establish remaining work.

| Stage / dependency | Deliverable | Concrete exit checks |
| --- | --- | --- |
| **S9 — independent install foundation** | Selective Rust/React/Postgres port, locks, explicit migrations, Compose, executable Orb setup/resume/services | Fresh Orb without sibling checkouts installs/builds from pinned deps. Guard disposable DB targets. Resume twice preserves sentinel data. Fresh Compose on a verified Docker-capable host boots empty Context with no model keys or agent runtime; Issue #8 extends this with pgvector and pinned local embeddings. Ordinary startup never runs unreviewed migrations. |
| **S10 — Context + identity + external client**, S9 | UI, authenticated HTTP/MCP, scopes and transactional writes including Memory | Actual Amp + synthetic Alice/Bob: authorized Memory create/update/connect immediately visible with identities/references/history and no human promotion. Deny reader/unscoped/revoked writes, header/User/audit spoofing and artifact/correction/relationship bypasses across HTTP/MCP/fixed handlers. Concurrent edits reject stale revision; failed batch has no partial effects. Equal key/body replays after subsequent record edits without a second mutation; changed body conflicts and revoked access fails. Exercise local login reset/disable and safe untrusted Markdown. Task fields round-trip under the current Task contract. Restart and reuse saved records. |
| **S11 — implemented shared capabilities + progress/jobs**, S10 | One versioned capability content model, intake, actual read-only GitHub adapter, bounded jobs and external reporting | Complete the actual onboarding/fixture-service read. Reject arbitrary endpoints/code, unimplemented IDs, corrupt/oversize manifests and credential override. Race Alice/Bob with the same key: independent receipts/attribution, canonical Source identity separate. Race sync/job retries for one caller: one receipt/mutation. Inject 429/timeout, DB failure, commit-before-ack, lease expiry and competing workers; check bounded retry/fencing/results. Revoke before dispatch/commit and deny. Disconnect/reclaim agents: stale generation/other client cannot report; no automatic reasoning resume. Pinned versions remain pinned. Alter fetched text and recompute hash: it cannot inherit server-fetched origin. |
| **S12 — retrieval + selective Memory + explicit capture/deletion**, S10; job cases after S11 | Hybrid/graph evaluation under Issue #8, search-first guidance, consented transcripts and deletion contract | Independently labelled queries cover semantic paraphrases, exact terms and evidence-only facts against the lexical baseline, with explicit ranking/recall denominators, context budgets, misses and ambiguous/no-answer controls. Set quality/performance targets before tuning; zero denied disclosures. Demonstrate useful direct Memory writes versus routine zero-write work; external agent updates after evidence correction using expected revisions, no internal rewrite or mandatory warning. Consent off stores nothing; visible shared-org/sender/completeness limits. Retain until deletion; unique raw marker disappears across all managed copies/indexes/history/jobs/receipts and stays absent after restart/retry/late job/repeated same-identity import. Independently saved knowledge retains deleted-source lineage. No automatic interpretation. Inspect default/empty/error/conflict/deleted/stalled/narrow UI states and interaction clips. |
| **S13 — installable product acceptance**, S11 + S12 | Distribution docs, security audit, clean second install, update/compatible rollback checks | Only the pinned local retrieval model is allowed; no hosted provider, broker, generative model or agent runtime. After model provisioning, deny external egress and execute Context CRUD/search/graph, supplied intake, progress/restart persistence, transcript deletion and authorized Memory writes. Test local model outage and allowlisted adapter egress separately. Repeat full onboarding on a fresh install; measure CPU/RAM/latency/indexing and model replacement. Rehearse update and compatible-image rollback using synthetic data, preserving deletion tombstones/persistence; no incompatible-schema rollback or backup/restore guarantee. Check secret redaction/rotation; required disposable DB tests run, not skip. Real UI/API evidence, not a mockup; no publication implied. |

Tests must distinguish plausible mistakes: authorized versus unscoped agent, Alice versus Bob, equal versus changed replay body, stale versus current record revision, caller-supplied versus adapter-fetched bytes, raw copy versus independently saved knowledge, crash before versus after commit, active versus expired lease, metadata versus body-only text. Derive expected IDs/hashes independently; no model grading or mock call counts in place of real evidence. Deliver an early thin intake → later retrieval → authorized Memory write slice, then complete the retained scope; do not defer essential permissions to a final hardening phase.

## Orb, installation and operating plan

Pin Rust supporting edition 2024, frontend dependencies/package-manager versions and the database version per supported installation lane. The foundation pins Rust 1.90.0, uses native PostgreSQL 15 and records Node/npm/browser versions in verification; PostgreSQL 16/Compose has a separate [prepared-host rehearsal](installation-lifecycle.md), not interchangeable storage or clean-host/full-lifecycle acceptance. Node is build tooling, not an agent worker. No Python application host or Absurd; Python is used only for development verification. Issue #8 adds pgvector and the pinned local embedding runtime, with new installation evidence required. `.agents/setup` installs/checks tools and locked dependencies and builds assets; `scripts/dev-init` explicitly initializes guarded synthetic storage/migrations after database startup. `.agents/resume` only checks build presence, without installs, migrations, resets or credential rotation. Supervised services/readiness live in `.amp/services.yaml`; expose only development UI/API previews through Orb portals. See [getting started](getting-started.md) for the literal tested order.

Do not assume a Docker CLI proves an Orb has a usable daemon. Check capability during S9; native PostgreSQL is an acceptable Orb development fallback, not a substitute for testing the actual Compose installation on a Docker-capable host. A fresh Orb must work without reference repositories. Amp/Orbs are development tools; adopters can run the documented standalone stack without Amp.

Installation docs must cover generated secrets, DB volume ownership, TLS edge, resource envelope measured during S13, first admin, users, agent onboarding and optional service configuration. No model-key fields. Add trusted server handlers through reviewed source changes/rebuilds; capability content alone cannot register executable code. Add external skills without granting new server permissions.

Updates: stop new job admissions → quiesce bounded work → apply explicitly reviewed compatible migration with dedicated role → deploy pinned compatible images → verify UI/API/client journey → resume. Preserve handler/definition versions for in-flight jobs or block visibly. Preserve deletion tombstones and do not replay removed payloads. Document compatibility and failure limits before running migrations; ordinary startup never migrates silently.

Test rollback only between schema-compatible images. Incompatible schema downgrade is not supported in v1; stop rather than promise recovery, and document a separately reviewed roll-forward path if needed. Never delete DB volumes as an update step. **Operator historical backups approved in #7:** use existing Compose/PostgreSQL custom dumps, private configuration/secrets and version/checksum manifests; restore only to an explicit empty isolated target, DB first, errors fatal, no bootstrap over restored accounts or automatic reconnect/replay. Verify synthetic bytes/history/identity/permissions and subsequent writes. No backup service/UI, third datastore, deletion ledger or global-session infrastructure. Historical snapshots may revive deleted content and formerly valid credentials; this is not deletion-safe recovery. Off-host encryption, key custody, schedules and retention remain private operator choices. External originals not stored in canonical PostgreSQL need separately documented preservation. Existing-system migration remains separately authorized.

## Risks, alternatives and explicit limits

| Tag | Risk / earliest disproof signal and action |
| --- | --- |
| **R8** | Retrieval misses important knowledge or returns too much irrelevant context. Issue #8/S12 compare local hybrid search with the lexical baseline, including evidence-only facts and low-degree Objects; publish misses and tune bounded expansion. No secret hosted fallback. |
| **R9** | Shared-record permissions are too broad for a later adopter. V1 has no team partitions; if that requirement changes, redesign API/graph/artifact/result authorization, not a UI-only filter. Basic authorization remains a launch gate. |
| **R10** | Small jobs become a general engine. A request needs arbitrary DAGs, uploaded code, external-agent wakeup or dynamic tool execution; stop and propose a separate design rather than stretching handler IDs into a scripting language. |
| **R11** | Saved Memory/audit is mistaken for verified truth. Show supplied authorship/references/history, deny audit spoofing and preserve revision conflicts. Accepted mutation proves storage, not real-world truth; no internal curation or human-promotion guarantee. |
| **R12** | Inherited generative/hosted-model coupling survives selective reuse. S9 build or S13 network audit finds an unapproved provider route/worker/migration; exclude that path. Local embeddings are the sole approved exception. |
| **R13** | Retry or upgrade duplicates effects/loses authority. S11 effect-before-ack/lease/revocation tests fail; fix idempotency/fencing/reconciliation before expanding adapters. |
| **R14** | Private code/license/data enters distribution. Inventory detects unresolved provenance/defaults; block copying, retain notices and implement generic behavior independently. |

Excluded from v1: general-purpose execution infrastructure; dormant hosted/generative integrations “for later”; catalog-only tools (not usable capabilities); unrestricted/direct-table Memory writes (violates scoped API authority). The earlier per-change Memory approval engine is superseded, not a hidden prerequisite. Evidence-passage search is now included in Issue #8. Broader adapters, SSO/team partitions, HA/SaaS, backup services/UI and deletion-safe historical recovery, scheduled business workflows, native capture bridges, media transcription, autonomous intelligence and arbitrary execution remain deferred. Changed-evidence warnings are optional recommendations only.

Foundation toolchain versions and the HTTP `commons/0.1` contract are documented in [getting started](getting-started.md) and the [API](foundation-api.md). Still to verify at later stages: supported external-client/MCP versions, measured capacity, deletion implementation details and supported GitHub API version. These need implementation evidence, not inferred capability claims. Conversation retention is until explicit deletion, not an unresolved duration. No production rollout, existing data migration or public release is authorized.

## Delivery state

Use [feature status](feature-status.md), dated verification reports and repository
history for delivered behavior. Follow [development guidelines](development-guidelines.md)
for the current change. Historical reports establish only their recorded revision
and environment; they do not assign agents, ownership or deployment authority.
