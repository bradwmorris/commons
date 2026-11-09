# Standalone installation and lifecycle

This guide is the standalone adopter path: install an empty workspace, verify a first
record, connect an agent, then practise operation and recovery. It also serves an
operator installing Commons for another organisation. Use fictional data for the
first walkthrough and record any help or undocumented step needed.

**Verification boundary:** the commands below describe the existing source and dated
rehearsals, not a newly passed release candidate. Clean-host installation, current
Docker Desktop/CPU-architecture support and a populated customised upgrade still need
their own executed evidence. [Feature status](feature-status.md) separates tested
features from remaining work.

This lane packages the delivered Commons foundation, **not completed v1**. It needs no
Amp, sibling reference checkout, agent runtime or model key on the server. Native Orb
development remains a separate [getting-started lane](getting-started.md). Only synthetic
disposable installations were authorized for this work; these instructions do not authorize
operating an existing deployment, changing public access or migrating live data.
See the dated installation evidence
for the corrected native-host Compose rehearsal, first failure and untested lifecycle limits.
The 17 October lifecycle evidence
covers two-instance sessions, historical restore, model recovery and a bounded compatible-image pair.

Issue #8 adds private Ollama 0.40.5,
pinned EmbeddingGemma 2 text-only Q8_0 weights, and pgvector 0.8.1. The commands below
include explicit provisioning into a persistent model volume. See [retrieval operations](retrieval.md)
for measured CPU cases, readiness, degraded behavior and rebuild limits. These commands
are for empty disposable storage, not authorization to migrate an existing installation.

## Prerequisites and boundaries

