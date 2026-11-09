# Commons MCP stdio connection

The product-owned Python tools are exposed through a separate local stdio server.
Each agent client starts its own connector process and uses its own Commons API
credential. The connector calls the existing authenticated HTTP API; it does not
run a model, install capture hooks or collect surrounding conversations.

## Installation and credentials

Prerequisites: Python 3.11+, `uv`, a reviewed Commons checkout/package, and access
to a Commons installation. From the reviewed checkout:

```sh
uv tool install .
commons-mcp --version
```

This installs both the adapter and the product `tools` package. No Meta Lord,
private overlay, repository `PYTHONPATH` or database connection is needed at runtime.
Use the absolute path of the installed `commons-mcp` executable in GUI clients
whose PATH differs from your terminal. For a reviewed update:

```sh
uv tool install --force .
```

Stop/restart the client's MCP connection after updating. Re-discover the tools and
repeat the synthetic search/read/write checks before using changed schemas.

Create a named user and scoped agent credential through Commons Access, following
[agent integration](../agent-integration.md). Give each authorised user a separate
credential. Supply the following in the client/server process environment through
your local secret mechanism:

- `COMMONS_URL`: explicit Commons origin, for example `https://commons.example`.
  Plain HTTP is accepted only for loopback development. Credentials, URL query
  strings and URL paths are rejected. TLS verification stays enabled.
- `COMMONS_TOKEN`: that user's scoped Commons API token. Do not put it in tool
  arguments, prompts, shell history, committed configuration or saved records.

The connector ignores proxy environment variables and never follows HTTP redirects.
This deliberately requires a direct supported route to the configured API origin.
There is no default installation, fallback store or shared service credential.

Current package **0.1.5** performs a read-only `GET /api/contract` before starting tool
discovery. It requires `commons/0.1` and schema version **10, 11 or 12**. Missing, older or
newer schema versions fail with a clear connection error before any tool operation;
the connector never migrates an installation. Use a reviewed matching API build:
the schema number alone does not prove every later same-schema feature is present.

## Codex

In the appropriate private Codex configuration, use your installed executable:

```toml
[mcp_servers.commons]
command = "/absolute/path/to/commons-mcp"
env_vars = ["COMMONS_URL", "COMMONS_TOKEN"]
```

