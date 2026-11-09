# Host capture for Codex and Amp

This opt-in adapter extends the [existing capture outbox](capture.md), not knowledge
access. It runs on a durable macOS/Linux host with the user's installed Codex and
Amp CLIs. Amp exports can include Orbs; no capture credential or delivery daemon
is needed inside an Orb. Everyone authenticated in the destination can read saved
conversations. Keep routing policy and credentials in private adopter configuration.

## Routing and mixed conversations

The agent applies its existing business-versus-personal instructions. Repository
paths never enable capture. Each human turn must have a `business`, `personal` or
`mixed` decision. The first business decision creates a durable thread association;
subsequent decisions belong to that association. Personal, mixed and unclassified
turns are excluded in full, including the human prompt. Split a mixed request into
separate turns to capture the business portion. Repeated personal/mixed decisions
for one turn preserve the first exclusion receipt without stopping the source. A conflict involving business still stops
the source and fences pending delivery for explicit reconciliation.
No new classifier or model call runs in the capture software. Routing remains
agent-attested, not a privacy proof.

For Codex, add an instruction to run the installed command at the start of each
human turn, before substantive work:

```sh
python3 /absolute/install/auto_capture.py --state /absolute/private/state route business
```

Choose the domain from the existing organisation policy; never hardcode business
for every turn. The command uses `CODEX_THREAD_ID` and finds the current persisted
turn through the read-only app-server. It does not resume the thread. If the command
fails, capture stays absent; report the failure without copying the transcript by
hand. User selection is not required on each thread.

For local Amp, open a terminal in the project where you want routing. Copy the
reviewed plugin into that project's plugin directory:

```sh
mkdir -p .amp/plugins
cp -n /absolute/install/amp-route.ts .amp/plugins/commons-capture.ts
amp plugins list
```

