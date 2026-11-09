# Commons feature status

The ledger records bounded implementation and verification evidence. Dated reports
apply only to their recorded revision and environment; they are not deployment
status or current agent assignments. Use current code, tests and Issues when
assessing a newer change. Full v1 acceptance remains incomplete.

## Schema10 candidate — 2 November 2026

The working-tree candidate uses ten application tables, seven Object kinds and
dedicated Users. Whole title+description+body is limited to 500 exact tokens; only
long Artifacts are chunked. Notes replace Memories, Threads replace Chats, Themes
replace categories; archive/protection and the built-in comparison product are
retired. Existing historical-only records remain explicitly readable outside
current lists/search. See [schema](schema.md) and [retrieval](retrieval.md).

The [MCP package reference](connect/mcp.md) records frozen package **0.1.2**,
packaged two-user candidate API checks, assisted Codex CLI 0.157.0 use and targeted
autonomous revision-key recovery. Configuration-only business mapping and connector
refresh were verified; server-upgrade persistence is separate. Claude Code 2.1.152
connected but provider authentication returned 401 before its model turn. Full
two-client onboarding and integrated installation/release acceptance remain pending.
Model-free API checks show keyword-only degradation, not semantic quality. Earlier
automatic capture evidence does not recertify the schema10 Thread/Trace path.

The ledger below is **historical pre-schema10 evidence**, not the current physical
schema, supported-kind list or release acceptance. References to Memory, User
Objects, categories, archive/protection and comparison UI describe those revisions.

## Historical implementation and verification ledger