The variables must be available to the Codex process that launches the connector;
a terminal export does not establish that an already-running desktop app inherited
it. Restart the applicable client/connection and check discovery. Do not replace
an existing server entry without reviewing it. See [official Codex configuration](https://learn.chatgpt.com/docs/extend/mcp#stdio-servers).

## Claude Code

With the variables available in the Claude Code launch environment, register the
absolute executable path under the appropriate private scope:

```sh
claude mcp add --scope user --transport stdio commons -- /absolute/path/to/commons-mcp
```

Use `/mcp` to inspect connection/discovery. Registration changes that user's client
configuration; perform it only in the intended user/test profile. See [official
Claude Code MCP guidance](https://code.claude.com/docs/en/mcp).

## Tools, errors and adaptation

The server imports only `tools.commons_search`, `tools.commons_read` and
`tools.commons_write`. Names, descriptions and JSON schemas come from those modules;
the MCP adapter does not maintain another copy. API permissions, revisions and
idempotency remain enforced by Commons. A new field/type may require product code
and a migration; editing client configuration does not change the database schema.
See the [current schema implementation contract](../atomic-schema.md).

Before adapting a business installation, inspect its live API and the reviewed
product tool definitions. Apply the supported configuration or code/migration path
on an isolated installation, update the package when its definitions change,
restart/discover and repeat the checks below. Do not assume old client-cached
definitions match a changed API.

The verified configuration-only example maps a fictional procurement business onto
existing fields: suppliers are Entities with `entity_kind: "supplier"`, procurement
work uses Tasks with `project: "procurement"`, and Notes link to policy Sources.
Installation name/theme can also be configured through the supported lifecycle
settings. This adds business vocabulary, not new Object kinds or arbitrary fields.

`integrations/mcp/tests/business_adaptation.py` verifies that mapping in a separate
synthetic installation, then reconnects through an updated package. The executed
0.1.1→0.1.2 connector refresh preserved bodies, fields, attribution and relationships;
rediscovery/search/read/write passed, and an unsupported custom field was rejected
without mutation. The fixture was cleaned up. This is connector-update evidence;
new schema extensions and API/server-upgrade persistence remain separate acceptance.

HTTP failures return safe status guidance without raw server payloads. The bounded
public `error` string from a recognised API denial is retained when it matches the
safe JSON error envelope; arbitrary bodies, extra fields and credential echoes
are suppressed. A 401 needs
credential renewal; a 403 needs scope/permission review; a 409 needs current-state
or original-key reconciliation. A timeout or broken connection can leave a write's
outcome unknown. Read back/reconcile and retain the exact original body/key before
retrying. The transport never automatically retries a mutation. Errors retain
the tools' structured `error.code`, `message`, `status` and `saved` fields.
Known validation/auth/conflict denials report `saved=false`; an interrupted,
malformed or oversized successful POST response reports `saved=null` (unknown).

Decoded HTTP responses are bounded to 128 MiB. This accommodates a supported
16 MiB Artifact body even with six-byte JSON character escaping; a regression
check exercises that case. Ordinary Artifact reads use Unicode windows of at most
48,000 characters and explicit `next_offset`, far below that transport bound.
Historical evidence or unusually rich collection pages can still exceed the
bound: request smaller pages or use the authorised direct API path when no
paginated representation exists. The adapter does not silently truncate a result.
An oversized write response leaves its save outcome unknown, requiring readback.

Request/call identity is not a conversation identity. Missing surrounding activity
and correlation remain unknown. MCP alone does not provide a complete trace or
populate the knowledge index with observed tool results.

## Verification status and acceptance

The adapter pins official Python SDK 2.3.0 and httpx 0.28.1; `uv.lock` pins transitive
dependencies. Seventeen tests cover modern/legacy protocol modes, actual product
module schemas/dispatch/structured errors and a real stdio subprocess, plus HTTP
identity forwarding, redirect/error denial, response bounds and uncertain-write
handling. Stub handlers remain limited to transport crash-isolation cases. Run from
the repository after installing the locked environment:

```sh
uv sync --locked
uv run python -B -m unittest discover -s integrations/mcp/tests -v
```

The schema-10 isolated candidate API also passed packaged checks under two named
synthetic users: discovery/search/read/write, writer attribution, exact Artifact
paging, links, same-key replay after later revisions, stale edits, packet-size
rejection, scope/reader denial and actual token revocation. An actual committed
write with an injected lost success representation remained `saved=null`; an
identical-key packaged retry recovered the original receipt. The fixture had no
embedding model: these checks exercised `lexical_only`/`model_not_configured`, not
semantic retrieval. Expiry was not exercised because no supported expiry-control
fixture/API was provided.

Actual Codex CLI **0.157.0** created/read a note and linked its source, then retrieved
the note in a fresh ephemeral session. Assistance was required: noninteractive
tool approval had to be explicitly configured for the authorised fixture, and the
client's guessed `expected_from_revision`/`expected_to_revision` fields were
corrected to published `from_revision`/`to_revision` after safe validation rejection.
The CLI used invocation-only MCP configuration, `--ignore-user-config`,
`--ignore-rules`, `--ephemeral` and a disposable working directory; normal config
was unchanged. Its model was the CLI default, not pinned.

A targeted repeat with package **0.1.1** deliberately reproduced the wrong
`expected_*` revision keys. The improved product-tool error identified the supported
fields; Codex corrected them, validated/executed a stable-key link and read it back
without manual key coaching. This verifies autonomous recovery in that example,
not general unassisted agent reliability.

The updated package reads exact correction `body`/`text` Unicode windows. A targeted
older candidate check read such a window correctly, but retrieval still returned
an original-Artifact match without the new correction-specific `match.read` locator.
That stale-candidate mismatch is resolved by the schema owner's final packaged
image verification: corrected-only search returns the correction ID/field/reference,
then reads the exact representation while preserving original Artifact text.
See final schema/image evidence,
image manifest `sha256:98a13a2120c91c3a9bcc01269ae2a9aba184734c5ea214c10dfeeead3055cc7e`.
This is integrated image/API evidence supplied by that owner, distinct from this
owner's direct package/window tests and actual Codex/Claude observations. The
obsolete isolated candidate is not used as final acceptance evidence.

Actual Claude Code **2.1.152** connected to the package, but onboarding remains
blocked before a model turn. A disposable config directory had no provider login;
a protected run using the existing native auth context returned provider 401,
`OAuth access token is invalid`. Normal settings writes were denied by the OS and
their hashes remained unchanged; no provider credentials were copied or repaired.
A usable authenticated disposable client profile is needed to finish this check.

The SDK supports both protocol eras; the real-client observations above do not
claim universal client/protocol compatibility. See [SDK documentation](https://py.sdk.modelcontextprotocol.io/)
and [MCP versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning).

On a disposable installation with synthetic users/data:

1. The actual wheel's clean-environment package/contract smoke is verified. Repeat
   it for the final candidate; all three definitions must import without the
   checkout on the Python path.
2. Connect one user through Codex and another through Claude Code to the same
   installation. Record exact candidate, Python/package/client/schema versions,
   commands, negotiated protocol, assistance and limitations.
3. Discover tools; search/read selected evidence; save/link synthetic evidence;
   retrieve it in a fresh session. Check actual writer identity and saved revisions.
4. Check scope/read-only denial, expired/revoked credentials, stale revisions,
   interrupted-write reconciliation and exact-key retry without duplicates.
5. Follow one supported business-schema adaptation, refresh the package/tools and
   repeat discovery/search/read/write.
6. Record onboarding review and integrated installation acceptance.

To repeat the clean-wheel contract smoke without checkout-path imports:

```sh
uv build --out-dir /private/tmp/commons-mcp-dist
uv venv /private/tmp/commons-mcp-wheel-env --python 3.12
uv pip install --python /private/tmp/commons-mcp-wheel-env/bin/python /private/tmp/commons-mcp-dist/commons_mcp-0.1.5-py3-none-any.whl
/private/tmp/commons-mcp-wheel-env/bin/python -I integrations/mcp/tests/wheel_smoke.py /private/tmp/commons-mcp-wheel-env/bin/commons-mcp
```

The smoke starts only a disposable loopback HTTP fixture. It checks the real
packaged tool modules and both SDK protocol modes; it does not run the Commons
server or actual Codex/Claude clients. Use fresh temporary paths for repeated runs.

Repeatable candidate API acceptance is in `integrations/mcp/tests/api_acceptance.py`.
It requires an explicitly authorised private synthetic fixture and consumes its
designated revocable credential. Use a fresh fixture for each complete run; do not
reset credential expiry or edit the database to make a check pass.

Package0.1.3 contains the current product definitions, including scope-aware index
diagnostics, supported Event precision and the legacy plain-Note alias. The wheel's
tools/adapter bytes were compared with the actual source after building.
It also includes compact nested Connection endpoints with deliberate read arguments,
accepted-choice/range errors and the product guidance on local references and
in-batch link revisions. Full owning Objects and relationship meaning remain readable.
The matching0.1.3 Codex repeat recovered the connected exception and current
corrected evidence, saved one decision with two supporting links, and read it back.
It used21 tool calls versus25 in the earlier run, but total serialized tool output
grew by17.8% because the correction was read in full twice. This is one fictional
case, not a general efficiency, capture-coverage or clean-host onboarding claim.

Codex is the currently verified actual-client path. Claude Code's model-backed
onboarding remains unverified after the recorded provider authentication failure.
The final adopter walkthrough remains pending. Server-upgrade persistence is
separate from the verified connector refresh/business mapping.
Do not use live data stores or change existing client
settings to run these tests. Cloud MCP hosting is not part of this first transport.


For a known delegated human, set `COMMONS_ON_BEHALF_OF` to that installation's
active human User UUID in private MCP configuration. `commons_write` also accepts
`on_behalf_of`; an explicit UUID or null overrides the configured default for that
request. Null allows agent-only work when the human is unknown. Preserve this
context with the exact key/body on retries. Never derive it from task assignment.
Use a separate agent User/token per agent, independent of model/provider login.


The schema12 candidate adds `commons_write` operation `delete_object` for ordinary Objects, requiring current revision and `acknowledge_owned_content_deletion:true`. Default validation remains non-saving. Thread managed deletion remains a separate HTTP owner/admin operation. `commons_search` includes visible captured bodies in `objects`/`all` and adds `threads`; follow `thread_text` reads with the returned revision/window. Native spans and incomplete Source evidence remain excluded, with explicit exclusion counts. Schema10/11/12 compatibility at connection time does not make schema12 capabilities available on an older server; inspect the installed contract. Refresh the installed MCP package/tool discovery with the reviewed release; editing source does not update an existing connector.

The schema12 deletion/conversation-search package is version **0.1.5**. Build and install its exact reviewed wheel when updating an existing local installation; a force reinstall of the same version can reuse an older cached local wheel. Verify fresh tool discovery and the live schema after installation.
