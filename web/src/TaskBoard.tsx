// Kanban presentation adapted from Context 91b31f4 (MIT); see ../CONTEXT-LICENSE.
import { useEffect, useRef, useState } from "react";
import { TaskAttribution, TaskIssueLink, TaskProject, TaskReadiness, taskOf } from "./TaskIdentity";
import { formatTaskDueDate } from "./taskDateGroups";
import { interceptNavigation, objectPath } from "./routing";
import type { ObjectVisual, RecordObject, TaskStatus } from "./types";
import "./taskBoard.css";

const columns: { status: TaskStatus; label: string; icon: string }[] = [
  { status: "backlog", label: "Backlog", icon: "◌" },
  { status: "todo", label: "Ready", icon: "○" },
  { status: "doing", label: "In progress", icon: "◐" },
  { status: "review", label: "Review", icon: "◇" },
  { status: "blocked", label: "Blocked", icon: "!" },
  { status: "done", label: "Done", icon: "✓" },
];

export function TaskBoard({ objects, visuals, loading, loadError, writable, showDone, now, changeStatus, reload }: {
  objects: readonly Readonly<RecordObject>[]; visuals: ReadonlyMap<string, ObjectVisual>;
  loading: boolean; loadError: string; writable: boolean; showDone: boolean; now: Date;
  changeStatus(task: Readonly<RecordObject>, status: TaskStatus, blockedReason?: string): Promise<void>;
  reload(): void;
}) {
  const [movingId, setMovingId] = useState<string | null>(null);
  const moving = useRef(false);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [blockingTask, setBlockingTask] = useState<Readonly<RecordObject> | null>(null);
  const [blockedReason, setBlockedReason] = useState("");
  const [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!blockingTask) return;
    const element = dialog.current!;
    const previousFocus = document.activeElement as HTMLElement | null;
    element.showModal();
    return () => { element.close(); previousFocus?.focus(); };
  }, [blockingTask]);
  const disabled = !writable || loading || !!loadError || movingId !== null;
  const moveTask = async (task: Readonly<RecordObject>, status: TaskStatus, reason?: string) => {
    if (disabled || moving.current || task.fields.status === status) return;
    moving.current = true; setMovingId(task.id); setError("");
    try {
      await changeStatus(task, status, reason);
      setBlockingTask(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Task could not be moved.");
    } finally {
      moving.current = false; setMovingId(null); setDraggingId(null);
    }
  };
  const requestMove = (task: Readonly<RecordObject>, status: TaskStatus) => {
    setDraggingId(null);
    if (disabled || task.fields.status === status) return;
    if (status === "blocked") { setBlockingTask(task); setBlockedReason(""); setError(""); }
    else void moveTask(task, status);
  };
  const errorMessage = error && <div className="board-error" role="alert"><span>{error}</span><button type="button" onClick={() => { setBlockingTask(null); setError(""); reload(); }}>Reload tasks</button></div>;
  return <section className="task-board" aria-label="Task board" aria-busy={loading}>
    {!blockingTask && errorMessage}
    {loading ? <div className="board-loading" role="status">Loading tasks…</div> : <>
      {!loadError && !objects.length && <div className="board-loading" role="status">No tasks match this view.</div>}
      <div className="task-board-columns" tabIndex={0} aria-label="Task status columns">
        {columns.filter(column => showDone || column.status !== "done").map(column => <section className={`task-column ${column.status}`} aria-label={`${column.label} tasks`} key={column.status}
          onDragOver={event => { if (!disabled && draggingId) event.preventDefault(); }} onDrop={event => {
            event.preventDefault(); const task = objects.find(object => object.id === draggingId);
            if (task) requestMove(task, column.status);
          }}>
          <header><span className="column-status" aria-hidden="true">{column.icon}</span><strong>{column.label}</strong><span>{objects.filter(object => object.fields.status === column.status).length}</span></header>
          <div className="task-column-cards">{objects.filter(object => object.fields.status === column.status).map(object => {
            const task = taskOf(object);
            return <article className={`task-board-card${movingId === object.id ? " moving" : ""}`} key={object.id} draggable={!disabled}
              onDragStart={event => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", object.id); setDraggingId(object.id); }} onDragEnd={() => setDraggingId(null)}>
              <a className="task-card-open" href={objectPath(object.id)} onClick={event => interceptNavigation(event, objectPath(object.id))} aria-label={`Open ${object.title}`} draggable={false} />
              <div className="task-card-title"><span className={`priority-dot ${object.fields.priority}`} title={`${object.fields.priority} priority`} /><strong>{object.title}</strong></div>
              {object.description && <p>{object.description}</p>}
              {typeof object.fields.blocked_reason === "string" && object.fields.blocked_reason && <p className="task-blocked-reason"><strong>Blocked:</strong> {object.fields.blocked_reason}</p>}
              <TaskProject task={task} /><TaskReadiness task={task} />
              <footer><div className="task-card-meta"><TaskIssueLink url={task.github_issue_url} /><time className={`task-due${task.status !== "done" && new Date(task.due_at!).getTime() < now.getTime() ? " overdue" : ""}`} dateTime={task.due_at ?? undefined}>{formatTaskDueDate(task.due_at, now)}</time></div>
                <div className="task-card-actions"><TaskAttribution task={task} visuals={visuals} /><select aria-label={`Move ${object.title}`} value={task.status} disabled={disabled} onChange={event => requestMove(object, event.target.value as TaskStatus)}>{columns.map(option => <option key={option.status} value={option.status}>{option.label}</option>)}</select></div></footer>
            </article>;
          })}{!objects.some(object => object.fields.status === column.status) && <div className="column-empty">No tasks</div>}</div>
        </section>)}
      </div>
    </>}
    {blockingTask && <dialog className="board-block-dialog" ref={dialog} aria-labelledby="block-task-title" onCancel={event => { event.preventDefault(); if (!moving.current) setBlockingTask(null); }}>
      <form onSubmit={event => { event.preventDefault(); if (blockedReason.trim()) void moveTask(blockingTask, "blocked", blockedReason.trim()); }}>
        <h2 id="block-task-title">Block “{blockingTask.title}”</h2>
        <label>Blocked reason<textarea required maxLength={2000} value={blockedReason} onChange={event => setBlockedReason(event.target.value)} /></label>
        {errorMessage}
        <div><button className="ghost" type="button" disabled={movingId !== null} onClick={() => setBlockingTask(null)}>Cancel</button><button className="primary" type="submit" disabled={disabled || !blockedReason.trim()}>{movingId ? "Saving…" : "Block task"}</button></div>
      </form>
    </dialog>}
  </section>;
}
