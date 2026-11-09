import type { CSSProperties } from "react";
import { projectPresentation } from "./taskProject";
import { AttributionStack } from "./RecordVisuals";
import type { ObjectVisual, RecordObject, Task } from "./types";
import "./taskIdentity.css";

export function taskOf(object: RecordObject): Task {
  const text = (value: unknown) => typeof value === "string" ? value : "";
  return { object_id: object.id, title: object.title, status: object.fields.status as Task["status"],
    owner_object_id: text(object.fields.owner_object_id), due_at: text(object.fields.due_at),
    github_issue_url: text(object.fields.github_issue_url), body: object.body, project: text(object.fields.project),
    work_kind: object.fields.work_kind as Task["work_kind"] };
}

export function TaskAssignee({ task, visuals }: { task: Pick<Task, "object_id" | "owner_object_id">; visuals: ReadonlyMap<string, ObjectVisual> }) {
  if (!task.owner_object_id) return <span className="task-assignee missing" aria-label="Unassigned">♙</span>;
  const user = visuals.get(task.object_id)?.users.find((u) => u.role === "owner" && u.user_object_id === task.owner_object_id)
    ?? visuals.get(task.owner_object_id)?.users.find((u) => u.user_object_id === task.owner_object_id);
  if (!user) return <span className="task-assignee missing" aria-label={`Assigned to unresolved user ${task.owner_object_id}`}>♙</span>;
  return <span className="task-assignee" aria-label={`Assigned to ${user.title}`}>
    <AttributionStack users={[{ ...user, role: "owner" }]} />
  </span>;
}

export function TaskAttribution({ task, visuals }: { task: Pick<Task, "object_id" | "owner_object_id">; visuals: ReadonlyMap<string, ObjectVisual> }) {
  const owner = visuals.get(task.owner_object_id ?? "")?.users[0];
  return <AttributionStack users={[...(visuals.get(task.object_id)?.users ?? []), ...(owner ? [{ ...owner, role: "assigned to" }] : [])]} />;
}

export function TaskIssueLink({ url, showLabel = false }: { url: string | null; showLabel?: boolean }) {
  if (!url || !/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/issues\/[1-9][0-9]*$/.test(url)) return null;
  const label = `Open GitHub issue ${url.slice("https://github.com/".length)}`;
  return <a className="task-github-link" href={url} target="_blank" rel="noopener noreferrer" aria-label={label} title={label} onClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()} draggable={false}>
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M12 .7a11.5 11.5 0 0 0-3.64 22.41c.57.11.78-.25.78-.55v-2.15c-3.2.69-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.23-1.28-5.23-5.69 0-1.26.45-2.29 1.18-3.09-.12-.29-.51-1.46.11-3.05 0 0 .97-.31 3.16 1.18a10.95 10.95 0 0 1 5.76 0c2.2-1.49 3.16-1.18 3.16-1.18.63 1.59.23 2.76.12 3.05.73.8 1.18 1.83 1.18 3.09 0 4.42-2.68 5.4-5.24 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.2.67.79.55A11.5 11.5 0 0 0 12 .7Z" /></svg>
    {showLabel && <span>Open issue</span>}
  </a>;
}

export function TaskReadiness({ task, showComplete = false }: { task: Task; showComplete?: boolean }) {
  const missing = [!task.owner_object_id && "assignee", !task.due_at && "due date", !task.body?.trim() && "brief"].filter(Boolean);
  return missing.length ? <span className="task-readiness" title={`Before execution, add ${missing.join(", ")}`}>Needs {missing.join(", ")}</span> : showComplete ? <span>Details supplied; check brief and dependencies</span> : null;
}

export function TaskProject({ task }: { task: Task }) {
  const project = task.project;
  const { label, short, icon, hue } = projectPresentation(project);
  return <span style={{ "--project-hue": hue } as CSSProperties} className={`task-project-badge project-colour${project ? "" : " missing"}`} aria-label={`Project: ${label}`} title={project ? `Project: ${label}` : "Set one project in task details"}><span aria-hidden="true">{icon}</span><span aria-hidden="true">{short}</span></span>;
}
