# Schema10 status

The comparison product described below is historical schema9 behavior, retired in
the schema10 candidate. It is not a current setup or verification path. The new
activity/export and external manual-review walkthrough awaits its verified owner
handoff; no DSPy runner or evaluation dashboard is introduced by the current
schema/tool implementation. Preserve existing historical evidence separately.

# External-agent comparisons

Commons stores reusable versioned requests and paired external attempts for human
inspection. There is no runner, grading, judge, rubric or required quality verdict.
All normal authenticated users in one installation can read every test, run and
stored file. The Evals page shows the task/question, paired outputs and file links.
Configuration, bundles and attempt history remain available through the API. Readers cannot write. Member sessions and agent tokens with the new
`eval` write scope can mutate; existing tokens gain no write authority. The Access
screen can issue an eval-scoped token. Login, origin checks and account revocation
still apply. Follow [the skill](../skills/commons-evals/SKILL.md).

## API: commons.evals/1

`GET /api/contract` advertises this surface. `GET /api/evals/guide` returns the
complete skill and API guide for coordinators. `GET /api/evals?q=title&offset=0`
returns `tests` and `next_offset` (50 per page). `GET /api/evals/{id}` returns current
`test`, immutable `versions` and `runs`. `GET /api/eval-runs/{id}` returns the pinned
`run`, all append-only `attempts` and derived operational `status`. Stable browser
links are `/evals/{id}` and `/eval-runs/{id}`. Payloads live in dedicated PostgreSQL
tables, outside Objects, general Runs, artifact indices and organisational retrieval.

POST `/api/evals` with:

```json
{"contract_version":"commons.evals/1","idempotency_key":"unique-logical-write","validate_only":true,"operation":{"op":"create_test","title":"Synthetic Lantern outreach","request":"What should outreach emphasise from the supplied brief?","configuration":{"model":"actual-client-model","ordinary_tools":["files"],"starting_files":{"brief.txt":"actual-sha256"}}}}
```

Validate then execute the same body/key with `validate_only:false` (or omitted).
Validation rolls back and returns no usable provisional IDs. Successful writes
return `id` and, where relevant, `revision` / `attempt_id`. Read back the saved
record. Keys are scoped to the current credential, serialized for concurrent retry,
and conflict on changed payloads (409). Validation flags are excluded from the
logical hash. A replay never overwrites later edits or resurrects revoked grants.
After credential rotation reconcile existing state; receipt identity changes.

Exactly one operation per request:

| op | Required fields |
| --- | --- |
| `create_test` | `title`, `request`, `configuration` (object) |
| `revise_test` | Same plus `test_id`, `expected_revision` |
| `create_run` | `test_id`, `test_revision`, `context_bundle` (text, may be empty) |
| `append_attempt` | `run_id`, `expected_revision`, `arm` (`without` or `with`), `attempt` |
| `grant_context` | `run_id`, `token` (caller-generated `cet_` + 32 random bytes as hex) |
| `revoke_context` | `run_id` (revokes all grants for that run) |

An attempt contains `status` (`pending`, `completed`, `failed`, `partial`), `output`,
`error`, `evidence`, `session_id`, `isolation` (`verified`, `unverified`, `unsupported`),
optional `files` (`[{"name":"briefing.md","content":"exact UTF-8 text"}]`) and
optional `links` (`[{"label":"Document","url":"https://example.org/file"}]`).
Completed attempts require nonblank output, failed attempts require an error,
verified isolation requires evidence. Evidence and isolation remain caller-attested.
Retries of execution append another attempt; earlier attempts remain inspectable.
Both latest arms completed → completed; neither started → pending; both failed →
failed; every other combination → partial. This is operational state, not quality.

Limits (UTF-8 bytes): title 200, request 100,000, configuration 32,000, bundle/output
200,000, error 20,000, evidence 50,000, session ID 200. Up to ten text files, each
200,000 bytes, with simple filenames; up to twenty HTTPS links without embedded
credentials. `GET /api/eval-files/{attempt_id}/{zero_based_index}` downloads exact
stored text with no-store, attachment and nosniff headers. Binary products stay at
external links; their durability and destination access are not guaranteed by Commons.
No server fetch occurs. Stored text files are durable PostgreSQL data.

## Isolation boundary

Normal authenticated readership is shared. A normal read-only agent token can see
all comparisons and is **unsuitable** for a trial. Trial capabilities are separate
from normal credentials: only `GET /api/eval-context` accepts their bearer token;
normal authenticated endpoints reject it. It returns only the run's immutable,
coordinator-selected bundle, not prompts/results/history or live retrieval. Tokens
expire after 24 hours, are stored hashed, can be revoked, and cease working if the
issuing credential/account is revoked/expired/disabled. Do not place them in output,
configuration, URLs or evidence. The grant response does not echo the secret.

This constrained bundle is the supported MVP treatment knowledge interface. Broad
live retrieval is not isolated by this implementation. The coordinator must review
bundle provenance and exclude prior results. The server cannot detect contamination
pasted into a bundle or stop an agent reading host secrets, shared files, another
connector, or a captured transcript. Use real execution-environment separation;
if unavailable, record the limitation and use guided manual setup. Shared human
visibility is never used as a substitute for trial isolation.

## Verification boundary

`tests/evals.py` exercises the real HTTP/storage/authority contract through the
normal disposable foundation suite. `tests/e2e/evals.spec.mjs` exercises creation,
links, side-by-side states, file downloads, two signed-in readers, keyboard and
narrow layout. The harness reads back eval versions/attempts/files after PostgreSQL
and API restart. These are synthetic deterministic fixtures, not external-agent
execution or proof of benefit. Real client setup and independent execution must be
reported separately with actual evidence. No live installation migration is implied.