Check that `commons-capture` is active and start a new thread with
`amp --executor local`. If the file already exists, inspect it before replacing
it. For an Orb, use a project plugin available to that Orb or follow the
[Amp personal plugin setup](https://ampcode.com/docs/customize/plugins).
Keep the delivery process and credential on the capture host.
The routing tool records its decision in the stored transcript. Current Amp exposes
plugin tools via `code_exec`; the adapter accepts this exact single-purpose form
(with whitespace/quote variations) and a successful versioned tool result:

```typescript
import { commons_capture_route } from "plugins"
text(await commons_capture_route({ domain: "business" }))
```

Other wrapper programs fail closed. Do not infer a route from quoted text, a tool
result mentioning the tool, repository names or general business keywords.
In an already running test Orb, adding the plugin required restarting that Orb's
processes before the running agent saw it; `amp plugins list` alone was insufficient.
Fresh personal Orbs should load the approved personal plugin at startup. Verify this
on the actual personal installation before claiming rollout complete.

## Activation and scheduled reconciliation

Use Python 3.11+ on macOS or Linux and the CLI for the provider you scan. Use absolute
CLI paths in scheduler configuration. Keep `auto_capture.py` beside
`commons_capture.py`. Install only a reviewed revision; upgrades preserve state.

1. Create an owner-only state directory and a separate 0600 file containing a
   destination-scoped token with only the `thread` write kind on schema 12.
   A knowledge token without that scope cannot upload captures.
   Never put credentials in prompts or Git.
2. Initialize the existing outbox with `commons_capture.py --state STATE init
   --url ORIGIN --installation LABEL`. Run this and the following commands on the
   capture host using `python3` and the installed script path. Replace `STATE`,
   `ORIGIN` and `LABEL` with your private state path, Commons origin and label.
   The destination is immutable.
3. Save a private JSON configuration with these required keys:

```json
{
  "namespace": "operator-chosen-stable-host-identity",
  "domain_label": "Business",
  "codex_home": "/absolute/codex/home",
  "codex": "/absolute/path/to/codex",
  "amp": "/absolute/path/to/amp",
  "token_file": "/absolute/private/capture-token"
}
```

   The current config requires both CLI fields. For an unused provider, use
   `/usr/bin/false` as its executable and always pass the provider flag below.
   For Amp-only setup, point `codex_home` at an empty private directory.
4. Run `auto_capture.py --state STATE activate --config CONFIG
   --acknowledge-shared-readership`. Activation is immutable. Turns begun earlier
   are excluded even if the agent routes them later. Forked Amp messages predating
   the fork are excluded too. Lost state is not permission to reconstruct history.
5. On the capture host, run `python3 /absolute/install/auto_capture.py --state STATE scan --provider codex`.
   Use `--provider amp` for Amp. Check **Threads** after a routed test turn.
   If the scan reports an error, check the configured CLI path, target credential
   and source availability. Schedule the same command on the host, for example
   with a user launch agent every 60 seconds. File locking serializes
   scans/routing/disable; avoid parallel periodic jobs. The source and destination
   must be reachable. A failed lifecycle/discovery check pauses sends safely.
6. Run `python3 /absolute/install/auto_capture.py --state STATE status` to see
   the queue, errors and associations. Inspect it
   after installation, restart and outages. Existing outbox retry commands recover
   terminal failures after reconciliation, preserving their saved body and key.

Run `python3 /absolute/install/auto_capture.py --state STATE disable` to stop
collection and sends. A scan already holding the lock finishes before disable returns. `enable` opens a new activation window; turns
begun while disabled are excluded. Existing queued batches from enabled periods
may then resume. Do not run the manual outbox's `flush` behind these controls.
Source archive/deletion or a destination archive stops that association permanently;
unarchive does not automatically restart it. Destination deletion purges local
pending bodies and keeps the existing replay tombstone. An offline host cannot
observe remote deletion until it reconnects; use the documented local purge for
immediate local cleanup. Never automatically reconnect restored state.

Uninstall: disable, remove only this adapter's scheduler and routing additions,
revoke its capture credential, then reconcile/purge its private pending state.
Preserve knowledge connectors, unrelated plugins and vendor originals. Saved
Commons conversations remain until explicitly deleted.

## Fidelity and limits

Tested source interfaces: Codex CLI 0.157.0 and Amp
0.0.1792886472-ge1e052, 25 October 2026. Their formats are version-sensitive.

* Codex: original visible `response_item` messages/function/custom calls/results
  from active local session JSONL, plus distinct persisted nested tool completion
  events. The app-server supplies lifecycle/path metadata with full pagination.
  Internal instructions and reasoning are excluded. Duplicate display messages
  are not re-imported. Nested activities retain their recorded completion order;
  start/completion source timestamps remain attached to the paired records.
* Amp: supported `threads list --json --limit/--offset` and `threads export ID`.
  Role-user tool results are kept as tools, not invented human turns. Streaming
  blocks wait until complete. Hidden blocks and thinking are excluded. Source tool
  results can already be summarized/reformatted by Amp; exporting a payload is not
  proof of every visible byte. Original wrapper arguments/results remain visible.
* Ordinary persisted text transcripts are included. **Voice-only realtime timeline
  transcripts are unsupported** by this adapter; original audio is unavailable.
  No live voice acceptance is claimed. Attachments are not fetched from transcript
  URLs or paths; available placeholders and coverage state this explicitly.
* Known credential patterns and the configured capture token are redacted before
  queueing. This is not a universal detector of arbitrary secrets in prose. Do not
  print secrets into a captured business turn. Personal/mixed routing excludes the
  entire turn rather than attempting to redact personal paragraphs automatically.
* Individual bodies over 1 MiB become explicit unavailable markers. Source exports
  over 64 MiB stop with an error. Batches have at most 50 items and approximately
  4 MiB; the original 32 MiB/500-batch pending queue cap remains. A full queue leaves
  the cursor retryable. Changes/removal of already captured source items stop
  delivery for reconciliation; they are not silently overwritten.
* Only transient pending bodies are stored locally, alongside routes, hashes and
  cursors. Acknowledged bodies are removed by the existing outbox. Stable source
  IDs and deterministic item IDs preserve replay across restarts and credentials.

A successful `scan` against a synthetic source is not proof of personal-plugin or
Codex-global instruction rollout. Keep source tests, real-client synthetic evidence
and production installation/acceptance distinct. See the requirement brief.

### Optional participant attribution

For a dedicated single-person client, an operator may explicitly configure
`"speaker_ids": {"codex": {"human": "USER_UUID", "agent": "AGENT_UUID"},
"amp": {"human": "USER_UUID", "agent": "AGENT_UUID"}}` before activation.
Use existing destination User IDs and obtain the user's agreement to the mapping.
This is supplied attribution, not verified authorship. Do not use a role mapping
for shared/multi-person client histories. Omitted mappings leave speakers unknown;
tools never inherit a person or agent. Configuration is immutable after activation,
and earlier captures are not rewritten. The server validates User references and
Thread pages expose them as participant links.
