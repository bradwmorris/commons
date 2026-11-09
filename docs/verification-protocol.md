# Installation verification

Use this for installation, update and recovery rehearsals. The [testing guide](testing.md)
owns executable test commands; [requirements](requirements.md) and feature contracts
own expected behavior. This guide does not assign agents or file ownership.

## Record and isolate the inputs

Record the exact Git revision, dirty state, image/artifact hashes, OS, toolchain,
database and client versions. Use synthetic data and disposable storage. Do not
inherit private configuration or use a running knowledge installation as a fixture.
A fresh directory on a prepared host is not a clean-host installation.

Keep development setup, standalone Compose installation, actual external-client
access, restart persistence and compatible-image rollback as distinct checks.
Success in one does not establish the others. Missing prerequisites are blocked
checks, not passes.

## Exercise the published procedure

Follow documented commands in order. Record the first failure before applying a
fix; report workarounds and corrected reruns separately. Required database and
browser checks must execute. Inspect rendered states and real interactions when
UI behavior changes. Use independent expected values, not values copied from the
implementation being tested.

Cover the contracts affected by the change:

- Authentication, scopes, attribution, denied reads/writes and credential revocation.
- Validation, atomic failure, stale revisions and same-key retries without duplicate effects.
- Exact record/evidence readback and persistence after application/database restart.
- Retrieval correctness, degraded modes and index recovery when retrieval changes.
- Supported capture coverage, deletion and replay/non-resurrection when capture changes.
- Installation readiness, explicit migrations and supported update/rollback boundaries.

For deletion, use unique synthetic markers in raw content and registered copies.
Check active reads, history payloads, indexes and pending/replayed work; separately
saved knowledge must retain honest deleted-source lineage. Historical backups can
revive content and credentials: follow the isolated restore procedure in
[installation lifecycle](installation-lifecycle.md), not a claim of deletion-safe recovery.

## Report the result

State the revision/environment, commands, expected and observed results, failures,
skips and limits. Redact secrets and keep private payloads outside Git. Use a dated
report under `docs/verification/` when durable acceptance evidence is useful; routine
checks can stay in the change's review record. Update broken instructions and
[feature status](feature-status.md) from observed results. A passing fixture is not
proof of untested client coverage, production readiness or deployment.
