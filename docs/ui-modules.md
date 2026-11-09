# UI views

Commons presents the same records in several ways. A view is not another
datastore: the list, board, detail and graph all read canonical Objects and
Connections through the authenticated API.

## Available now

| View | Purpose |
| --- | --- |
| Objects and typed lists | Search, sort and open Tasks, Memories, Notes, Entities and Users |
| Task List | Inspect work, filter by project, and optionally include completed Tasks |
| Task Due date | Group the list by due date in the browser's local timezone |
| Task Board | Show the same filtered Tasks by status; move cards by drag/drop or status selector |
| Object detail | Read/edit supported fields, inspect evidence, relationships, revision and audit |
| Connections | Explore explained relationships and open their endpoint records |
| Access | Manage your agent credentials; administrators can create named users |

Select **Board** in Tasks, or open `/tasks?view=kanban`. List and Board share
search, project and completed filters. Cards open the ordinary Task detail;
switching views does not create or copy records. Unknown Task view IDs fall
back to List with a notice.

## Writes stay on the API

Editors send the current revision and preserve fields they are not changing.
Board moves use the same update operation as other edits. Entering In progress
needs a brief; the Board asks for a reason when moving to Blocked. Required
Task dates remain required in every view. GitHub Issue links are optional and
must be canonical when supplied.

The server decides whether a write is allowed. Readers see read-only controls;
hiding a button is not the permission check. A failed or conflicting write is
not a confirmed local change: inspect the error and reload/reconcile. Connections
can be inspected in the UI, but creation currently requires the API.

## Extending the UI

Views are currently **built-in trusted React code**, compiled with the app.
Commons does not yet supply an external UI-module registry, manifest format,
plugin SDK or composition command. Do not assume an upstream module package
can be installed unchanged.

For a new built-in view, reuse the shared records, API client, navigation and
revision checks. Keep secrets out of browser bundles and permission enforcement
on the server. Review, build and test the change; installing a new bundle is a
separate deployment action. A different presentation should not introduce
parallel Task storage or a second mutation contract.

See the [frontend reuse inventory](../web/REUSE.md), [API](foundation-api.md)
and [testing guide](testing.md) for implementation and verification details.

## Optional Publishing view

`VITE_PUBLISHING_CALENDAR_URL` adds an installation-specific Publishing navigation
item and embeds its existing calendar. With no build value, both the navigation
item and route are disabled. This does not move calendar data into Commons or
grant publishing authority. The calendar must allow the Commons origin as a frame
ancestor. Docker builds accept the same optional build argument.