- A trusted Linux Docker host, a working Docker Engine daemon and Compose v2.20+ plugin.
  A Docker CLI alone is insufficient. Verify `docker info` and `docker compose version`.
  Install through [Docker's platform instructions](https://docs.docker.com/engine/install/)
  if needed. Membership in the Docker group effectively grants host administrator access.
- Python 3 for local configuration and backup helpers; Git for obtaining source; network access for image,
  Cargo/npm and Debian package downloads during the build. Host Node/Rust/PostgreSQL and
  Playwright are **not** needed to run this stack. They remain development/test tools.
- A free loopback HTTP port, persistent Docker volume storage, and enough memory/disk to
  compile the Rust release image. Resource observations and clean-host limits belong in
  the dated verification report, not an unmeasured production sizing promise.
- Use an exact reviewed source revision and preserve its image ID/digest and configuration.
  Do not substitute an unreviewed moving tag during update or rollback.

`Dockerfile` uses pinned official Rust/Node/Debian build/runtime image digests. Compose pins
official **PostgreSQL 16.15-bookworm** to index digest
`sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4`.
Native development/tests use PG15; never attach a native PG15 data directory to PG16 or
downgrade the Compose volume's major version. Debian packages fetched during build can
change; locked dependencies and base-image digests are not a bit-identical-build guarantee.

## Choose the installation journey

1. Follow **First empty installation** below. Record the reviewed Git revision,
   platform/architecture, Docker/Compose versions and any local changes. Keep the
   generated private configuration and exact built image identifiers.
2. Follow **Verify the first workspace** before adding organisational knowledge.
   A healthy container alone is insufficient.
3. Optionally explore the [fictional demo](demo.md) in its own isolated installation.
   The existing demo initializer is for the native Orb lane; it is not a Compose
   seeding command. Do not run it over this workspace or import demo identities.
4. [Connect an external agent](agent-integration.md), then separately choose whether
   to configure [capture](connect/capture.md). Generic HTTP access needs no private
   overlay. The [MCP package](connect/mcp.md) has candidate implementation and bounded checks;
   final client and installation acceptance remain pending.
5. Optionally customise supported installation settings, then repeat the affected
   checks. Branding below is configuration-only. New Object kinds or fields may
   require validation, migrations, indexing, tools and UI changes; arbitrary schema
   editing is not supplied by these commands. See [schema](schema.md).
6. Practise restart, historical backup/isolated restore and a reviewed compatible
   update below, using synthetic data before depending on recovery for real work.

## Schema10 candidate boundary

The candidate uses [ten application tables](atomic-schema.md), dedicated Users and
seven Object kinds. Whole Objects are bounded to 500 formatted tokens; keep long
originals in Artifacts. There is no archive/protection feature. Migration retains
existing historical-only records outside current lists/search, with explicit reads.
Do not infer that earlier Compose or rollback evidence covers this migration.
The package/runtime integration and personal installation walkthrough still need
acceptance against one exact reviewed candidate. No live migration is performed
by following this draft or reading its historical evidence.

## First empty installation

From the Commons repository root, on the chosen Docker host:

```sh
scripts/dev-compose-config --config-dir .commons/first --project commons-first --port 3401
source .commons/first/config
docker compose build app db ollama
docker compose run --rm model-provision
docker compose up -d --wait db ollama
docker compose run --rm migrate
docker compose run --rm bootstrap
docker compose up -d --wait app
docker compose ps
```

Run each command only after the preceding command succeeds. If one fails, keep its
exit status and sanitised logs, inspect the cause, and resume at the corrected step.
Do not regenerate credentials, bootstrap an existing account database or delete
volumes to make an installation appear fresh.

### Verify the first workspace

The example's configured browser origin is **http://localhost:3401**. Open that exact
origin after `app` becomes healthy. Read the generated initial password privately
as described below; sign in as the bootstrapped administrator.

1. Confirm the workspace contains no business knowledge or fictional demo records.
   Bootstrap may create the administrator identity; that is not imported knowledge.
2. In **Access**, create a named member for ordinary work. Sign in as that member
   using a separate browser profile if keeping the administrator session open.
3. Create a Note titled `Synthetic installation check`, containing a distinctive
   sentence such as `The fictional workshop opens on Thursday.` Reopen it and
   compare the saved text. Record its ID and revision privately for restart checks.
4. Search for the title in the UI, open the result and check the original evidence
   and attribution. Collection search is lexical metadata search; this does not
   prove semantic retrieval or embedding readiness.
5. Follow [Verify a connection](agent-integration.md#verify-a-connection) for a
   separately scoped client: read the record, save/read back an allowed synthetic
   write, check retries/stale revisions and deny a read-only write. Check retrieval
   readiness and limits using the [retrieval guide](retrieval.md).
6. Repeat the record read after the restart procedure below. A valid credential,
   exact retained content/revision and a new successful write are stronger evidence
   than an open browser tab or a health response alone.

The [foundational test suite](testing.md) runs in its own disposable native test
environment with separate build/browser prerequisites. Do not point it at this
workspace. The Compose lifecycle check at the end of this guide separately creates
disposable Compose projects. Neither replaces a person following these instructions.

For an installation handover, retain a private checklist: candidate revision/dirty
state, platform and client versions, commands/actions, expected and observed results,
sanitised evidence links, failures/help required, and remaining limits. Agree which
real business requests matter before later claiming improved outcomes.

The generated literal-export `config` records `COMPOSE_PROJECT_NAME`, an absolute
`COMMONS_CONFIG_DIR`, the HTTP port/origin and source-based image tag. Use a fresh shell
per installation; do not inherit another instance's `COMMONS_*`/`COMPOSE_*` overrides.
Persist intentional changes in this file, not only the current shell. Operator helpers
read these literal values without executing shell code and ignore inherited overrides.
No arguments preserves the original `.commons/compose`/port 3000 defaults. Existing config
is never rewritten; for an older config explicitly record its **existing** project name
and absolute config directory before using the backup helper. Never choose a new project
name to repair an existing installation.

Use the same project name for the entire installation: it identifies the persistent named
`pgdata`/`models` volumes and private network. The one-off `migrate` and `bootstrap` tools are not ordinary startup services.
Never automatically run them on container restart, Orb resume or image launch.

### A second independent installation

In a fresh shell in the same Commons checkout:

```sh
scripts/dev-compose-config --config-dir .commons/second --project commons-second \
  --port 3402 --origin http://127.0.0.1:3402
source .commons/second/config
# Same built images; different DB/model volumes, networks, configuration and secrets.
docker compose run --rm model-provision
docker compose up -d --wait db ollama
docker compose run --rm migrate
docker compose run --rm bootstrap
docker compose up -d --wait app
```

The first example uses `localhost`, the second `127.0.0.1`. **Ports do not isolate
browser cookies:** Commons uses the same host-scoped session cookie name. Use these
distinct local hosts, distinct HTTPS hostnames, or separate browser profiles; two
tabs on `localhost` at different ports will overwrite each other's session cookie.
Each installation must have its own users and credentials; never reuse a token or
silently reroute a failed request to the other installation. There is no cross-store sync.
Normal agents need a selected endpoint, scoped credential and instructions—not this
checkout or a private overlay. Two installs do not require kind, forks or a third database.
Generic examples above also work without `commons_enyu` or `commons_brad`.

### Optional trusted-local entry, without a sign-in screen

For an explicitly approved single-user local installation, set
`export COMMONS_LOCAL_USER=EXISTING_MEMBER_UUID` in that installation's private
literal config and recreate its app. Resolve/create that named member through the
existing administrator API; do not map to an admin or import a historical account.
The operator can do this setup without asking the viewer to create an account or
enter a password. Leave the separate admin available privately for imports.

This setting requires an HTTP `localhost` or `127.0.0.1` origin, an active member,
and no protected-demo setting. Fresh HTML navigation issues a normal HttpOnly,
SameSite session for that member, with no sign-in/out controls. API calls without
a cookie/token remain 401; bearer scopes, Origin/revision checks and admin-only
imports remain enforced. Disabling the setting invalidates its automatic sessions.
Wrong document Host headers are rejected; local pages cannot be framed.

**Trust boundary: anyone able to reach the local listener can act as this member.**
This is not Amp authentication, SSO or per-person identity. Keep the Compose host
publication on `127.0.0.1`, never add a public proxy, and trust the Mac's local users
and Docker administrators/attached containers. The app listens on the container
bridge using Compose's explicit `COMMONS_BIND=0.0.0.0`; native local-entry processes
default to `127.0.0.1`. Do not override that default on an exposed host.
Keep separate cookie hosts for the two stores. Ordinary installations remain
password/session/bearer authenticated when this opt-in setting is absent.

### Installation branding

The same app image can identify separate installations without changing records or
accounts. Set these optional values in each installation's private literal config:

```sh
export COMMONS_INSTALLATION_NAME='Example workspace'
export COMMONS_THEME=blue-slate
```

The name defaults to `Commons`; the theme defaults to `charcoal` (the existing
palette). `blue-slate` is the alternate muted dark palette. Names are trimmed and
must contain 1–64 characters without control characters; unsupported themes fail
startup. The first character supplies the collapsed brand mark. The name appears
in navigation, sign-in and the browser title. Both settings are public UI metadata
returned by unauthenticated `/api/health`; never put secrets in them.

Recreate **only the app** with the installation's normal Compose configuration to
apply these settings. There is no database migration, index rebuild, permission or
local-entry change. Preserve the previous image and private config for rollback;
keep personal names/settings outside shared source. Native servers use the same
environment variables. Branding loads from health before sign-in, not from a
browser preference or a separately built frontend.

The first DB launch provisions **empty storage only**, from `docker/init-db.sh`: the schema
owner/migrator is `commons_migrator`; ordinary serve/bootstrap use `commons_app` with table
DML and sequence privileges, not superuser/schema-create authority. Application migrations
remain explicitly invoked, reviewed, embedded Rust migrations. The PostgreSQL administrator
creates the vector extension only during empty-volume initialization; an existing database
needs a separately approved administrator extension step before migration 0003. Binaries
require their exact embedded migration versions/checksums; no downgrade is supplied.
The PostgreSQL administrator
secret is not mounted in the app or migrator. No DB port is published. The app is non-root,
has a read-only root filesystem and dropped Linux capabilities, and serves built UI/API
from one origin. PostgreSQL has only the internal private network. The app also joins an
ingress bridge for loopback port publication; this is **not** an application egress allowlist
or network-denied acceptance. Ollama has only the private network and no published port;
only the one-off model-provision tool has a provisioning egress network. Migration/bootstrap
tools remain on the private network. Never add a public Ollama port to fix provisioning.

Configuration lives in the chosen private directory (`.commons/` is Git-ignored). The generator creates random distinct
DB/admin secrets and URL files once, then preserves them on subsequent runs. A partial run
without a config file is refused rather than rotating credentials for a possibly existing
volume. Files are mounted read-only via Compose secrets; local Compose uses host bind mounts,
not encrypted secret storage. Secret files are 0444 so container users can read them, inside
0700 host directories. Host root/Docker administrators can read them; this is a trusted-host
installation, not protection against those administrators. Keep this directory private and
do not log/export/commit it or copy it into an image.

The app/tools use `DATABASE_URL_FILE`; bootstrap additionally uses
`COMMONS_ADMIN_PASSWORD_FILE`. Do not also set the corresponding direct environment value:
the CLI deliberately rejects ambiguous direct-plus-file configuration. `_FILE` keeps usable
secrets out of Compose's environment values, not out of the trusted host administrator's reach.

Bootstrap defaults to username `admin` and name `Administrator`; optionally export
`COMMONS_ADMIN_USER` and `COMMONS_ADMIN_NAME` before the command. The generated initial
password is in the selected config directory's `secrets/admin_password`; read it only in a private local
terminal/password manager, never in a thread or record. Bootstrap refuses when any account
exists, so re-running it is not an account reset. Follow the guide for named users, scoped
credentials and required Task fields. Conversation deletion is implemented for the
stored conversation and its managed copies; it does not erase external exports or
historical backups. Independently saved knowledge can remain with deleted-source
lineage. Review [capture and deletion limits](connect/capture.md) before enabling
collection, and verify the intended client coverage separately.
Issue a separate scoped credential per external client; rotation means issue a replacement,
verify it, then revoke the old credential in Access. Tokens expire after 30 days. Bootstrap
secret replacement does not reset an existing login, and changing database secret files
does not rotate passwords in an initialized PostgreSQL volume. Account reset/global session
invalidation are not supplied by these helpers. Keep recovery credentials securely.

## Origin, TLS and readiness

The example binds **loopback only** and uses HTTP loopback for synthetic verification.
Open the exact configured origin; `localhost` and `127.0.0.1` are different origins. For a
future authorized host installation, configure an operator-managed HTTPS reverse proxy and
set `COMMONS_ORIGIN` to that exact HTTPS origin before recreating the app. HTTPS enables
Secure cookies. Do not expose PostgreSQL or silently bind the app to all host interfaces.
No proxy, certificate, public DNS, hosting or deployment is provisioned by this repository.
Docker Desktop keeps named volumes inside its Linux VM; a Mac directory containing config
is not the database. On Linux, Docker manages volumes under its daemon data root. Inspect
`docker volume inspect PROJECT_pgdata` rather than assuming a physical host path. The
container mounts are `/var/lib/postgresql/data` and `/models`; the app has no writable
authoritative file volume. Host/Docker disk loss or volume deletion loses this storage.

Remote client hookup is a separate operator step. Host loopback is not remotely reachable
and a laptop may sleep. Arrange an authenticated HTTPS/private route and independent
ingress/Commons credentials only when authorized; this installer does not expose services
to remote Orbs. Capture defaults off and is independent from ordinary authenticated access.

`docker compose logs app`/`db` and the exit status of each one-off command are diagnostic
inputs; inspect locally and redact secrets before sharing. A DB `pg_isready` pass only means
PostgreSQL accepts connections. App `/api/health` is not a substitute for authenticated
read/write/UI checks: it checks DB/schema and reports build/contract/schema versions. Serve
and bootstrap reject a missing, unsuccessful or nonmatching embedded migration set/checksum.
A missing/failed migration must be investigated, not bypassed by
resetting the volume. Fix the reviewed cause and rerun the explicit command; a partial fresh
DB provisioning failure is not automatically repaired on restart.

## Restart and shutdown

```sh
# First source the intended installation's config, in a fresh shell.
docker compose restart app
docker compose restart db
docker compose up -d --wait app
```

After restart, verify known IDs, revisions, artifacts, links, attribution, identity and replay
receipts through the authenticated API/UI. `docker compose ... down` stops/removes containers
and the private network but **preserves the named volume**. Never use `down --volumes`,
`docker volume prune`, remove `.commons`, or replace secret files as an update/reset step.
A volume is not a backup. The operator snapshot workflow below is separate from restart
persistence; neither promises physical crash/power-loss recovery or deletion-safe restoration.

## Private historical backup and isolated restore

`scripts/compose-lifecycle` is an operator command, not a service, scheduler or API.
It uses the existing Compose database's PostgreSQL tools. No live data operation is
authorized merely by these instructions; practice on disposable synthetic data first.

```sh
# Choose a new output directory beneath an existing private parent.
scripts/compose-lifecycle backup --config-dir .commons/first \
  --output /absolute/private/backups/first-2026-10-17
```

The app can remain online: `pg_dump --format=custom` provides a consistent single-database
snapshot. Do not migrate, rotate secrets or edit configuration concurrently. The helper
checks schema/config/secret stability, writes a private dump and secret copies, then writes
`manifest.json` last as the completion marker. A failure leaves an incomplete private
directory, not a successful backup; inspect/remove only that failed output and retry to
a new path. Existing backup directories are never overwritten. Directories are 0700 and
bundle files 0600. Do not publish them: **the bundle is plaintext and contains credentials**.

The manifest records the source project/configuration, PostgreSQL/pgvector/migration
versions and checksums, exact app/DB/Ollama image IDs, operator checkout revision and
Compose/init-file hashes, timestamp and SHA256 for each payload. If Git metadata is
unavailable, the diagnostic checkout revision is explicitly null; exact deployed image
IDs and Compose/init-file hashes remain mandatory. These checks detect
damage, not malicious replacement: restore only trusted backups. A PostgreSQL dump can
execute SQL. Source/image pins are not a promise that a rebuild is byte-identical.
The helper supports the generated standalone DB/role layout only and rejects database
URLs pointing elsewhere; it must not silently back up a local DB while the app uses another.
Confirm the intended Docker context/daemon before any command. The manifest records its ID.

**Included:** all canonical tables, binary bytes actually stored in PostgreSQL, history,
accounts, credentials, receipts and derived indexes, plus the installation's six secret
files and literal configuration. #11 documents/images/history and #9 accepted Chat/Run
data use that same database when delivered. **Excluded:** original files only referenced
by path/URL, external identity assets, remote originals, client histories/outboxes, operator
files outside this config, application image archives and model weights. #10 owns mapping
external originals into canonical storage or a separately documented recoverable package;
a database dump does not prove those originals were captured. Instance-specific migration
exclusions belong in that migration's inventory, not the generic backup helper.

Keep reviewed release images **once per version**, separately from daily data snapshots:

```sh
# Replace references with the reviewed app/DB/Ollama image references recorded at install.
docker image save commons:REVIEWED_TAG commons-postgres:16.15-vector0.8.1 \
  commons-ollama:0.40.5 > /absolute/private/backups/release-images.tar
# On a replacement Docker host, load that trusted archive before restoring:
docker image load --input /absolute/private/backups/release-images.tar
```

The restore helper refuses missing exact image IDs; it never silently pulls a mutable
tag or substitutes a rebuild. Keep the matching Commons source revision too. The model
volume is reproducible: explicit model provisioning verifies/downloads the pinned weights;
optionally preserve a verified cache if recovery must work without download access.

```sh
scripts/compose-lifecycle restore --bundle /absolute/private/backups/first-2026-10-17 \
  --config-dir .commons/first-recovery --project commons-first-recovery --port 3403 \
  --accept-historical-state
```

Restore requires a nonexistent config directory and a different, unused project with no
existing containers/networks/volumes. It verifies payloads and matching Compose/init files
before starting anything, pins recorded image IDs, starts **only DB**, initializes the
required roles from recovered secrets, restores into a fresh `template0` database in one
transaction with errors fatal, and verifies metadata. Ownership/default grants come from
the dump; database access is reset to the normal app/migrator boundary. **Never bootstrap
over restored accounts.** Failure leaves the isolated target for inspection; no automatic
cleanup, retry, app startup, index rebuild, client reconnect or capture replay follows.

**Historical restore rewinds data and access.** A deleted record can return; a token revoked
after the snapshot may work again; old account settings/passwords/browser sessions may
return. This accepted operator workflow is **not deletion-safe recovery** and has no
deletion ledger/global-session invalidation. Start only a private local verification
session after reviewing this risk; inspect the chosen snapshot and use existing revocation/
reissue controls before reconnecting clients. Post-backup writes are not merged automatically.

After operator review, explicitly start the recovery application:

```sh
# Fresh shell; use a separate browser profile from existing installations.
source .commons/first-recovery/config
docker compose run --rm model-provision
docker compose up -d --wait --no-build --pull never ollama app
```

Check health/schema, named login, original IDs/revisions, document and image
hashes, history/corrections/links/receipts, authorization and a new write. Compare with an
independent pre-backup fixture/inventory. Provision/rebuild derived retrieval as needed;
health alone is not index completeness. A successful restore—not a dump file's existence—is
the recovery check. Keep the original installation unchanged until separately authorized cutover.

Capture's host-local queue is only an outbox; server backup cannot recover never-uploaded
events. Do not auto-replay an old queue after restore. If separately preserved, SQLite
DB/WAL must be copied consistently with original destination binding; lost state requires
approved history reconciliation under #9. This is not a second authoritative backup store.

**Operator choices, not installed settings:** encrypted off-host copies, nightly/pre-update
backups, retention and recovery-key custody are recommended. Select destination, encryption
tool/recipient, tolerated loss/downtime and expiry privately. Keep keys available independently
of the failed Docker host. No cloud account, live schedule, upload or automatic deletion is
configured. Older backups retain deleted material until their agreed disposal; retiring them
after sensitive deletion sacrifices those recovery points and cannot erase uncontrolled copies.

## Explicit update and compatible-image rollback

Before an update, create and verify a private snapshot, record source commit, image ID,
schema/migration compatibility, project, config and known public-state checks. Keep prior
release images. Review release notes and
migrations. Stop admissions/quiesce bounded work when jobs exist; that stage is not implemented
by the foundation. Stop the app before changing schema; ordinary startup never migrates.

```sh
# Keep the original project name, config and secrets; record the old exact image ID.
docker compose stop app
# Obtain/review the new source using the organisation's normal Git workflow.
# Persist COMMONS_APP_IMAGE=commons:reviewed-new-revision in this instance's config; source it.
docker compose build app
docker compose run --rm migrate
docker compose up -d --wait --no-build app
# Verify authenticated API/UI, exact prior state/identity/receipt replay, then new writes.
```

If migration/build/readiness fails, stop and preserve logs/storage. Do not promise the prior
binary can operate after every schema change. Roll back **only** when the previous and current
images are documented/tested compatible with the actual schema and retained payload formats:

```sh
docker compose stop app
# Persist COMMONS_APP_IMAGE=<recorded old image ID> in config; source it.
docker compose up -d --wait --no-build --pull never app
# Repeat exact state/identity/replay and new-write checks.
```

Do not run old migrations to downgrade, delete volumes, change PostgreSQL major versions or
restore data as a rollback shortcut. Incompatible-schema downgrade is unsupported: keep the
app stopped and seek a reviewed roll-forward fix. Future jobs/handler pins and conversation
deletion tombstones require their own lifecycle evidence once delivered; this foundation
does not establish their update compatibility. No backup subsystem or restored-authority
machinery is added by this procedure.

## Remaining installation stages

Run `python3 tests/compose_lifecycle.py --app-image commons:REVIEWED_TAG --verify-retrieval` after building
all three images and installing the browser prerequisites in [testing](testing.md).
It creates random disposable projects only; cleanup deletes only their volumes. Do not
point testing at a real installation. It is distinct from `scripts/testing/run verify`.
Add `--compatible-image IMAGE` to exercise two distinct reviewed images with the same
migration set, and `--incompatible-image IMAGE` to verify schema refusal. Two tags pointing
to one image are rejected as rollback evidence; a historical pair does not prove future
schema-change rollback compatibility.
Final acceptance must run against the schema10 candidate, large documents/binary/history
and capture/deletion behavior; storage acceptance alone does not complete #9.

Clean-host and actual Docker Desktop/CPU-architecture claims need their own executed
evidence; a prepared Linux Orb is not the Mac. No Mac access or changes are implied.
Cloud comparison/adopter instructions remain later, nonblocking #7 work: compare self-managed
versus managed PostgreSQL for pgvector/version/roles, verified TLS/private networking,
capacity, backups/PITR/restore portability, maintenance and total cost. Current SQLx build
does not enable TLS, so managed PostgreSQL is not yet a drop-in alternative. No provider
selection, purchase or public exposure is made here. Do not close all #7 from this local stage.
