---
name: commons-evals
description: Save reusable tasks or research requests and compare independent external attempts with and without Commons knowledge, for human inspection.
---

# Commons comparisons

Use the installation's authenticated `/api/contract`, then the [eval contract](../../docs/evals.md).
The coordinator keeps its normal Commons connection. Test agents must never receive
that connection, browser session, accumulated conversation, previous results or its
credential files. Commons stores evidence; it does not start or sandbox agents.

1. Search `GET /api/evals?q=...` and read a matching test. Reuse its exact version or
   append a new version when inputs change. Record exact request, baseline model and
   settings, ordinary tools, permitted actions, starting file hashes and any limits
   in `configuration`. Do not add a rubric, score, judge or quality verdict.
2. Prepare a frozen knowledge bundle from relevant full Commons records/evidence.
   Include source IDs/revisions and omissions. Read the selected evidence, exclude
   eval outputs, answer keys and captured trial transcripts. Review for accidental
   prior-result contamination. The server preserves supplied text; it cannot prove
   that the coordinator selected clean knowledge. Do not save eval outputs as Notes,
   Memories, ordinary Artifacts or captured conversations.
3. Create a run pinned to the chosen version and bundle. For treatment, generate a
   random `cet_` + 32-byte hex secret outside records/logs, validate and grant it via
   `grant_context`. Supply only that capability and `GET /api/eval-context` to the
   treatment environment. It returns frozen organisational knowledge; it is not
   live search. Baseline receives no Commons credentials or reachable authenticated
   connector. Never substitute a normal read-only token: it can read all results.
4. Use the execution environment's existing facilities to start **two fresh,
   independent sessions** with no inherited history. Record actual client/version,
   model/settings, tool inventories and session IDs. Use separate equivalent file
   copies and verify initial hashes before either session starts. Give both exactly
   the saved request and ordinary inputs; treatment additionally gets the restricted
   knowledge capability. Neither may see the other's workspace or saved output.
   No duplicated live sends, purchases, deployments or record writes are authorised.
5. Verify access, not intentions: baseline cannot authenticate to Commons; treatment
   can read `/api/eval-context` but receives 401 on `/api/evals`, `/api/eval-runs/{id}`,
   `/api/objects`, `/api/chats`, `/api/runs`, `/api/artifacts/{id}`, `/api/retrieve` and
   mutation routes. Neither can reach the coordinator's files, cookies or connectors.
   Disable capture into the tested corpus. If the host exposes shared filesystem
   secrets or undeactivatable connectors, **stop trial execution** and record
   `isolation: unsupported`; asking the agent to ignore access is insufficient.
6. Automatic path: use existing supported fresh-session and tool/profile controls
   only after verifying those boundaries. Guided manual path: an operator creates
   two isolated client profiles/containers with matching ordinary tools and separate
   file copies, removes inherited connectors/credentials, configures only the
   treatment capability, verifies the denials above, and returns outputs/session
   evidence to the coordinator. Do not build or require a special runner. If neither
   path is available, retain pending/failed/partial evidence and report the blocker.
7. Save each attempt through `append_attempt`, with expected run revision and a
   stable key/body. Include raw output, operational status, actual error, session ID,
   evidence and honest `verified` / `unverified` / `unsupported` isolation. These are
   caller reports, not server certification. Save UTF-8 produced files inline or
   HTTPS links for other products; verify linked bytes/access for both readers.
   Every update/retry of execution is a new attempt; transport replay uses the old
   key/body and does not duplicate it. Preserve earlier failures. Validate first,
   execute, then read back. Reconcile unknown writes before changing keys.
8. Revoke all run capabilities when execution ends. Open the stable run link as two
   named users; inspect exact request, both outputs, products and expandable evidence.
   No form or grading is required. Operational completion means outputs were saved,
   not that Commons improved them. Record client limitations; do not generalise one
   real-client journey to all vendors. Deterministic API/browser fixtures are not
   evidence that external agents executed independently.

Synthetic examples: research outreach to fictional Lantern from a supplied brief;
produce `briefing.md` from that same brief in separate starting copies. Private
organisation notes and real outreach stay outside source/test fixtures.
