# Testing Commons

These commands test the implemented application, not every planned v1 requirement.
The API, UI and database are real. Use only isolated synthetic data; real-model
retrieval acceptance runs separately as described below.

## Commands shared by Orbs and CI

Schema-12 `verify` uses disposable Docker Compose PostgreSQL 16.15/pgvector 0.8.1,
separate migrator/application roles and the packaged application. It does not require
native PostgreSQL. It runs the current atomic-schema HTTP/fault suites, real compact
UI journeys, PostgreSQL/API restart readback, Rust tests, MCP and tool boundary tests.
A model-free verify run checks lexical behavior; real-model acceptance remains separate.
`--app-image TAG` explicitly tests an already built candidate; otherwise verify builds one.
`COMMONS_CHROMIUM_BINARY` may identify an installed Chromium executable; otherwise
the pinned Playwright installation is required. All fixture volumes are deleted.

For schema12 verify, use a working Docker Engine/Compose daemon, Python 3, uv,
the pinned Rust toolchain, Node/npm, and browser tooling. Verify runs the Rust,
MCP and tool suites locally as well as the packaged API checks. Native PostgreSQL
and its port 55432 are not prerequisites for this Compose lane. Source `check`
also uses rustfmt/clippy and the frontend dependencies. Browser tooling
is independent: `tests/e2e/package-lock.json` pins Playwright and Chromium; initial
installation needs package-network access.

The separate native `dev` and `retrieval` lanes use the
[development installation](getting-started.md): Rust 1.90.0, Node/npm, Python 3,
PostgreSQL 15 at `/usr/lib/postgresql/15/bin` and pgvector 0.8.1. `.agents/setup`
provisions that native lane; it is not a prerequisite for Compose verify.

From the repository root:

```sh
npm ci --prefix tests/e2e
npm run install-browser --prefix tests/e2e
scripts/testing/run check
scripts/testing/run verify
```

On a host missing browser OS libraries, run
`tests/e2e/node_modules/.bin/playwright install --with-deps chromium` instead of
`install-browser` (requires system-package privileges). CI installs these explicitly.
Missing database/browser dependencies are errors, never skipped passing coverage.

Real-model acceptance is a separate **required Issue #8 check**, not a mocked or
silently skipped part of `verify`. Provision the [pinned local runtime/cache](retrieval.md)
first, then run (replace the two paths with actual absolute paths):

```sh
scripts/testing/run retrieval --ollama-binary /path/to/ollama --model-cache /path/to/models
```

It creates its own disposable PG15 cluster, API, loopback Ollama process and private
manifest copy, without modifying the supplied cache. Missing dependencies are failures.
`tests/retrieval.py` seeds through authenticated HTTP, uses independently labelled queries,
measures retrieval/CPU timings and process high-water RSS, stops the real model, interrupts
a rebuild and fences stale/ineligible jobs. Direct SQL is limited to the disposable
index inspection and explicit eligibility/space fault injection, not agent access.
`retrieval.json` records every query rank/miss, lexical baseline, context bytes, timings,
controls and failures. A source-space fault is not a claim to support a second model.
Compose/private-network/offline checks are separate from this native harness.

- **check:** Rust formatting, strict Clippy, locked Rust build, locked frontend
  install/typecheck/build, locked browser-test install, JavaScript syntax checks
  and four synthetic manual-outbox plus ten transfer-package/source-reader tests.
- **Legacy schema-9 verify (replaced by the schema-10 lane above):** check/build, a new isolated PostgreSQL cluster, migrations, normal
  `cargo test --locked`, the existing application-owned HTTP suite, real Chromium
  journeys, then whole-PostgreSQL/API restart and exact public-state/receipt readback.
  Any failed step exits nonzero; browser retries are disabled. Zero Rust tests is not
  equivalent to Rust behavior coverage: the initial foundation's behavior suite is
  `tests/foundation.py`. Main owns future feature/Rust tests.
- **dev:** the same disposable cluster, migrations/bootstrap and Alice/Bob/reader
  fixtures, without running acceptance. It is **not** the persistent installation.
  In an Orb run it as a supervised service, e.g.
  `amp orb service start commons-test-dev --command 'scripts/testing/run dev' --port 3001 --portal`.
  Inspect/stop through `amp orb service logs commons-test-dev` and
  `amp orb service stop commons-test-dev`. Outside an Orb, run in the foreground;
  Ctrl-C cleans up. Never use it for real data. Credentials are in a mode-0600
  temporary fixture file whose path is printed, not in logs or committed config.

