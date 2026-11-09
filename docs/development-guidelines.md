# Contributing to Commons

This repository owns the product's code, contracts, build/test machinery and
minimal contributor guidance. It does not require a private operating overlay,
particular agent identity, external Task installation or organisation-specific
planning process.

## Understand the change

Read root `AGENTS.md`, the relevant requirements/architecture and the owning code.
When work has a repository Issue, treat its current agreed outcome and acceptance
as the coordination record; search before creating a duplicate. The
[Issue template](requirements-documents.md) is optional structure for maintainers.
External teams may use their own planning and tracking process.

Keep changes within the owning modules. Preserve unrelated work and existing
history. Product behavior and contracts belong here; installation-specific
identities, destinations, operating procedures and provider integrations belong in
the adopter's private configuration or overlay.

## Implement and verify

Use existing repository patterns and the smallest complete change. Reproduce a
reported bug before fixing it when practical, and test observable public behavior
rather than private implementation details. Follow [testing](testing.md) for the
required commands and prerequisites.

Required PostgreSQL/browser checks must run rather than silently skip. For UI
appearance, inspect affected rendered states. For changed interactions, exercise
the real pointer/keyboard flow. Documentation changes need link/contract checks.
Report exact commands, decisive results, failures, skips and coverage limits.

Review the actual diff—including intended staged, unstaged and untracked files—
against the agreed behavior and repository standards. Fix confirmed in-scope
defects and rerun affected checks. Requirement changes or broader refactors return
to the maintainer rather than being hidden in implementation.

## Deliver safely

Use the branch, pull-request or direct-push procedure authorized by the repository
maintainer for that change. Before delivery, fetch/integrate the current target
without discarding local or others' work and rerun affected checks on the combined
result. Never force-push shared history. Read back the remote revision and report
whether work is local, committed, pushed, merged or deployed—these are distinct.

Source delivery does not authorize deployment, public release, live migration,
provider actions or existing-data changes.
Keep secrets, private records and personal configuration out of source and test
evidence. Preserve Apache-2.0 and applicable upstream notices.

## Optional Issue links in product Tasks

Commons Tasks do not require GitHub Issues. An external workflow may deliberately
pair one repository Issue with one Task using the generic
[`ensure_task` contract](foundation-api.md#issue-task-pairing). That workflow owns
repository selection, owner/date decisions and progress; Commons only validates
the canonical URL, uniqueness, revision, permission and retry behavior. Assignment
does not launch execution, and there is no webhook or automatic synchronization.
