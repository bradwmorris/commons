# Commons v1 requirements — external agents, local semantic retrieval

## Product scope

Commons is an installable application for organisation-owned knowledge and shared
capabilities. It uses a Rust API, React UI and PostgreSQL, with local EmbeddingGemma 2
retrieval. External agents supply reasoning and execution. There is no built-in
agent runtime or generative model integration, and no required agent vendor.
These requirements describe the target product; [feature status](feature-status.md)
records implemented behavior and verification limits.

## Core contracts

- **Initial installation/trust confirmed:** organisation-shared records, local login, basic admin/member/reader authorization and Compose. Authentication and scoped agent credentials are not optional. Confidential team partitions and company SSO are not launch requirements.
- **Task requiredness decided:** new Tasks require `due_at` for every human/agent actor and general/code work kind. `github_issue_url` is optional; when supplied it must be a canonical HTTPS GitHub Issue URL. Retain Context shapes and active User assignment/execution-brief conventions. **Approved migration exception, implemented in destination staging:** Issue #11 preserves imported legacy Tasks whose due date was already missing, including through unrelated edits. Missing Issue links are ordinary supported Tasks and need no import exception. Do not invent dates or convert Tasks to Notes. Validate missing-date import provenance; ordinary callers cannot claim an exception to omit `due_at`. Full-replacement updates must preserve fields the caller does not intend to change.
- **Issue–Task pairing decided (Issue #4):** an external workflow can create/reuse a repository Issue and call `ensure_task` to pair exactly one Task deliberately. This is not inferred from `work_kind=code` or enforced for ordinary Tasks. There is no webhook/import, bidirectional sync, repository selection or dispatch in Commons. Agent Users use their own scoped credentials, separate from assignment. Installation-owned image avatars reuse Context presentation; personal media is not bundled in the product. Preserve legacy duplicate links as explicit conflicts, never silently merge/relink them.
- **Licence:** Apache-2.0 for Commons. Preserve upstream notices and verify redistribution rights.
- **Memory scope revised and confirmed:** authorized external agents create, update and connect Memories through the authenticated validated API/tools without per-change human approval. This supersedes the earlier proposal/promotion flow. Commons enforces schemas, permissions, attribution and expected revisions without internal generative models or direct agent database access.
- **Retries confirmed:** request receipts are scoped to the authenticated principal, separate from Source identity/deduplication. Never return another caller's receipt or misattribute a write; no global exactly-once orchestration.
- **Deletion confirmed:** retain conversations until explicit deletion, then remove raw payloads and copied excerpts from active surfaces/jobs/payload history without resurrection. Separately saved knowledge may remain with honest lineage and limitations; hiding a Chat is not erasure.
- **Operator historical backups approved in #7:** small Compose/PostgreSQL dump/empty-target restore helpers, private configuration/checksum manifests and disposable verification. No backup service/UI, live schedule, deletion ledger or global-session machinery. Historical snapshots can revive deleted content and formerly valid credentials; this is not deletion-safe recovery. Off-host destinations, encryption/key custody and retention remain private operator choices. Ordinary durable PostgreSQL storage and restart persistence remain required.

Follow the [contributor guide](development-guidelines.md) for implementation and delivery.

## Context and identity

- Rust API, PostgreSQL and Context UI are retained. Selectively adapt current Context's nine canonical Object kinds, artifacts, explained relationships, stable IDs, revisions, mutation audit, reviewable Runs and correction/provenance history. Keep audit facts durable but redact deleted payload copies; do not equate immutable audit with retaining deleted conversation text.
- Real named users, authenticated browser access, server-bound agent/service identities and scoped revocable credentials are required. Caller-supplied identity headers must not confer authority. Task ownership is separate from who performed a mutation.
- External agents use supported read/write interfaces with atomic writes, dry-run validation, idempotency and revision conflicts. No direct database access is required or offered to them.
- Memory remains a record kind, not a running intelligence service. Replace inherited ordinary-agent Memory restrictions deliberately at the common domain boundary; do not bypass them through a model cutover marker. Authorized agents use existing record shapes and supported apply operations. Apply permissions to every effect, including parent artifacts, evidence corrections and both relationship endpoints; HTTP, MCP and fixed handlers share enforcement through commit.
- Onboarding and capability guidance encourage selective evidence-backed lasting knowledge: search first, update/link existing records when useful, otherwise create. Preserve uncertainty and useful source references/history. Zero writes is valid for routine/transient work, duplicates are acceptable, and no per-interaction prompt, pending-proposal queue, global deduplication or internal curation model is required.
- External agents can update Memories after evidence changes using expected revisions. No internal rewriting. A minimal deterministic changed-evidence warning is an optional recommendation only, not a confirmed acceptance requirement.
- Commons generates audit Events for accepted mutations with server-bound identity/time/revision. Agent-authored real-world Event records and claims remain labelled as supplied, not server-observed facts. Agents cannot forge audit facts or elevate authority via actor fields.

### Canonical Context UI

Preserve the existing Commons navigation, layout, typography, typed rows, details,
forms, inline editing and graph behavior. Use the components and styles in `web/src/`
as the baseline. Verify affected collection/detail/form, empty/error and narrow
states with synthetic fixtures and real interaction checks. Product changes may
extend that design; an old upstream deployment is not a required development input.

## Retrieval with local embeddings

**Implementation and evidence:** Issue #8 owns local EmbeddingGemma 2 (270M text-only), served alongside the Compose application through Ollama, with derived vectors in PostgreSQL/pgvector. See [retrieval operations](retrieval.md) for current implementation, measured cases and limits. No hosted embedding provider, OpenAI key or silent external fallback. Model provisioning needs a download or pre-provisioned artifact; after provisioning, embedding requests remain within the installation. External agents still receive Context data under their own environment/provider policies.

- Give agents the schema and a bounded top-X-by-connection-count organisation map. Degree is a centrality signal, not proof of importance or truth. Search the whole authorized store, not just those hubs.
- Combine semantic and keyword matching over Object titles/descriptions and separately indexed evidence passages linked to their parent. Return relevant Objects and useful existing explained Connections within a context budget, with further reading/traversal available. A cluster is a query-specific set of records, not a new stored kind or inferred relationship.
- Guidance recommends retrieval at the start of substantive requests, then again when the topic changes or context is missing. Commons does not automatically inject context or control an external agent's actions. Selective writes and zero-write outcomes remain valid.
- Keep source records authoritative; embeddings are a replaceable index. Pin model/runtime artifacts, query/document formatting, dimensions and chunking version. Fence indexing by source revision and deletion state, expose readiness/failures, and support safe reindex/model replacement without changing canonical IDs or mixing embedding spaces. Preserve writes during model outages and label lexical-only/incomplete search explicitly.
- Measure CPU latency, RAM, indexing throughput, retrieval quality and returned context size before promising a supported hardware envelope. Set bounded defaults and acceptance targets during implementation; neither public scores nor model size prove Commons performance. Model replacement may require re-embedding, not restructuring organisation records.

The UI collection endpoint remains lexical title/description search. The separate bounded
`/api/retrieve` endpoint searches Objects and evidence with explicit hybrid/incomplete/lexical-only
states; `/api/orientation` provides the bounded map. Generative query rewriting, rerankers,
multimodal ingestion and automatic Memory maintenance remain outside this build.

## Shared capabilities must work, not merely describe work

- Organisation-owned, versioned skills, processes and workflow definitions are readable through API/UI and a supported external-agent tool interface. Record owner, revision, executor type, input/output schemas, permissions, evidence requirements and availability.
- Ship implemented callable Context tools, deterministic captured-text source intake and one narrowly scoped read-only service adapter (recommended: GitHub issue retrieval from configured repositories). Catalog entries without implementations are explicitly descriptive/unavailable, never advertised as callable.
- An external-agent procedure describes steps the agent performs in its own environment. Commons records progress/evidence and supplies allowed operations; it does not launch that agent, execute uploaded code or interpret the procedure as a server program.
- Server-executed operations are allowlisted shipped handlers with bounded inputs, authorized effects, timeouts, egress/credential constraints and typed results. Adding handlers requires a reviewed code change/rebuild, not uploading a skill, script, shell command or arbitrary URL.
- Maintain minimal durable jobs for selected deterministic intake/adapter work, safe bounded retry, leases and visible failure/cancellation. Record externally executed workflow attempts with ownership and explicit stalled/interrupted states; never claim to continue reasoning when an agent disconnects. No general DAG engine, Python execution host, arbitrary remote code execution or scheduled autonomous agent launch in v1.

## Capture and model boundary

Only the local retrieval embedding service is approved. No hosted model-provider setup, inference credentials, subscription broker, generative LLM calls or built-in agent execution. Remove/omit inherited generative inference startup, configuration, routes, workers and UI—not just their API keys. Defer autonomous conversation interpretation, generated chat summaries, Event extraction from prose and intelligent memory synthesis/merging/maintenance. An embedding match is not verification of a claim or authority to mutate records.

Retain deterministic audit recording for committed actions. Explicit consented transcript submission may store a supported bounded schema with source/session/message IDs, sender attribution, redaction/deletion controls and replay protection; it does not extract facts. Disclose organisation-shared visibility before consent. Initial agent tools do not capture Amp or Codex transcripts automatically. Native host capture bridges are deferred, version-specific connectors, not universal capture. External agents may analyse supported records and submit explicit writes under their granted authority.

Use minimal truthful origin metadata: caller-supplied captures remain caller-attested even with a valid hash/URL. A deterministic implemented server adapter may fetch without a model or agent; only bytes actually fetched and recorded by it have server-observed origin. A hash verifies supplied bytes, not authorship, truth or completeness of a remote source. No elaborate authenticity subsystem is required.

Deletion must cover messages/artifacts, tracked copied excerpts, search indexes, job inputs/results, request receipts and history payload snapshots. Cancel/fence work referencing deleted raw content and prevent replay or resubmission of the same source/session/message identity from restoring it. Keep payload-free audit/tombstones and deletion status; never a hidden retained raw snapshot. Separately saved knowledge can remain, but disclose this before deletion and show that its source was deleted. See the [deletion contract](architecture.md#conversation-deletion-contract) for the boundary, including external-copy limitations.

Authentication, database, TLS and optional third-party service credentials still exist. Keep them out of prompts, record bodies, browser results, logs and example configuration. Warn users that data returned to an external agent leaves Commons for that agent's environment/provider under the organisation's policies.

## First useful end-to-end experience

Fresh separate installation → admin login and named user → scoped agent credential → actual external agent connects and reads the capability catalog and selective Memory guidance → executes the versioned source-intake procedure using implemented tools → creates evidence-linked records → UI shows identities/history → restart → another task retrieves the saved records and reuses the same capability. Demonstrate the read-only service adapter, not just its description. The authorized agent directly saves/updates/connects a useful Memory, without human promotion, and demonstrates a routine interaction requiring no Memory write. All examples use synthetic data.

## Acceptance and delivery boundary

- Clean Orb setup/resume and a fresh standalone installation are reproducible from locks/docs without sibling repositories, model keys or external harness packages on the server.
- UI/API and an actual supported external-agent client preserve attribution, scope enforcement, persistence, exact replay, conflict behavior and atomic failure.
- Retrieval tests cover lexical/exact matches, semantic paraphrases, evidence-only facts, relationships, outdated/corrected facts, ambiguous/no-answer controls and denied access. Report misses and compare against the lexical baseline using independently labelled relevant IDs, not internal model grading. Verify low-degree relevant Objects remain discoverable, context budgets and index freshness/recovery.
- Catalog permissions match tool execution; reader/revoked credentials, identity spoofing, unimplemented tools, arbitrary execution and unauthorized service targets are denied.
- Task API/UI require and preserve due dates for all actors/work kinds. Issue links are optional; accept absent/null, reject a supplied empty/malformed/noncanonical value, and preserve valid links through unrelated edits. Reuse RFC3339 timestamps and `https://github.com/OWNER/REPO/issues/POSITIVE_INTEGER` syntax (no query/fragment/trailing slash/leading-zero number).
- Authorized agents create/update/connect Memories through HTTP/MCP; readers and unscoped/revoked agents cannot. Test artifact/correction/relationship alternate paths, concurrent edits and stale revisions. Common authorization is held/rechecked through commit. No human-approval dependency remains. Audit cannot be spoofed; source references and agent-authored claims remain distinguishable.
- Alice and Bob using the same request key never share receipts/attribution; concurrent synchronous/job retries under one caller return one committed result. Changed payload conflicts. Canonical Source reuse, where explicit source identity requires it, is independent of request identity; occasional separately created duplicate records are acceptable.
- Conversation deletion uses a unique synthetic marker across documented active copies, history, jobs and receipts; deleted raw text cannot return through retries, late jobs or repeated same-identity submission. Separately saved knowledge remains only within the disclosed boundary. Caller-modified text with a recomputed hash cannot inherit server-fetched origin.
- Restart/crash tests distinguish safely resumed server jobs, unknown side effects and stalled external-agent work. Saved records survive optional step failure. Late fenced writes fail.
- External-network-denied tests exercise startup, browsing, writes, search, jobs, transcript storage/deletion and authorized Memory writes after model provisioning; local embedding traffic is allowed. No hosted model requests or fallback. Adapter egress is separately allowlisted; audit dependencies/config/routes for unintended generative model integration. Test embedding-service failure separately from external-network denial.
- Documentation and tested checks cover installation, configuration, updates, compatible-image rollback, restart persistence and #7's operator historical snapshot/isolated restore workflow, with UI/API evidence. Incompatible schema rollback and deletion-safe historical restore are not promised. A design or mockup is not completed functionality.

Use isolated synthetic fixtures for development. Deployment, live migration and release follow the maintainer’s current authorization. Record actual delivered behavior separately from the full v1 acceptance targets.