| Capability | Delivery/evidence boundary |
| --- | --- |
| Rust/PostgreSQL/React build + explicit migration/bootstrap | Native PG15 setup/resume and distinct-role PG16 Compose installation tested. Mounted secrets, schema-aware readiness and explicit migrations; no automatic migrate/reset on startup. Clean-host remains unverified; bounded compatible-image evidence is listed below |
| Local login, named users, admin/member/reader, scoped/revocable agent tokens | Implemented-and-tested: actual portal admin created named member/reader; member issued scoped bearer; reader lacked New/Edit/Append and had disabled write scopes; HTTP origin/spoofing/scope/revocation denials passed. Expiry-duration behavior unverified; account reset/disable pending |
| Rich records, documents and history | [Schema-6 evidence](atomic-schema.md): Source/Theme/Event, Entity categories, exact Note evidence, text/images/document versions, supplied history/corrections, archive/protection and legacy Task exceptions. [Schema-7 joint deletion/restore](connect/capture.md) adds synthetic combined coverage. Relationship creation/update remains API-only; UI reads/traverses links |
| Mandatory Task due_at; optional canonical GitHub Issue | Implemented-and-tested for suite cases: human/agent × general/code unlinked creation, due-date absent/null/blank rejection and valid offset retention; optional absent/null Issue acceptance, supplied invalid URL rejection, valid linking/clearing and uniqueness. `ensure_task` still requires the Issue and remains retry-safe across callers |
| Atomic apply, dry-run and credential-scoped replay | Implemented-and-tested for HTTP suite rollback/dry-run, equal/changed bodies, independent caller receipts, concurrent replay/stale edits, replay after edit and revoked access. Source-specific receipts await intake implementation |
| Lexical UI collection search; separate hybrid retrieval API | Metadata pagination/kind/recent/connected ordering remains unchanged. `/api/retrieve` additionally searches current evidence passages and semantic candidates; see Issue #8 measurements below |
| Canonical Context and Access UI | Reused Context91b31f4 components/styles with synthetic source renders at matching desktop/narrow viewports. Eleven browser journeys cover typed forms, inline autosave/cancel, required Task dates, optional Issue linking, conflicts, reader controls, tokens, copy-ID, modal focus and graphs. Lead inspected real demo screenshots and pointer clip; narrow graph-label clipping fixed. Historical visual comparison; current UI changes are checked against Commons itself |
| Actual external Amp HTTP client | Fresh remote writer discovered/read/searched, created one Memory, updated with expected revision, connected Note, replayed identical request and rejected stale update. Actual UI changed same Memory; writer independently read it back. Fresh bounded subagent in lead Orb retrieved current information and proved reader403/no mutation. Not MCP, Codex or a second remote-reader Orb claim |
| Synthetic seed and restart persistence | Stable API receipts seed nine records/nine links without duplication or overwriting later edits. Shared suite preserves14 exact details plus identity/receipt across PG/API restart. Persistent demo separately preserves13 details, agent receipt/identity and UI revision4; repeated seed and two resumes preserve state. Compose separately preserves10. No crash/power-loss or backup guarantee |
| Chat/Run writes and conversation correction targets (#9) | [Schema-7 synthetic stage](connect/capture.md): canonical messages/tools/attachments, Run history, historical import, readable UI and explicit manual outbox. Historical Users remain inert identities, not accounts; user reset/disable remains pending |
| MCP, versioned callable capability catalog/procedures and source intake | Planned remaining v1, not implemented; current authenticated HTTP discovery is not MCP or a descriptions-only substitute for callable capabilities |
| Read-only GitHub adapter, bounded jobs and external attempts | Planned remaining v1, not implemented |
| Consented transcript storage/deletion/non-resurrection | Synthetic managed-copy deletion/replay cases pass across shared artifacts/history, indexes and pending outbox delivery. Opt-in host adapters are implemented and tested with actual Codex CLI and Amp Orb sessions; see the 25 October evidence below. Capture remains separately configured per installation, and connecting a knowledge tool does not enable it |
| Two-image compatible update/rollback | [Two distinct historical schema-2 images](installation-lifecycle.md) preserve exact state/receipts and allow new writes in both directions. Incompatible schemas refuse serving. This is not rollback evidence across #9/#11 migrations |
| Clean-host installation and production hardening | Still unverified; prepared-host Compose pass does not complete these |
| Local EmbeddingGemma 2 hybrid retrieval | [Issue #8 implementation and measured limits](retrieval.md): pinned CPU Ollama/pgvector, 768-dimensional Object/evidence retrieval, bounded existing Connections/map, durable revision-fenced indexing/rebuild. Native synthetic evaluation: 12/12 relevant IDs at five versus lexical 2/12; MRR 0.944. Not a large-store or multilingual claim |
| External reasoning / local retrieval boundary | Only the selected local embedding model; no hosted fallback or generative runtime. Native actual-model outage/restart and stale/ineligible/space-fencing checks pass. Schema-7 Compose checks add stale-job non-resurrection; broader real-client intake remains pending |
| Operator historical backup/restore (#7) | [Compose lifecycle helpers](installation-lifecycle.md#private-historical-backup-and-isolated-restore): private whole-PG dumps/config/checksum manifests and empty-target DB-only restore; no service/UI/scheduler. [Schema-7 combined fixture](connect/capture.md) restores rich documents/binaries/history/capture exactly and demonstrates old-content/credential revival. Mac/clean-host and cloud stages remain separate |
| Backup service/UI, deletion-safe historical recovery, internal agents/generative models, general orchestration | Excluded/deferred, not implied by operator snapshot helpers |

Implemented-and-tested means only named observed cases at a stated revision/environment;
implemented-but-unverified includes missing/failing/blocked checks. Planned means no Commons
handler/feature, not a hidden success claim. Full v1 acceptance and Issue #1 remain open.

See [literal install guide](getting-started.md), [API](foundation-api.md),
[shared testing commands](testing.md) and [verification protocol](verification-protocol.md).
Current test commands and prerequisites are in [testing](testing.md). Counts in
older reports describe those revisions, not the current suite. Application CI
runs `verify`; Docker/model lifecycle checks are separate.

## Automatic capture: implemented, with explicit limits

The [25 October adapter verification](connect/clients.md)
records 21 passing adapter/outbox tests and actual Codex CLI and Amp Orb sessions.
A bounded background poller captured new business turns, excluded personal turns,
survived reader/delivery restarts and verified exact stored text and tool records.
This is implemented functionality, not a future migration step.

The tested versions were Codex CLI 0.157.0 and Amp
0.0.1792886472-ge1e052. The evidence does not establish every later client version,
Claude Code or local Amp coverage. Voice-only timelines, original audio/binaries,
and content already truncated by a client remain limitations. Routing is
agent-attested; mixed turns are excluded in full. Installation-specific activation
and production acceptance belong to that installation, not a product-wide enabled
flag. See [setup and coverage](connect/automatic-capture.md).

## Historical comparison MVP (Issue #23)

This schema9 product was retired in the schema10 candidate. Preserve historical
evidence; do not follow it as a current onboarding workflow. Activity/export and
external-review documentation awaits its implementation handoff.


Schema/API, shared comparison UI and external-agent skill are present in this
repository; verification and real-client acceptance are recorded in the associated PR.
The treatment interface is a frozen knowledge bundle, not isolated broad live
retrieval. Deterministic fixtures do not prove external execution or benefit.
See [evals](evals.md). No live migration/deployment is implied.
