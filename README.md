# Commons

Shared context and capabilities for your organisation's agents.

Commons gives people and external agents a shared place to save useful knowledge,
track work, and find it again. Your organisation owns the records and decides who
can read and change them.

It runs as a standalone Rust API, React UI and PostgreSQL database. Agents bring
their own reasoning and execution environment; Commons needs no model keys,
embedded agent runtime or particular agent vendor.

## How it works

1. **Find context.** Search record titles and descriptions, follow relationships,
   and read the supporting evidence.
2. **Use it.** People work in the UI; external agents read through the authenticated
   API and do their reasoning outside Commons.
3. **Save what matters.** Create or update a Task, Note or Entity, attach
   evidence, and explain its connections to other records.
4. **Reuse it later.** Saved records, revisions and mutation audit survive restarts
   and remain available to the organisation.

The schema12 candidate has ten application tables and seven Object kinds. Users
are separate identities. A whole formatted Object title+description+body fits
500 tokens; long exact evidence lives in Artifacts. There is no Archive/Restore
or protection feature; retained historical-only records are explicitly readable
but excluded from current lists/search. See the [schema contract](docs/atomic-schema.md).

The data is graph-shaped, but stored in PostgreSQL: **Objects** represent things;
**Connections** say how and why they relate. Descriptions are short current
snapshots, evidence holds the supporting material, and audit records who changed
what. Start with [Schema and ontology](docs/schema.md).

Every Task requires an active User assignee and due date. A canonical GitHub Issue
link is optional; external workflows may deliberately pair one repository Issue
with one Task. Authorized agents can write Notes directly—no per-change human approval.
Search first; update or connect useful existing knowledge, or create a new record.
Routine work need not produce a Note.

The UI collection search matches titles/descriptions lexically. The authenticated
[retrieval API](docs/retrieval.md) combines local EmbeddingGemma 2 text-only semantic
matches with keyword matches. Default discovery searches whole Objects; use explicit
Artifact scope for long evidence. Results are compact and return bounded existing
Connections. Compose packages Ollama and PostgreSQL/pgvector; provision the pinned
CPU model explicitly. No OpenAI key or hosted fallback exists. Records remain authoritative;
the vector index can be rebuilt or replaced without restructuring the knowledge graph.
Commons does not automatically capture conversations, summarise chats or maintain
Notes. Agents use the API, never direct database access.

## Get started

Clone the public source on a Linux host with Docker Engine and Compose:

```sh
git clone https://github.com/bradwmorris/commons.git commons
cd commons
```

Follow the [installation guide](docs/installation-lifecycle.md), then
[choose an agent](docs/site/connect.mdx).

## Documentation

- [Schema and ontology](docs/schema.md) — Objects, Connections, evidence and history.
- [Setup and operations](docs/installation-lifecycle.md) — standalone installation,
  credentials, verification, restart and update limits. For development, use
  [Getting started](docs/getting-started.md).
- [External-agent integration](docs/agent-integration.md) — connect an existing
  agent without adopting a new runtime.
- [Installation appearance](docs/appearance.md) — validated overlay palette and fonts.
- [Evaluation guide](docs/evals.md) — historical comparison reference awaiting the activity/export documentation handoff. The retired comparison workflow is not a schema10 feature.
- [UI views](docs/ui-modules.md) — lists, Task Board, details and graphs over the
  same canonical records.
- [Integration API](docs/foundation-api.md) — supported endpoints, authentication,
  request examples and errors.
- [Context contract](docs/context-contract.md) — shared rules for finding,
  reading and changing knowledge.

## Status

**Schema 12 source preview.** Tasks, Notes,
Entities, named users, scoped tokens, evidence, connections and mutation audit are
available through the current UI/API. Tasks have List, Due date and Board views.
Use synthetic data while the remaining lifecycle and security work is unfinished.

Rich Object kinds, correction/history, and managed-copy conversation deletion are
implemented with synthetic acceptance evidence. Opt-in host capture adapters have been tested with actual Codex CLI and Amp Orb
sessions, with [explicit coverage limits](docs/feature-status.md#automatic-capture-implemented-with-explicit-limits).
Connecting a knowledge tool does not enable capture.
The [local stdio MCP package](docs/connect/mcp.md) exposes three separate product
Python tools: search, read and write. Codex, Pi and local Amp completed search, evidence read and a synthetic write. Claude Code tool discovery passed; provider authentication blocked the model-driven test. See the [client setup guide](docs/site/connect.mdx) for setup and coverage. MCP does not enable surrounding capture. The
[operator snapshot helpers](docs/installation-lifecycle.md#private-historical-backup-and-isolated-restore)
support explicit historical backups and isolated restoration, not a backup service/UI
or deletion-safe recovery. Old snapshots can revive deleted content and credentials.

See [feature status](docs/feature-status.md) and the [synthetic demo](docs/demo.md)
for evidence and limits.
Standalone Compose has a prepared-host rehearsal; clean-host installation and
cross-image update/rollback acceptance remain unfinished.

## Development and design

Read the [requirements](docs/requirements.md), [architecture](docs/architecture.md)
and [development guidelines](docs/development-guidelines.md). The
[testing guide](docs/testing.md) gives the shared local/CI commands.
Reused code and its licences are documented in [third-party notices](THIRD_PARTY_NOTICES.md).

## License

[Apache-2.0](LICENSE), with retained [third-party notices](THIRD_PARTY_NOTICES.md)
for reused material. The software licence does not make an organisation's data,
credentials or private configuration public.
