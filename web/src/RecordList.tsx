import type { ReactNode } from "react";
// Collection presentation adapted from Context 91b31f4 (MIT); see ../CONTEXT-LICENSE.
import { DescriptionSnippet } from "./DescriptionSnippet";
import { ObjectId } from "./ObjectIdentity";
import { AttributionStack, ObjectTypeBadge, TaskStatusBadge } from "./RecordVisuals";
import { TaskAttribution, TaskIssueLink, TaskProject, TaskReadiness, taskOf } from "./TaskIdentity";
import { formatTaskDueDate, type TaskDateGroup } from "./taskDateGroups";
import { interceptNavigation, objectPath, sections, type Section } from "./routing";
import type { ObjectVisual, RecordObject } from "./types";

export function RecordList({ objects, groups, visuals, section, now, loading, error, query, children }: {
  objects: readonly RecordObject[]; groups: TaskDateGroup[] | null;
  visuals: ReadonlyMap<string, ObjectVisual>; section: Section; now: Date;
  loading: boolean; error: string; query: string; children?: ReactNode;
}) {
  const renderRecord = (object: RecordObject) => {
    const task = object.kind === "task" ? taskOf(object) : null;
    const seconds = Math.max(0, Math.round((now.getTime() - new Date(object.metadata.created_at ?? "").getTime()) / 1000));
    const created = !Number.isFinite(seconds) ? "—" : seconds < 60 ? "now" : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)}h ago` : `${Math.floor(seconds / 86400)}d ago`;
    return <div className={groups ? "record due-date-record" : "record"} key={object.id}>
      <a className="record-open" href={objectPath(object.id)} onClick={event => interceptNavigation(event, objectPath(object.id))} aria-label={`Open ${object.title}`} />
      <span className="record-kind">{section === "tasks" && task ? <TaskProject task={task} /> : <ObjectTypeBadge kind={object.kind} compact />}</span>
      <span className="record-id"><ObjectId id={object.id} rowPill /></span>
      <span className="record-main"><span className="record-title"><strong>{object.title}</strong>{task && <TaskStatusBadge status={task.status} />}</span><span className="record-source" />
        <span className="record-users">{task ? <>{section !== "tasks" && <TaskProject task={task} />}<TaskAttribution task={task} visuals={visuals} /><TaskIssueLink url={task.github_issue_url} /><TaskReadiness task={task} /></> : <AttributionStack users={visuals.get(object.id)?.users ?? (visuals.get(object.metadata.created_by ?? "")?.users ?? []).map(user => ({ ...user, role: "created by" }))} />}</span>
      </span><DescriptionSnippet description={object.description} /><time dateTime={groups && task ? task.due_at! : (object.metadata.created_at ?? "")}>{groups && task ? formatTaskDueDate(task.due_at, now) : created}</time>
    </div>;
  };
  const byId = new Map(objects.map(object => [object.id, object]));
  const count = groups ? groups.reduce((sum, group) => sum + group.tasks.length, 0) : objects.length;
  return <section className="list-view" aria-label={`${section} records`} aria-busy={loading}>
    {loading && <p className="muted" role="status">Loading {sections[section].toLowerCase()}…</p>}
    {groups ? <div className="task-date-groups">{groups.map(group => <section className="task-date-group" aria-label={`${group.label} tasks`} key={group.key}><div className="list-group-head"><strong>{group.label}</strong><span>{group.tasks.length}</span></div><div className="record-list">{group.tasks.map(task => renderRecord(byId.get(task.object_id)!))}</div></section>)}</div> : <><div className="list-group-head"><span className="status-ring" /><strong>{section === "objects" ? "Objects" : `All ${sections[section].toLowerCase()}`}</strong><span>{count}</span></div><div className="record-list">{objects.map(renderRecord)}</div></>}
    {!loading && !error && count === 0 && <div className="empty-list">{query.trim() ? "No active objects match your search." : "Nothing here yet."}</div>}
    {children}
  </section>;
}