For the native dev/retrieval and legacy harness, `--built` explicitly omits
check/build and reuses existing binaries/assets; it is a
diagnostic shortcut, **not full verification**. Full runs and CI omit it. It does not
skip any required database/HTTP/browser check. Do not label an old binary as the
current source: summary records the binary hash and Git revision/dirty flag.

## Isolation, cleanup and failure evidence

Schema12 verify creates a randomly named disposable Compose installation, private
configuration/credentials, application image selection and loopback port. It does
not adopt an existing database or require native port 55432. Its cleanup removes
only its fixture containers, networks and volumes; inspect its report if interrupted.
No native PG15 pass is implied by a Compose pass, or vice versa.

The following details describe **native dev/retrieval and the legacy schema9
harness**, not schema10 verify: a mode-0700 temporary PG15 directory/socket, random
SCRAM credentials and fixed loopback port **55432**. These lanes refuse an occupied
native port; never kill another service to make them pass. Their owned process and
temporary-cluster cleanup does not promise cleanup after SIGKILL/host loss.
Inherited database configuration is discarded. No lane should use live knowledge
or real credentials as a fixture.

Ignored `tests/e2e/results/<run-id>/` holds the JSON status/revision/binary hash,
PostgreSQL/API logs, browser report, and targeted state screenshots. Browser failures
retain trace, screenshot and video. Open reports with
`tests/e2e/node_modules/.bin/playwright show-report <report-directory>` or traces with
`playwright show-trace <trace.zip>`; serve through an Orb portal if reviewing remotely.
These files can include **disposable synthetic** session/token values and passwords
in network/DOM traces. Never use real credentials/data, post raw traces publicly or
blindly publish logs; sanitize review evidence. CI stores them for seven days with
repository access controls. A CI workflow file is not evidence it has run remotely.

## Historical native coverage and ownership

| Check | Executed contract / boundary |
| --- | --- |
| Application-owned `tests/foundation.py` (13 cases) | Named auth/reader/scopes/Origin/spoofing; human/agent × general/code unlinked Task creation, required dates, optional canonical Issue validation and add/clear edits; direct Memory/audit/revisions; artifacts/both link endpoints; atomic rollback/dry run; independent caller receipts/concurrent replay; stale edits; lexical metadata/body miss; revocation; API process restart; explicit demo document sessions, normal-mode denial and rejection of spoofed proxy identity; Issue pairing across retries/credentials/concurrency and generic duplicate denial; agent Users, delegated scopes, writer/owner separation and authenticated revision-checked avatars; bounded lexical evidence retrieval and orientation |
| Eleven Playwright journeys | Memory form create/search/edit/evidence escaping; API-created link traversal and graph focus/fit; unlinked general/code Tasks, required non-UTC dates, invalid optional URL denial and valid link editing/preservation; stale draft/reload; reader/token scope/revocation; Note autosave/cancel, Entity create, modal focus, copy-ID, empty/error/narrow and graph label bounds; fresh protected-demo entry/edit/session renewal without sign-in controls; Task List/Board filter/completed parity, Sydney DST date groups, URL recovery, drag/drop, blocked reason, completion/reopen, stale/invalid writes and reader denial; agent creation/scoped credentials, image upload/rendering across Task views, review ownership and broken-avatar recovery |
| Whole-cluster restart | Exact saved Object details (including Task fields, artifacts, links and audit), authenticated identity and caller receipt survive stopping/restarting PostgreSQL and API with the same storage |
| `cargo test --locked` | Real disposable `DATABASE_URL` provided for native tests as they arrive; initial foundation contains **zero** native Rust tests, not an unreported skip |

No interception/mock server is used in these journeys. Relationship creation is via
the real scoped HTTP API because the UI has no relationship creation form. UI navigation
is tested separately. Selectors use labels/roles and checks assert public state, not
React internals. Timezone checks use Brisbane (+10) against independently calculated
UTC, so a naive local-as-UTC implementation fails.

