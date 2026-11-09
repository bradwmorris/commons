# Overlay inventory

An optional, read-only workspace view for signed-in members and administrators. It shows the reviewed
AGENTS.md files, skills, tool documentation and workflow guides from one overlay
commit. Each entry shows its repository-relative path. The view displays source as
text and does not run instructions or discover installed tools.

## Enable it for one installation

1. Commit the overlay's definitions. Use `AGENTS.md`,
   `projects/<project>/AGENTS.md`, `.agents/skills/<skill>/SKILL.md`,
   `docs/tools.md`, and `docs/workflows.md` in the overlay repository. Existing
   `docs/integrations.md`, `docs/tool-ownership.md`, `tools/<tool>/README.md` and
   `docs/<name>-workflow.md` are also eligible.
2. From the Commons checkout, export a snapshot into a private directory owned by
   the installation operator. Use the exact `COMMONS_INSTALLATION_NAME`. For example:

   ```sh
   umask 077
   scripts/export-overlay-inventory /path/to/overlay "My organisation" > /path/to/private/draft.json
   ```

3. Review every entry before enabling the view. Use `--exclude <relative-path>`
   for definitions that should stay outside Commons. The exporter reads regular
   Markdown blobs from the committed tree and skips symlinks and untracked files.
   It omits lines containing recognized home-directory paths and rejects common
   credential formats. Review for other sensitive material. The snapshot contains
   the committed text and commit hash, so refresh it after changes you want to show.
4. Move the reviewed file to its final location. For native serve, set
   `COMMONS_OVERLAY_INVENTORY_FILE` to that file and restart the app. For Compose,
   source the installation config, set `COMMONS_OVERLAY_INVENTORY_SNAPSHOT` to the
   absolute host file path, and add the optional Compose file to the same invocation
   you already use for the installation. Ensure the container user can read the file
   while keeping its parent directory private on the host.

   ```sh
   docker compose -f compose.yaml -f docker/overlay-inventory.compose.yaml \
     up -d --no-deps --no-build --pull never app
   ```

   Keep the override in future app recreations for this installation. Each
   installation needs its own snapshot and mount. The inventory is disabled in protected demo mode. A mismatched installation name
   or an unreadable snapshot makes the inventory unavailable while Commons serves
   normally. An empty category is shown as such.
5. Sign in as a member or administrator and open **Inventory**. Check the commit and expand
   a file. To disable it, remove the native setting or Compose override and
   recreate the app. The default Commons installation has no Inventory view.

## Author concise instructions

Keep root AGENTS.md to rules that apply to the workspace and links that tell the
agent when to open project guides. Put a repeated procedure in the skill that owns
it. State its trigger and boundaries in the description. In the body, give the
short path, the check that establishes completion, and direct references for
conditional detail. Leave API arguments and permissions with the live tool
contract. Measure successful work and correct discovery when changing guidance.

Use a local limit of **6,000 characters per `SKILL.md`**. Count Unicode code
points in the entire UTF-8 file, including YAML, Markdown syntax, spaces, tabs,
comments, examples and the final newline if present. Normalize CRLF to LF before
counting. A combining mark counts separately. Linked files have their own
purpose and are outside this count. The limit is a Commons authoring rule.

From Commons, run `scripts/check-skill-length --root /path/to/overlay` while
editing. New and changed skills above the limit fail. Existing unchanged
over-limit files show warnings. Use `--base <commit>` to check a committed
change relative to its review base. The check covers the usual `skills/` and
`.agents/skills/` directories. Run the overlay's existing structural and
behavior checks as well.
