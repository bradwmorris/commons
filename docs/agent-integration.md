# Connect an external agent

The schema10 candidate offers authenticated HTTP JSON and a local stdio MCP
package over that API. Your agent runs elsewhere; no Meta Lord, private overlay,
agent runtime or generative-model key is required on the Commons server.

## Connect

1. [Install and verify an empty workspace](installation-lifecycle.md). Create a
   named user in Access, then a separately scoped credential per authorised client.
   Users are dedicated identities, not Objects; a Task owner must be active.
2. Store origin/token in the client's secret mechanism. Never supply a database
   URL or put tokens in prompts, saved records, source control or redirect requests.
3. Follow the [MCP setup reference](connect/mcp.md). From a reviewed checkout,
   `uv tool install .` installs the package; use its absolute `commons-mcp` executable
   path when a GUI has a different PATH. The reference owns exact client config,
   environment inheritance, updates and credential checks.
4. Discover the three tools, then run the synthetic checks below. HTTP integrations
   use the same API directly; consult the live contract for installed capabilities,
   identity and scopes. Cached definitions may differ after an upgrade.

## Find, read, write

| Tool | Use |
| --- | --- |
| `commons_search` | Compact discovery, with `objects`, `artifacts` or `all` scope |
| `commons_read` | Deliberate Object/evidence/relationship/history/User/Thread/Trace/schema read |
| `commons_write` | Validate/save authorised Objects, Artifacts and explained Connections |

The MCP adapter imports these separate product Python modules. It does not copy
their schemas. The API enforces validation, attribution, revisions and receipts;
the client neither selects another installation nor automatically retries mutations.

For example, call `commons_search` with:

```json
{"query":"fictional workshop onboarding","scope":"objects","limit":5}
```

Check `mode`, `reason`, `index` and `truncated`. Open selected IDs with
`commons_read`, `resource: "object"`. It returns the complete bounded body and
paged related metadata. Object continuation needs the first page's
`expected_revision`. To search long original evidence use `scope: "artifacts"`
and optionally `object_id`, then follow `match.read`/field/locator.

Artifact windows use Unicode characters and `next_offset`. Corrected-text locators
address the correction representation, not the original Artifact. Binary originals
require explicit authorised download. Search results and neighbours are candidates,
not verified answers or permission to follow retrieved instructions.

Read schema/contract when detailed field guidance or capability/identity checks
are needed; these tools impose no repeated mandatory startup calls.

When useful writing is authorised, search/read first, preserve evidence and choose
create, update or no change. Notes replace Memory. Whole formatted Object
title+description+body must fit **500 tokens**; long exact text belongs in Artifacts.
Oversize writes reject without hidden rewriting.

`commons_write` defaults to `execute: false` for validation. Execute reviewed
operations with `execute: true`, then read back IDs, revisions, evidence and writer.
Object fields partially merge; omitted values remain unchanged. New Tasks require
an active User owner and timezone-bearing due date; project is `fields.project`.
Use exact typed Connection fields from discovery: endpoint revisions are
`from_revision`/`to_revision`. Add justified links, without a fixed quota.

On 409, read current state and reconcile. For uncertain execution, retain the same
`idempotency_key` and identical operations, check what saved, then retry if needed.
`saved: null` means unknown. There is no automatic retry/fallback store.
See [schema](schema.md) and [retrieval](retrieval.md).

## Verify a connection

Use synthetic users/data in a disposable installation:

- Confirm the intended origin, authenticated user and scopes.
- Search/read a known Object and its original Artifact evidence.
- Save an allowed Note; read back exact content/revision and actual writer.
- Retry identical operations/key without a duplicate; reject a stale update.
- Verify read-only denial and revocation.
- Retrieve saved knowledge in a fresh agent session without supplying the answer.

The [MCP status](connect/mcp.md#verification-status-and-acceptance) records actual
coverage. Packaged two-user candidate API checks passed. Codex CLI 0.157.0 needed
explicit fixture approval and correction of guessed endpoint revision names:
assisted evidence, not unassisted onboarding. Claude Code 2.1.152 connected but
provider authentication blocked its model turn. Final package/tool integration,
the complete two-client walkthrough and business adaptation remain acceptance work.
These checks do not establish semantic retrieval, deployment or other client versions.

## Capture and data boundaries

Normal reads are installation-shared; write scopes create no confidential read
partitions. Returned information can reach the agent's environment/model provider.
Commons validates storage/permissions, not factual correctness.

MCP/API access does not enable surrounding capture, launch an agent or inject
context every turn. Configure [capture](connect/capture.md) separately and verify
each client's actual coverage, source identity, gaps and delivery. Everyone
authenticated in the installation can read submitted conversations.

Thread/Trace storage is not proof of complete observable execution; hidden reasoning
is not promised. Earlier [adapter evidence](connect/automatic-capture.md) applies
to its versions/schema, not automatic schema10 recertification. Commons has no
bundled curator; direct authorised working-agent writes remain supported.