Main owns `src/`, migrations, Cargo/web manifests, installation/dev scripts and
feature tests (including `tests/foundation.py`). The harness owner owns
`scripts/testing/`, `tests/e2e/`, CI, this page and concise AGENTS test instructions.
The installation Orb independently executes published instructions/journeys; it
must preserve the first published-command failure and distinguish workaround/retest.
A prepared Orb/native PostgreSQL pass is not a clean-host or Compose pass.

Schema 7 extends the suite to **23 HTTP cases and 14 browser journeys**. The added
capture cases cover shared authenticated reads, scope/owner/Origin controls,
concurrent delivery, token-rotation replay, immutable visible items and Run history,
historical missing/deleted references, passive routine results, structured corrections,
managed excerpt/binary/history deletion and pending-outbox replay. Browser checks
cover empty/list/partial/narrow views, visible failed tools, unavailable attachments,
expanded Run history, reader restrictions and confirmed deletion. See the
[capture evidence and limits](connect/capture.md).

`tests/migration.py` and `integrations/migration/test_*.py` remain regression
coverage for existing import compatibility: replay, ownership, exact stored bytes,
invalid inputs and preservation of later edits. They use synthetic fixtures and
are not instructions to rerun a completed installation migration.

Automatic capture has [separate real-client adapter evidence](connect/clients.md).
That evidence does not establish every client version or complete binary/voice
coverage. Product MCP/catalog, callable adapters/jobs and broader installation
acceptance remain distinct from capture implementation.

Issue #8 adds local EmbeddingGemma 2
retrieval acceptance runs through the explicit `retrieval` command above: real-model
quality/resource measurements, revision-safe indexing, rebuild and outage cases.
Offline Compose operation is verified separately, allowing only installation-local
model traffic; see [current evidence and limits](retrieval.md).
The [Compose rehearsal](installation-lifecycle.md) is separate
prepared-host PG16 evidence, not this native PG15 suite. The [demo](demo.md) exercises
actual external Amp HTTP clients separately from deterministic tests. Other transports
and clients need their own evidence. Do not create fake passing tests for absent routes.
#7 adds `python3 tests/compose_lifecycle.py --app-image commons:REVIEWED_TAG --verify-retrieval` after the
three Compose images and pinned browser tooling are installed. It creates only random
disposable projects and removes their volumes: real two-instance/browser isolation,
restart/recreation, private custom dump, corruption/overwrite guards, DB-only isolated
restore, original image/evidence/audit bytes, receipts and new writes. A post-snapshot
revoked token intentionally returns in the restored copy: historical recovery is **not
deletion-safe**. Add `--verify-rich --verify-capture` for the schema-7 shared
binary/history/capture/deletion fixtures, including tombstone restore and stale
index-job non-resurrection. No live backup, schedule or off-host upload runs in CI.
Keep requiredness, authorization and
principal-receipt tests in the feature owner's suite as capabilities arrive.

## External-agent usability milestone (separate from CI)

This is a small black-box user journey, not a model dependency or a deterministic
CI job. Use explicitly authorized external client sessions and a supported real
interface: the current authenticated `/api/contract` and HTTP API are sufficient for
the historical HTTP demo. Product MCP **0.1.2** now packages the three canonical
search/read/write modules; see [current MCP evidence](connect/mcp.md). Packaged
two-user API checks, assisted Codex use, targeted autonomous revision-key recovery
and the configuration-only procurement mapping/connector refresh are verified.
Claude Code connected but provider authentication returned 401 before a model turn.
Full two-client usability and integrated installation/release acceptance remain
unfinished; these checks do not establish general unassisted reliability. Record exact Commons
revision, client/version, transport, discovery output and redacted tool activity. An
actual Amp agent choosing and executing HTTP tool calls proves that bounded client
journey; a standalone Python acceptance script does not. No automatic agent creation is
part of verify. Never put private token files, portal login URLs or cookies in evidence.

1. Seed a separate synthetic installation through authenticated API with stable IDs
   and replayable receipts. Give the first fresh external agent a Note-scoped
   credential, a task outcome and the documented discovery entry point. No direct DB,
   live business service or reference configuration is involved.
2. Ask it to find useful customer context, create one clearly synthetic handoff Note,
   revise the supplied scheduling detail using the current expected revision, and
   connect its evidence. Distinguish scenario-specific scheduling from the existing
   service-review preference; do not overwrite unrelated records. Exercise identical
   lost-response replay and a stale update, preserving exact before/after state.
