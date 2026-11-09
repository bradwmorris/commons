# Pi conversation capture

MCP works independently of this optional extension. The extension runs inside Pi,
uses a local Python bridge and sends through the shared Commons capture API. Everyone
signed in to the target installation can read what is saved.

1. On the Pi computer, keep `pi-capture.ts`, `pi_capture.py`,
   `commons_capture.py` and `auto_capture.py` from the same reviewed
   `integrations/capture/` revision in one directory. Install Python 3.11+.
2. In Commons **Access**, issue a separate credential with only **Thread** write
   access. Save it in a private file with mode 0600. In another private file,
   create this JSON. Replace the values with your origin, stable labels, paths
   and active User IDs from the same Commons installation. Omit `speaker_ids`
   if you cannot confirm the mapping.

   ```json
   {
     "url": "https://commons.example",
     "installation": "your-installation-label",
     "namespace": "your-stable-host-label",
     "state": "/absolute/private/pi-outbox",
     "token_file": "/absolute/private/pi-capture-token",
     "speaker_ids": {
       "human": "HUMAN_USER_UUID",
       "agent": "PI_AGENT_USER_UUID"
     }
   }
   ```

3. In the terminal that starts Pi, point it at the config and bridge. Load the
   extension for this invocation. Leave MCP and built-in extensions enabled.
   If `pi` is a local wrapper, check that it preserves these variables. For a test
   installation, launch the unwrapped Pi executable if the wrapper overrides them.

   ```sh
   export COMMONS_PI_CAPTURE_CONFIG=/absolute/private/pi-capture.json
   export COMMONS_PI_CAPTURE_BRIDGE=/absolute/install/pi_capture.py
   export COMMONS_PI_PYTHON=/absolute/path/to/python3
   pi -e /absolute/install/pi-capture.ts
   ```

4. Give the agent your organisation's routing rule. In a new test session, ask
   it to route an entirely business turn and call a Commons tool. The
   `commons_capture_route` result should show business and enabled. A new
   **Thread** should show the prompt, visible reply and paired tool activity.
   Under **Traces → Other executions**, open the matching `pi-events`
   execution. Check the Thread link, turn and tool call ID. These timestamps
   come from the extension's observations.
5. Send a personal test turn and check that it was excluded. Personal, mixed
   and unclassified turns are excluded in full. Capture starts from live hooks.
   Earlier sessions, attachment originals and hidden reasoning are outside this
   path. A crash before the turn settles can omit the turn.

If the route tool is missing, restart Pi with `-e`. If a routed turn fails to
appear, check Python, the config and the **Thread** credential. From the terminal,
run `python3 /absolute/install/commons_capture.py --state /absolute/private/pi-outbox status`
to inspect pending batches. Follow the [outbox guide](capture.md) for recovery.

To disable, exit Pi and restart without the extension and capture variables.
If you installed a persistent copy in the Pi extensions directory, remove that
copy too. Reconcile pending state before removing it. Saved Threads remain in Commons.
