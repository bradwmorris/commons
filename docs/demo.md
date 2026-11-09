# Synthetic Commons demo

The fresh schema10 seed/reseed implementation is repaired. An isolated Compose
check passed **nine records and nine explained links**, exact saved snapshots,
preservation of a later edit, no duplicates and cleanup. See
the bounded seed evidence.
That check exercised the seed function against a disposable Compose API; it did
not verify native Amp startup or the protected-portal flow below.

**Legacy demo state requires explicit migration review.** Existing receipt state
from the older seed refuses changed payloads before mutations or service commands.
Do not remove its state or regenerate keys to bypass that refusal. Use a fresh
isolated demo for the schema10 path.

The fictional fixture contains a studio, coffee customer, contact, four Notes,
two valid Tasks and nine explained connections. It is not a production deployment
or full release acceptance; no real customer data or conversations are included.

Keep it separate from real organisational work: independent storage, configuration,
credentials and browser sessions. The commands below are the native Amp Orb lane,
not a turnkey standalone Compose demo installer. Start an empty standalone workspace
with [installation and verification](installation-lifecycle.md). The seed check
above does not establish native/protected-portal, clean-host or MCP onboarding.

## Task views

Tasks includes **List** (default) and **Board**, with no view configuration needed.
In List, choose **Due date** alongside Recent/Connected for local-day groups.
Search, project filtering and the completed toggle are shared between views;
completed Tasks are hidden initially. Board supports dragging between status
columns or using each card's status dropdown. Entering Blocked asks for a reason;
rejected/conflicting writes show an error with Reload tasks, never a confirmed move.
Readers can inspect cards but cannot move them. On narrow screens, scroll the
board horizontally; the toolbar wraps. `/tasks?view=kanban` selects Board, and
unknown views recover to List. Views are built-in presentation components over
the same records, not an external plugin system.

## Open and resume

On an Amp Orb, open that installation’s Commons portal. Normal installations use
Commons sign-in. The optional protected-demo mode below instead relies on the
private portal’s authentication and uses one shared synthetic member; it does not
establish individual viewer identity.

Opening the portal wakes a sleeping Orb. If a service needs repair, run:

```sh
.agents/resume
amp orb services ensure
```

Keep `.commons/` and this checkout. Resume/ensure never reseed, migrate or reset data.
Inspect `amp orb service logs commons` and `commons-db` if readiness fails. After a
reviewed source update, rebuild with `.agents/setup`, explicitly run `scripts/dev-init`
only when a reviewed migration is needed, then `amp orb service restart commons`.

## Explicit protected-demo mode

On this isolated synthetic installation, after confirming the external portal is private:

```sh
scripts/demo protect
amp orb service restart commons
```

This writes ignored `.commons/protected-demo.json`, pinned to the current portal origin
and existing member ID. It never seeds, migrates or changes saved Objects. Normal installs
and Compose remain password/session/bearer authenticated by default. Remove that config
and restart to disable the mode; its demo-issued sessions then become invalid. Never
make this portal public or expose its local proxy outside the protected Orb.

`COMMONS_PROTECTED_DEMO_USER` is the explicit server setting. It requires an active
member (never admin), forces the listener onto IPv4 loopback, and issues a normal
HttpOnly/SameSite cookie on HTML navigation only (Secure for HTTPS). No credential is
embedded in assets or URLs. API requests never auto-authenticate; bearer scopes,
revocation, revision checks and browser mutation Origin checks remain enforced.
Expired demo sessions renew by reloading, without showing a login form.

The trust boundary is Amp's **external authenticated portal and the isolated Orb**,
not `X-Amp-*`, Host or forwarded headers: Commons trusts none of them as identity.
The local Amp proxy merely forwards traffic; local Orb processes can access the demo.
The owning Orb's hairpin URL bypasses Amp sign-in, so it alone cannot prove ingress
protection. Check the real external route anonymously as well as through an authenticated
portal browser. This mode is not production SSO or a publicly usable anonymous installation.

## Create or replay the sample data

For a new empty development Orb, after `.agents/setup`:

```sh
scripts/demo init
```

This explicitly starts the guarded native database, migrates, bootstraps a synthetic
administrator, starts the supervised API/UI and seeds through authenticated HTTP.
It refuses to adopt existing native storage without its demo marker. Generated credentials
are private ignored `.commons/demo.json`; no secret is printed by initialization/seeding.
The member account can edit; the reader account cannot mutate. The admin is separate.

`scripts/demo seed` replays stable credential-scoped receipts. It creates no repeated
records or edges and does not overwrite subsequent UI/agent edits. Preserve its seed token
and record IDs; a revoked/expired seed credential fails rather than silently creating a
new namespace. Seeding is explicit, never a startup/resume side effect. This is not an
import, deduplication or backup feature. Do not remove storage to repair a seeding error.

## External-agent HTTP access

In the protected demo, issue a scoped credential in Access. Normal installations first
sign in as the intended named member. Give an
agent only the needed write kinds (for the example, Memory and Note); reads cover the
shared synthetic organisation. Store the token in the client's private secret file or
secret manager, not a prompt or command argument. The agent uses bearer HTTP:

1. `GET /api/contract` discovers routes, scopes, limits and supported operations.
2. Search `GET /api/objects?q=Kestrel&kind=memory`, then explicitly read useful records.
3. Use `POST /api/apply` with `commons/0.1`, a stable idempotency key and supported
   operations. Updates need the current expected revision; relationships authorize and
   advance both endpoints. Lost-response replay must use exactly the same key/body.
4. Read back saved IDs, attribution and links. A second agent with a separate read-only
   credential can retrieve them without receiving the first agent's conversation.

See the [HTTP contract](foundation-api.md) for payloads. This milestone uses actual
external Amp agents over HTTP, not MCP/native Commons tool integration. No agent loop,
model provider, inference credential or arbitrary execution is installed in Commons.

An external Orb also needs Amp portal authentication. The supported
`thread_portal_login_url` tool can mint a single-use URL for that exact private portal;
consume it immediately with a private cookie jar, then call the API with the separate
Commons bearer token. Do not publish the portal or reuse another session's credentials.
The owning Orb can use its own portal URL directly; that shortcut does not prove an
external client connection. Never put a bearer token on the portal login request or
forward it across redirects. Revoke temporary evaluation credentials after the journey.

## Evidence boundary

Run [the shared verification suite](testing.md) against its own disposable cluster.
It intentionally refuses an occupied native port: stop **this Orb's own** demo API/DB
temporarily before `scripts/testing/run verify`, then restore them with ensure. Never
reuse the demo database as test storage or stop a neighboring service. Exact delivery,
screenshots, real-agent results and remaining gaps belong in Issue #1 and the dated
milestone evidence, not a claim that all V1 features exist.