3. Find the agent-created Note in the actual UI, edit it there, and ask the writer
   for independent HTTP readback. A second fresh agent with a separate read credential
   must search for and use the current information without being given the expected
   value, follow its relationship and read the evidence. It must distinguish stored
   supplied claims from server-verified facts. Deny a reader mutation as a control.
4. Grade independently by API/UI readback and actual tool activity: correct existing
   Note ID updated (no forced dedup engine); correct value/revision and provenance;
   server-bound user/credential audit; later retrieval of the
   same IDs/relationship; no out-of-scope mutation. Report each pass/fail/blocked,
   unnecessary writes, errors/retries and operator help. A fluent agent answer or
   zero tool calls earns no storage/retrieval pass. Restart the same synthetic storage,
   compare exact details/identity/receipt, and replay the seed without overwriting the
   UI edit. Revoke temporary evaluation credentials afterward.

Model access/client availability may block this milestone without blocking the
deterministic suite. Missing tooling is a product milestone gap, not permission to
simulate tool discovery or claim a successful external-agent evaluation.

## Runtime audit lane

`Verify Commons runtime` builds the three pinned Docker images on a hosted runner
and executes `tests/compose_lifecycle.py --app-image commons:runtime-check
--verify-retrieval --verify-rich --verify-capture --metrics-output runtime-metrics.json`.
It runs for pushes changing application code, its workflow, lifecycle harness or runtime packaging;
manual dispatch can also select a branch once the workflow is on the default branch.
It is separate from foundation CI and creates only randomly named disposable
installations. It checks real PostgreSQL 16, model provisioning and recovery,
independent browser sessions, restart/recreation, rich evidence and capture/deletion
preservation, isolated restore and receipt replay. It never uses live credentials
or live installations. A schema-compatible application rollback still requires a
second distinct reviewed image and is not implied by this lane.

The optional metrics file compares eight requests each for full Object detail,
compact metadata, a 24,000-character evidence window and warmed retrieval on the
rich synthetic fixture. It records response bytes and latency, not a production
capacity result. It does not measure query-plan/pool-wait attribution, true cold
model startup, peak process memory or representative large-corpus recall. Preserve
those limits when reporting results; do not select indexes from this microbenchmark.

## Overlay appearance

`verify` additionally restarts its disposable API with two valid token overrides
(one over each preset), unreadable text, malformed JSON and an empty object.
`tests/e2e/appearance-check.mjs` checks the real public stylesheet response and
cache policy, signs in, opens/cancels a dialog, and verifies primary/focus colors,
font choice and fallback appearance. It saves a screenshot for each case. Native
resolver tests cover allowlists, injection rejection, partial configuration and
contrast. This adds no live installation configuration or user preference state.

For operator-only retrieval investigation, `commons diagnose-retrieval` accepts no
arguments and uses the configured app database connection. It checks fixed product
query plans in a read-only transaction with a per-statement timeout, without
starting the server, workers or model. Its JSON contains allowlisted plan node,
row, loop, timing and buffer metadata; it excludes SQL, expressions and record
values. Keep installation-specific output outside the repository. This is a
bounded fallback after representative timing checks, not an arbitrary SQL tool.


## Schema12 deletion and captured-body search candidate

`check` and `verify` cover the schema12 source, ordinary Object deletion (all six writable kinds, revisions, scope denial, validation rollback, stable receipt replay, owned evidence removal and independent linked knowledge preservation), captured-body search/read windows, correction/append stale references, managed deletion replay fences and explicit native-span exclusion. Verify also executes the three tool modules against real HTTP, then the rendered deletion cancel/confirm journey and PostgreSQL/API restart. These use only disposable synthetic fixtures.

On Docker-capable hosts with an existing pinned **model-only** cache volume, the real-model retrieval lane can also run via `scripts/testing/run retrieval --disposable-model --model-volume EXPLICIT_VOLUME`. It mounts the selected cache read-only, copies it into disposable model-container storage, creates separate PostgreSQL/API processes, exercises bounded Thread chunking/current correction/deletion fences and semantic retrieval, and runs the existing labelled retrieval corpus. It never adopts a knowledge database or modifies the selected cache. Missing/wrong model pins fail. This is distinct from the documented native PG15 lane and is not a live migration or full-capacity conversation benchmark.
