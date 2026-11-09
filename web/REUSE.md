# Canonical Context frontend

The shell, collection rows, detail/property/relationship layouts, creation modal,
inline editing, identity controls, visual badges, Task presentation and graph layout
are selectively adapted from `bradwmorris/centaur-context` revision
`91b31f49327f3723b863049d4e5061c072633104`, principally `App.tsx`, `styles.css`,
`RecordVisuals.tsx`, `DescriptionSnippet.tsx`, `ObjectIdentity.tsx`, `InlineEditor.tsx`,
`TaskIdentity.tsx`, `taskIdentity.css`, `taskProject.ts`, `taskDateGroups.ts`,
`ConnectionGraph.tsx`, `connectionGraphLayout.ts`, and `WorkspaceToolbar.tsx`.
Their MIT copyright and permission notice is retained in `CONTEXT-LICENSE`.

`RecordList.tsx` extracts that retained list presentation. `TaskBoard.tsx` and
`taskBoard.css` selectively adapt the same revision's
`modules/taskBoard/TaskBoard.tsx` and `taskBoard.css`: canonical status columns,
cards, identity and due-date presentation. Commons owns shared filtering,
authenticated revision-checked writes, reader gating, URL selection and the native
blocked-reason dialog. These are built-in components, not an external plugin API;
no upstream composition tooling or private overlay is included.

Modifications use Commons branding, authenticated sessions/roles, the `commons/0.1`
API, required new-Task dates and optional canonical Issue links. Subsequent Commons
features use this retained visual language; the inventory describes upstream reuse,
not the complete current feature list.
No deployment configuration, private overlays, records, avatars or screenshots are
included. Reference renders use only the source's synthetic fixture in an isolated
temporary copy; that fixture is not a production API or acceptance of Commons.

New Commons code remains Apache-2.0; these changes do not relicense upstream code.
