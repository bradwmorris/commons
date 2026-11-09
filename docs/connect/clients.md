# Capture client interfaces and verification limits

The interface table is dated research from 17 October 2026. The later
25 October verification establishes
actual Codex CLI and Amp Orb adapter tests; other clients remain unverified. Ordinary authenticated HTTP
context access remains independent from optional capture.

| Environment | Supported interface to investigate | Limits / manual fallback |
| --- | --- | --- |
| Codex | Trusted hooks and app-server `thread/read`, `thread/turns/list` with `itemsView: full`, `thread/items/list` | Verify the installed Desktop history is available to the adapter without resuming a turn. Hooks omit hosted tools; raw transcript format is unstable; WebSocket transport is experimental. Explicit selected-history normalization or supplied text/files is a labelled fallback. |
| Claude Code, later coverage | Prompt/Stop/tool/subagent/compaction hooks, with session/tool IDs | Transcript writes may lag Stop; final assistant text alone is incomplete. JSONL is internal/version-sensitive. `/export [filename]` supplies readable text, not guaranteed original attachments. SDK/print-mode output does not prove observation of an existing interactive client. |
| Local Amp, later coverage | `session.start`, `agent.start`, `agent.end`, `tool.call`, `tool.result`; `thread.messages({full:true, ...})` | Full history needs paging (maximum 20 messages/page). Verify original attachments, timestamps and multiplayer authors; simplified plugin messages do not establish their completeness. Explicit `amp threads export <thread>` or `markdown <thread>` can supply manual inputs, which must be normalized and stripped of thinking/private configuration. |
| Amp Orbs | Same documented plugin interfaces on the Orb executor | Prove actual loading, restart/pause, compaction recovery, protected attachment bytes and durable outbox behavior. The Orb cannot use the Mac's loopback URL. Connection setup is installation-specific. Authorized manual export remains a fallback, not automatic-capture acceptance. |

Official references:

- [Codex app-server](https://learn.chatgpt.com/codex/app-server)
- [Codex hooks](https://learn.chatgpt.com/codex/hooks)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code sessions/export](https://code.claude.com/docs/en/sessions)
- [Amp plugin API](https://ampcode.com/docs/plugin-api)
- [Amp Orbs](https://ampcode.com/docs/orbs)
- [Amp attachments](https://ampcode.com/docs/orbs/files-and-attachments)

Do not call model APIs, prompt for a generated summary, resume/start a turn, scrape
private endpoints, or transfer provider credentials merely to copy records.
Copying original visible content requires no new inference. Hidden reasoning is
not a completeness requirement and must not be included in normal exports.

The inspected Context bridge at
`91b31f4`
is a design reference for private state, explicit activation/routing, durable
delivery and configuration-preserving installation. Its Codex 0.153.4 parser
only captures completed visible text and omits tools/attachments. Its curation,
Git-derived Memories and old permission policy are not Commons behavior.

## Claude Code

Use the [Connect guide](../site/connect.mdx#claude-code) for MCP. Claude Code
2.1.152 discovered the stdio connector in a disposable configuration. A real
model request using the existing login returned `401 OAuth access token is invalid`.

With a working provider login, repeat the synthetic Source search, exact
Artifact read, Note validation, write and readback in a fresh session. Confirm
the Commons writer ID independently.

Commons has no Claude Code capture adapter. Anthropic's
[hooks](https://code.claude.com/docs/en/hooks) document a session ID and
`transcript_path`, plus events for prompts, tools and stopping. For an adapter
probe, use a disposable project. Register local command hooks for
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure` and `Stop`
through project settings. Log only the event name, session ID, tool-use ID if
supplied and transcript path to an owner-only local file. Start a new synthetic
session with one successful and one failed tool call. Compare the IDs and event
order with the completed transcript. Stop may precede final transcript writes.
Remove those hook entries after the probe. No Commons delivery is configured by
these hooks.

Anthropic separately documents [beta native spans](https://code.claude.com/docs/en/monitoring-usage#traces-beta).
On a build that supports them, set `CLAUDE_CODE_ENABLE_TELEMETRY=1`,
`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` and `OTEL_TRACES_EXPORTER=console` for
one synthetic process. Leave prompt and tool-content logging off. Check for the
prompt root, model and tool spans locally. Remove the variables to disable.
This probe and the hook probe still need an authenticated model turn. The Codex
Commons receiver expects Codex turn IDs and routing, so a Claude exporter cannot
be pointed at that receiver to set up Commons capture.

## Synthetic probe boundary

Use isolated disposable Commons stores and approved synthetic client profiles/
threads. Before any client invocation, record the exact intended profile, source
scope, destination and side effects. Never scan private history or test against a
live store. Use unequal messages/speakers, commentary and final replies, successful
and failed tools, an original small image, text attachment, missing/oversized
attachments, resume/fork/compaction and stop/restart. Compare expected source IDs,
order and exact bytes/hashes with API/UI readback. Test auth rejection, token
rotation, two-store isolation, pending-retry deletion and disabled collection.

Record exact executable versions, commands, passing and blocked cases. Inspect
rendered normal/empty/partial/failed states and record changed interactions.
Do not mark all of #9 complete from synthetic storage/transport evidence.
