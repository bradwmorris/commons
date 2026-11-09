# Development setup

Use this guide for an isolated native development installation. For Docker Compose,
use [installation lifecycle](installation-lifecycle.md). The [testing guide](testing.md)
owns automated check prerequisites and commands; [feature status](feature-status.md)
records tested behavior and remaining gaps. Do not use a live knowledge database
as a development fixture.

## Supported development lane

Use an isolated **Debian 12 x86-64 Amp Orb**, Node 22+ and npm, Python 3, curl, sudo/apt
and Amp CLI (preinstalled in Orbs), at least 4 GB RAM and 5 GB free space. Setup installs
PostgreSQL **15** and Rust **1.90.0**; npm/Cargo lockfiles pin dependencies. No sibling
reference checkout, model key, Docker daemon or external agent package is needed.
PostgreSQL 16/Compose uses separate storage/configuration; never reuse the native data
directory or interpret a native test result as a Compose pass. Obtain an exact reviewed
Commons revision from the repository and record that checked-out revision for each run.
First build requires package network access. Setup checks Node 22+/npm and installs missing
Debian build/PG15 prerequisites, but does not install Docker or start/migrate/reset a database.
Observed here: Debian 12 x86-64, Rust 1.90.0, PostgreSQL 15.19, Node 26.10.0 and npm
10.9.9. Other Node 22+ versions were not independently tested in this rehearsal.

```sh
.agents/setup
amp orb service restart commons-db
scripts/dev-init
amp orb services ensure
```

Start the declared database first, explicitly initialize it, then ensure the application.
Starting both before initialization makes the API fail to connect to a nonexistent database;
that first-boot failure was observed and the sequence above corrects it.

This creates `.commons/pgdata`, local random DB credential and database `commons`,
and applies the reviewed embedded migration. It never imports reference data.
PostgreSQL binds loopback 55432, SCRAM on TCP; local Unix socket trusts the Orb OS user.
`.commons` is ignored and private to that disposable Orb; it is not a secure multi-user
host deployment. fsync/synchronous_commit/full_page_writes are not disabled.
Native init/serve authenticate and verify that the server data directory belongs to this
checkout before proceeding. A missing password for existing storage or a non-PG15 native
directory fails closed; do not rotate credentials or remove data to bypass the error.
Services are supervised, not detached shell processes. The app serves the built React
bundle and API at one origin. Use the **exact portal URL printed by ensure**; portal
access is separate from Commons authentication. Do not save a generated portal hostname.

## Bootstrap once, then use named login

Choose synthetic credentials for this disposable installation. Do not paste a production
password into a thread, script or record. Enter it without echo:

```sh
source scripts/dev-env
export COMMONS_ADMIN_USER=admin
export COMMONS_ADMIN_NAME='Synthetic Administrator'
read -rs -p 'New local admin password (12–128 bytes): ' COMMONS_ADMIN_PASSWORD; echo
export COMMONS_ADMIN_PASSWORD
target/debug/commons bootstrap
unset COMMONS_ADMIN_PASSWORD
```

Bootstrap refuses if **any account already exists**. Open the portal, sign in, then Access
→ Create named user (member/reader/admin). Access → Agent credentials issues a 30-day
revocable token bound to the signed-in user. Copy once into the external client's secret
storage, then dismiss; no database credentials go to agents. A reader cannot acquire write scopes.
External-agent read access exposes organisation-shared records to that agent's environment/provider.

## First real records

Create a Task with active User owner, local due date/time, status/priority/work kind
and brief before doing. The date is required for **all** actors and work kinds. A
canonical GitHub Issue URL is optional; use it when the work has a deliberate Issue
relationship, not merely because `work_kind` is `code`.
Create a Note directly; search first, update/link existing knowledge when useful or
create otherwise. No human promotion. Record detail shows current revision, evidence
artifacts, connected records and server-observed audit identity/action/time.
The HTTP [foundation API](foundation-api.md) supports link creation; UI currently reads
links but has no creation form. Edit errors preserve the entered draft; revision conflict
requires Reload latest (discarding the stale draft) or manually reconciling it.

No raw HTML/Markdown execution; bodies are displayed as plain escaped text. The UI
collection search remains lexical metadata with pagination and kind/recent/connected
filters. [Local hybrid retrieval](retrieval.md) is a separate authenticated API and
requires explicit model provisioning/configuration; `.agents/setup` installs pgvector,
not model weights. An unset model URL gives honest lexical-only evidence retrieval.
Conversation storage and managed-copy deletion are implemented; this development
lane still uses synthetic data. See [capture and deletion limits](connect/capture.md):
external copies and historical backups are outside that deletion guarantee, and
independently saved knowledge may remain with deleted-source lineage. Client capture
requires separate configuration and coverage verification.

## Verify and resume

Use the [shared real-PG/browser commands](testing.md), not the persistent demo as test storage.
The harness owns a fresh disposable PG15 cluster and refuses an occupied native port.
If this Orb is running its own demo, stop only those two owned services temporarily:

```sh
amp orb service stop commons
amp orb service stop commons-db
npm ci --prefix tests/e2e
npm run install-browser --prefix tests/e2e
scripts/testing/run check
scripts/testing/run verify
.agents/resume
.agents/resume
amp orb services ensure
```

The harness discards inherited DB configuration, boots the actual Rust binary, runs the
HTTP and browser checks, restarts its whole cluster and compares exact saved public state.
It removes only its own temporary cluster/credentials. Restore the demo with ensure even
after a failing check; preserve the failure evidence and do not reset the demo database.

`amp orb service restart commons` restarts API only; `amp orb service restart commons-db`
restarts PostgreSQL without deleting storage. Use ensure if a service is missing, inspect
`amp orb service logs commons`/`commons-db` on failure. Resume checks build files only;
it does not migrate, install, bootstrap, rotate credentials or clear data.
Keep a seeded synthetic demo's existing checkout, `.commons` and service configuration;
resume/restart is not a request to reseed or replace its records. A different checkout
cannot adopt the same native port/cluster. The lead owns any demo seeding instructions;
the disposable testing harness is not the persistent demo installation.

Historical Foundation1 independent results: HTTP suite **8/8**, plus its API process restart; direct browser
admin/member/reader and Task/conflict/evidence journeys; separate API and whole-PostgreSQL
restarts with the same saved Task/Memory/Note detail hash and valid scoped credential.
Repeated setup and two resumes preserved the fixture. `cargo test --locked` ran **0 Rust
unit tests**; it is not a substitute for the real database/HTTP/browser checks.
The later shared-testing harness/CI integration was not part of that historical snapshot;
see [current feature status](feature-status.md) for subsequent evidence.

## Update and compatibility

Schema10 includes an old-to-new migration, but earlier native setup evidence is
not proof of a current candidate upgrade. The candidate moves Task content to
top-level body and project to fields.project, uses dedicated Users and seven Object
kinds, and rejects formatted Objects over 500 tokens. Long originals belong in
Artifacts. See [the exact schema contract](atomic-schema.md). For an authorised
revision: inspect changes/migrations; stop API, build with `.agents/setup`, explicitly run
`scripts/dev-init` for reviewed migrations, then restart API and verify. Ordinary startup
never migrates. Return to the prior binary only if its schema is documented compatible;
no downgrade/schema rollback or backup/restore guarantee exists. Never remove `.commons`
as an update/reset shortcut. This guide confers no authority over existing deployments.

For packaged agent access use [MCP setup](connect/mcp.md); its bounded two-user API
and assisted Codex checks do not establish clean-host or full two-client acceptance.
