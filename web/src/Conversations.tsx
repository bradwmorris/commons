import { useEffect, useState, type ReactNode } from "react";
import { request } from "./api";
import { ThreadSearch } from "./ThreadSearch";
import { NativeTrace } from "./NativeTrace";
import { ObjectId } from "./ObjectIdentity";
import { CaptureRelationships } from "./CaptureRelationships";
import { AttributionStack, ObjectTypeBadge } from "./RecordVisuals";
import { WorkspaceToolbar } from "./WorkspaceToolbar";
import { StoredText } from "./StoredText";
import { interceptNavigation, navigate } from "./routing";
import type { Identity, UserAttribution } from "./types";

type Coverage = { status?: string; messages?: string; tools?: string; attachments?: string; history?: string; gaps?: string[] };
type ChatRow = { id: string; title: string; provider: string; coverage: Coverage; imported: boolean; updated_at: string; participants: UserAttribution[] };
type RunRow = { participants: UserAttribution[]; id: string; kind: string; status: string; source_created_at: string | null; imported: boolean; started_at: string | null; completed_at: string | null; received_at: string; thread_title: string | null; provider: string | null; span_count: number | null };
type Item = { participants: UserAttribution[]; model?: { provider?: string; id?: string }; id: string; kind: string; role: string; speaker_name: string | null; body: string;
  source_created_at: string | null; source_ingested_at: string | null; received_at: string; tool_name?: string; tool_call_id?: string;
  status?: string; artifact_ids: string[]; import_provenance: unknown;
  attachments: { id: string; title: string | null; media_type: string | null; capture_outcome: string; capture_reason: string | null; stored: boolean }[];
  correction: { reason: string; representation: unknown } | null };
type ChatDetail = { participants: UserAttribution[]; chat: { chat_id: string; provider: string; owner_id: string; coverage: Coverage; parent_chat_id: string | null; import_provenance: unknown };
  object: { title: string; revision: number }; items: Item[]; total: number; next_offset: number | null };
type RunDetail = { participants: UserAttribution[]; id: string; kind: string; status: string; parent_run_id: string | null; chat_object_id: string | null;
  actor_id: string | null; source_created_at: string | null; started_at: string | null; completed_at: string | null;
  input: unknown; trace: unknown[]; result: unknown; review: unknown; error: string | null;
  consulted_object_ids: string[]; historical_references: { object_id: string; state: string; purge_evidence: unknown[] }[];
  import_provenance: unknown };

const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "Request failed. Try refreshing.";
const hasRecord = (value: unknown) => value != null && (typeof value === "string" ? !!value.trim() : typeof value === "object" ? !!Object.keys(value).length : true);
const date = (value: string | null) => value ? new Date(value).toLocaleString() : "Not recorded";
function Link({ path, children }: { path: string; children: ReactNode }) {
  return <a href={path} onClick={event => interceptNavigation(event, path)}>{children}</a>;
}
function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="detail-section"><header><h3>{title}</h3></header>{children}</section>;
}
function JsonRecord({ value }: { value: unknown }) {
  return <pre className="source-text-preview">{JSON.stringify(value, null, 2)}</pre>;
}
function Paging({ offset, next, busy, onPage }: { offset: number; next: number | null; busy: boolean; onPage: (offset: number) => void }) {
  if (offset === 0 && next === null) return null;
  return <div className="inline-editor-actions" aria-label="Pagination">
    <button disabled={busy || offset === 0} onClick={() => onPage(Math.max(0, offset - 50))}>Previous</button>
    <span className="muted">Page {Math.floor(offset / 50) + 1}</span>
    <button disabled={busy || next === null} onClick={() => { if (next !== null) onPage(next); }}>Next</button>
  </div>;
}

export function ConversationWorkspace({ section, id, identity, refreshKey, onLoaded }: {
  section: "threads" | "traces"; id: string | null; identity: Identity; refreshKey: number; onLoaded: (value: { id: string; title: string }) => void;
}) {
  if (!id) return <Collection section={section} refreshKey={refreshKey} />;
  if (section === "traces") return <section className="trace-detail-page"><Run key={id} id={id} refreshKey={refreshKey} onLoaded={onLoaded} /></section>;
  return <section className="detail-page"><div className="record-page"><div className="record-primary">
    {id ? section === "threads" ? <Conversation key={id} id={id} identity={identity} refreshKey={refreshKey} onLoaded={onLoaded} />
      : <Run key={id} id={id} refreshKey={refreshKey} onLoaded={onLoaded} />
      : <Collection key={section} section={section} refreshKey={refreshKey} />}
  </div></div></section>;
}

function Collection({ section, refreshKey }: { section: "threads" | "traces"; refreshKey: number }) {
  const [page, setPage] = useState<{ objects?: ChatRow[]; runs?: RunRow[]; total: number; next_offset: number | null } | null>(null);
  const [offset, setOffset] = useState(0);
  const [format, setFormat] = useState("all");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setBusy(true); setError("");
    request<NonNullable<typeof page>>(`${section}?limit=50&offset=${offset}${section === "traces" ? `&format=${format}` : ""}`).then(result => { if (active) setPage(result); })
      .catch(cause => { if (active) setError(errorText(cause)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [section, offset, format, refreshKey]);
  if (section === "threads") return <section className="list-view thread-list-view" aria-label="Threads" aria-busy={busy}>
    <ThreadSearch />
    <WorkspaceToolbar className="thread-collection-toolbar"><span className="muted">Recent</span><span className="collection-count" aria-label={`${page?.total ?? 0} threads`}>{page?.total ?? 0}</span></WorkspaceToolbar>
    {error && <p role="alert" className="form-error">{error}</p>}
    {busy && <p role="status" className="muted">Loading threads…</p>}
    <div className="list-group-head"><span className="status-ring" /><strong>All threads</strong><span>{page?.objects?.length ?? 0}</span></div>
    <div className="record-list">{page?.objects?.map(chat => {
      const seconds = Math.max(0, Math.round((Date.now() - new Date(chat.updated_at).getTime()) / 1000));
      const updated = seconds < 60 ? "now" : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)}h ago` : `${Math.floor(seconds / 86400)}d ago`;
      return <div className="record" key={chat.id}>
        <a className="record-open" href={`/threads/${chat.id}`} aria-label={`Open ${chat.title}`} onClick={event => interceptNavigation(event, `/threads/${chat.id}`)} />
        <span className="record-kind"><ObjectTypeBadge kind="thread" compact /></span>
        <span className="record-id"><ObjectId id={chat.id} rowPill /></span>
        <span className="record-main"><span className="record-title"><strong>{chat.title}</strong></span><span className="record-users thread-participants" aria-label="Thread participants">{(chat.participants ?? []).map(user => <a key={user.user_object_id} href={`/users/${user.user_object_id}`} aria-label={`Open participant ${user.title}`} onClick={event => interceptNavigation(event, `/users/${user.user_object_id}`)}><AttributionStack users={[user]} /></a>)}</span></span>
        <p className="description-snippet">{chat.provider} · {chat.imported ? "Imported history" : "Supplied capture"} · {chat.coverage.status || "Unknown coverage"}</p>
        <time dateTime={chat.updated_at} title={`Updated ${date(chat.updated_at)}`}>{updated}</time>
      </div>;
    })}</div>
    {!busy && !error && page?.total === 0 && <div className="empty-list">No threads saved.</div>}
    <Paging offset={offset} next={page?.next_offset ?? null} busy={busy} onPage={setOffset} />
  </section>;
  return <section className="list-view trace-collection" aria-label="Traces" aria-busy={busy}>
    <WorkspaceToolbar className="trace-collection-toolbar"><label><span className="sr-only">Trace format</span><select aria-label="Trace format" value={format} onChange={event => { setFormat(event.target.value); setOffset(0); }}><option value="native">Native traces</option><option value="history">Other executions</option><option value="all">All activity</option></select></label><span className="collection-count">{page?.total ?? 0} {format === "native" ? "traces" : "records"}</span></WorkspaceToolbar>
    {error && <p role="alert" className="form-error">{error}</p>}
    {busy && <p role="status" className="muted">Loading traces…</p>}
    <div className="list-group-head"><span className="status-ring" /><strong>{format === "native" ? "Traces" : format === "history" ? "Other executions" : "All activity"}</strong><span>{page?.runs?.length ?? 0}</span></div>
    <div className="record-list" aria-label="Saved traces">
      {page?.runs?.map(run => {
        const elapsed = run.started_at && run.completed_at ? new Date(run.completed_at).getTime() - new Date(run.started_at).getTime() : null;
        const duration = elapsed === null ? "Duration not recorded" : elapsed >= 1000 ? `${(elapsed / 1000).toFixed(2)} s` : `${elapsed.toFixed(1)} ms`;
        const label = run.kind === "opentelemetry" ? run.thread_title || "OpenTelemetry trace" : run.kind;
        const seconds = run.started_at ? Math.max(0, Math.round((Date.now() - new Date(run.started_at).getTime()) / 1000)) : null;
        const started = seconds === null ? "—" : seconds < 60 ? "now" : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)}h ago` : `${Math.floor(seconds / 86400)}d ago`;
        return <div className="record trace-record" key={run.id}>
          <a className="record-open" href={`/traces/${run.id}`} aria-label={`Open trace ${label}, ${run.provider || "External"}, ${run.status}, ${duration}, ${date(run.started_at)}`} onClick={event => interceptNavigation(event, `/traces/${run.id}`)} />
          <span className="record-kind"><ObjectTypeBadge kind="trace" compact /></span>
          <span className="record-id"><ObjectId id={run.id} rowPill /></span>
          <span className="record-main"><span className="record-title"><strong>{label}</strong><span className={`trace-status ${run.status === "error" || run.status === "failed" ? "error" : ""}`}>{run.status}</span></span><span className="record-users"><AttributionStack users={run.participants ?? []} /></span></span>
          <p className="description-snippet">{run.provider || (run.imported ? "Imported" : "External")} · {duration}{run.span_count !== null ? ` · ${run.span_count} spans` : ""}</p>
          <time dateTime={run.started_at || undefined} title={date(run.started_at)}>{started}</time>
        </div>;
      })}
    </div>
    {!busy && !error && page?.total === 0 && <div className="empty-list">{format === "native" ? "No traces received." : "No activity saved."}</div>}
    <Paging offset={offset} next={page?.next_offset ?? null} busy={busy} onPage={setOffset} />
  </section>;
}

function Conversation({ id, identity, refreshKey, onLoaded }: { id: string; identity: Identity; refreshKey: number; onLoaded: (value: { id: string; title: string }) => void }) {
  const [page, setPage] = useState<ChatDetail | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    let active = true;
    setBusy(true); setError(""); setConfirm(false);
    request<ChatDetail>(`chats/${id}?limit=50&offset=${offset}`).then(result => { if (active) { setPage(result); onLoaded({ id, title: result.object.title }); } })
      .catch(cause => { if (active) { setError(errorText(cause)); setPage(null); } }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [id, offset, refreshKey, onLoaded]);
  if (!page) return <p role={error ? "alert" : "status"}>{error || "Loading thread…"}</p>;
  const coverage = page.chat.coverage;
  const canDelete = identity.role !== "reader" && (identity.id === page.chat.owner_id || identity.role === "admin");
  return <>
    <h1 className="detail-title">{page.object.title}</h1><AttributionStack users={page.participants ?? []} />
    <section className="properties-block" aria-label="Thread properties"><div className="properties-grid">
      <Property label="Type">Thread</Property><Property label="Provider">{page.chat.provider}</Property>
      <Property label="Coverage">{coverage.status || "Unknown"}</Property><Property label="Items">{page.total}</Property>
    </div></section>
    <nav className="capture-section-links" aria-label="Thread sections"><a href="#transcript">Conversation</a><a href="#relationships">Related objects & map</a></nav>
    <details className="detail-disclosure"><summary>Capture coverage · {coverage.status || "unknown"}{coverage.gaps?.length ? ` · ${coverage.gaps.length} gaps` : ""}</summary><div className="properties-grid">
      {(["messages", "tools", "attachments", "history"] as const).map(key => <div className="property" key={key}><span>{key}</span><div>{coverage[key] || "Not recorded"}</div></div>)}
    </div>{coverage.gaps?.map((gap, index) => <p className="muted" key={index}>{gap}</p>)}</details>
    <div id="transcript"><Section title="Conversation">
      {busy && <p role="status">Loading…</p>}
      {!page.total && <p className="muted">No visible items were supplied.</p>}
      {groupItems(page.items).map(group => group[0].kind === "message"
        ? <TranscriptItem key={group[0].id} item={group[0]} provider={page.chat.provider} />
        : <details className="thread-tools detail-disclosure" key={group[0].id}><summary>Tool activity · {group.length} {group.length === 1 ? "item" : "items"}{group.some(item => item.status === "failed") ? " · failed" : ""}</summary>
          {group.map(item => <TranscriptItem key={item.id} item={item} provider={page.chat.provider} />)}
        </details>)}
      <Paging offset={offset} next={page.next_offset} busy={busy} onPage={setOffset} />
    </Section></div>
    <div id="relationships"><CaptureRelationships id={id} title={page.object.title} section="threads" refreshKey={refreshKey} /></div>
    <details className="detail-disclosure"><summary>Record details</summary><div className="properties-grid"><Property label="Object ID"><ObjectId id={id} compact /></Property><Property label="Revision">{page.object.revision}</Property></div>
      <p className="muted">Shared with all authenticated people and agents here. Speaker names are supplied attribution, not verified authorship.</p>
    </details>
    {page.chat.import_provenance != null && <details className="detail-disclosure"><summary>Original conversation history</summary><JsonRecord value={page.chat.import_provenance} /></details>}
    {error && <p role="alert" className="form-error">{error}</p>}
    {canDelete && <details className="detail-disclosure"><summary>Delete managed thread copies</summary>
      <p className="muted">Removes this transcript, its attachments, registered raw excerpts, linked Run payloads and their stored history. Independently authored knowledge, vendor originals, downloads and historical backups may remain. Old backups can restore deleted content.</p>
      <label className="check"><input type="checkbox" checked={confirm} disabled={deleting} onChange={event => setConfirm(event.target.checked)} />I understand the managed-copy deletion boundary.</label>
      <div className="inline-editor-actions"><button className="secondary" disabled={!confirm || deleting || busy} onClick={async () => {
        setDeleting(true); setError("");
        try { await request(`chats/${id}/delete`, { expected_revision: page.object.revision, acknowledge_managed_copy_deletion: true }); navigate("/chats"); }
        catch (cause) { setError(errorText(cause)); setConfirm(false); } finally { setDeleting(false); }
      }}>{deleting ? "Deleting…" : "Delete thread"}</button></div>
    </details>}
  </>;
}

function Run({ id, refreshKey, onLoaded }: { id: string; refreshKey: number; onLoaded: (value: { id: string; title: string }) => void }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [correction, setCorrection] = useState<unknown>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true; setError("");
    request<{ run: RunDetail; correction: unknown }>(`runs/${id}`).then(result => { if (active) { setRun(result.run); setCorrection(result.correction); onLoaded({ id, title: result.run.kind === "opentelemetry" ? `Trace ${id.slice(0, 8)}` : result.run.kind }); } })
      .catch(cause => { if (active) { setError(errorText(cause)); setRun(null); } });
    return () => { active = false; };
  }, [id, refreshKey, onLoaded]);
  if (!run) return <p role={error ? "alert" : "status"}>{error || "Loading Run…"}</p>;
  if (run.kind === "opentelemetry") return <>
    <NativeTrace id={id} entries={run.trace} coverage={run.review} source={{ id: run.id, input: run.input, started_at: run.started_at, completed_at: run.completed_at }} context={<><AttributionStack users={run.participants ?? []} />{run.started_at && <time>{date(run.started_at)}</time>}{run.chat_object_id && <Link path={`/threads/${run.chat_object_id}`}>Source thread ↗</Link>}</>} />
  </>;
  return <>
    <AttributionStack users={run.participants ?? []} /><h1 className="detail-title">{run.kind === "opentelemetry" ? "OpenTelemetry trace" : run.kind}</h1>
    <section className="properties-block" aria-label="Run properties"><div className="properties-grid"><Property label="Type">{run.kind === "opentelemetry" ? "Trace" : "Run"}</Property><Property label="Status">{run.status}</Property><Property label="Started">{date(run.started_at)}</Property><Property label="Completed">{date(run.completed_at)}</Property></div></section>
    {run.chat_object_id && <p><Link path={`/threads/${run.chat_object_id}`}>Open source thread</Link></p>}
    {run.error && <pre className="source-text-preview run-error">{run.error}</pre>}
    {hasRecord(run.input) && <details className="detail-disclosure"><summary>Input</summary><JsonRecord value={run.input} /></details>}
    {run.kind === "opentelemetry" ? <NativeTrace id={id} entries={run.trace} coverage={run.review} /> : <details className="detail-disclosure"><summary>Trace · {run.trace.length} entries</summary>{!run.trace.length && <p className="muted">No trace supplied.</p>}{run.trace.map((entry, index) => <details className="detail-disclosure" key={index}><summary>Trace entry {index + 1}</summary><JsonRecord value={entry} /></details>)}</details>}
    {hasRecord(run.result) && <details className="detail-disclosure" open={typeof run.result === "string" && !!run.result}><summary>Result</summary>{typeof run.result === "string" ? <StoredText body={run.result} format="markdown" /> : <JsonRecord value={run.result} />}</details>}
    {hasRecord(run.review) && <details className="detail-disclosure"><summary>Review</summary><JsonRecord value={run.review} /></details>}
    {correction != null && <Section title="Correction (original preserved)"><JsonRecord value={correction} /></Section>}
    {!!run.consulted_object_ids.length && <details className="detail-disclosure"><summary>Consulted objects</summary>
      {run.consulted_object_ids.map((objectId, index) => {
        const reference = run.historical_references.find(ref => ref.object_id === objectId);
        return <div key={index}>{!reference || reference.state === "present" ? <ObjectId id={objectId} compact /> : <>
          <p className="muted">{objectId} · {reference.state === "deleted" ? "Deleted in source history" : "Missing; cause unknown"}</p>
          {!!reference.purge_evidence.length && <details className="detail-disclosure"><summary>Retained source purge evidence</summary><JsonRecord value={reference.purge_evidence} /></details>}
        </>}</div>;
      })}
    </details>}
    <CaptureRelationships id={id} title={run.kind} section="traces" refreshKey={refreshKey} />
    <details className="detail-disclosure"><summary>Record details</summary><Property label="Run ID">{run.id}</Property><Property label="Source date">{date(run.source_created_at)}</Property></details>
    <RunHistory id={id} refreshKey={refreshKey} />
    {run.import_provenance != null && <details className="detail-disclosure"><summary>Original Run history (never resumed)</summary><JsonRecord value={run.import_provenance} /></details>}
  </>;
}

function RunHistory({ id, refreshKey }: { id: string; refreshKey: number }) {
  const [page, setPage] = useState<{ history: { id: string; action: string; occurred_at: string | null; revision: number | null }[]; next_offset: number | null } | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true; setBusy(true); setError("");
    request<NonNullable<typeof page>>(`runs/${id}/history?limit=50&offset=${offset}`).then(result => { if (active) setPage(result); })
      .catch(cause => { if (active) setError(errorText(cause)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [id, offset, refreshKey]);
  return <Section title="Run history">{error && <p role="alert">{error}</p>}{busy ? <p role="status">Loading history…</p> : page && <>
    {!page.history.length && <p className="muted">No history on this page.</p>}
    {page.history.map(event => <details className="detail-disclosure" key={event.id}><summary>{event.action} · revision {event.revision ?? "unknown"} · {date(event.occurred_at)}</summary><JsonRecord value={event} /></details>)}
    <Paging offset={offset} next={page.next_offset} busy={busy} onPage={setOffset} />
  </>}</Section>;
}

function Property({ label, children }: { label: string; children: ReactNode }) {
  return <div className="property"><span>{label}</span><div>{children}</div></div>;
}

// Only contiguous activity is grouped: chronological order and page boundaries
// are preserved, including results whose calls were on an earlier page.
function groupItems(items: Item[]): Item[][] {
  const groups: Item[][] = [];
  for (const item of items) {
    const last = groups.at(-1);
    if (item.kind !== "message" && last && last[0].kind !== "message") last.push(item);
    else groups.push([item]);
  }
  return groups;
}

function TranscriptItem({ item, provider }: { item: Item; provider: string }) {
  const message = item.kind === "message";
  const speaker = item.speaker_name || ({ human: "User", agent: "Assistant", tool: "Tool" }[item.role] ?? item.role);
  return <article className={`conversation-item transcript-${message ? item.role : "tool"}`} aria-label={`${item.kind} from ${speaker}`}>
    <header><AttributionStack users={item.participants ?? []} />{!message && <strong>{item.tool_name || "Tool"}</strong>}{item.role === "agent" && <span className="muted">{item.model ? `${item.model.provider ?? "Provider not recorded"} · ${item.model.id ?? "Model not recorded"}` : "Model not recorded"}</span>}<span className="muted">{!message && `${item.kind.replaceAll("_", " ")}${item.status ? ` · ${item.status}` : ""}`}</span>{item.source_created_at && <time dateTime={item.source_created_at}>{date(item.source_created_at)}</time>}</header>
    {message ? <StoredText body={item.body} format={provider === "slack" ? "slack" : ["amp", "codex", "claude", "claude_code"].includes(provider) ? "markdown" : "plain_text"} />
      : <details className="detail-disclosure"><summary>Visible {item.kind.replaceAll("_", " ")} details</summary><pre className="source-text-preview">{item.body}</pre></details>}
    {item.attachments.map(artifact => <div key={artifact.id}>
      <p>{artifact.stored ? <a href={`/api/artifacts/${artifact.id}/content`} target="_blank" rel="noreferrer">Stored attachment · {artifact.title || artifact.id.slice(0, 8)}</a> : <strong>{artifact.title || "Attachment not stored"}</strong>} · {artifact.media_type} · {artifact.capture_outcome}</p>
      {artifact.capture_reason && <p className="muted">{artifact.capture_reason}</p>}
    </div>)}
    {item.correction && <details className="detail-disclosure"><summary>Correction (original preserved)</summary><p>{item.correction.reason}</p><JsonRecord value={item.correction.representation} /></details>}
    <details className="detail-disclosure transcript-metadata"><summary>{message ? "Message details" : "Source details"}</summary>
      {message && <details className="detail-disclosure"><summary>Original message text</summary><pre className="source-text-preview">{item.body}</pre></details>}
      <p className="muted">ID {item.id} · received by Commons {date(item.received_at)}{item.tool_call_id ? ` · tool call ${item.tool_call_id}` : ""}</p>
      <p className="muted">Original ingestion time: {date(item.source_ingested_at)}</p>
      {item.import_provenance != null && <JsonRecord value={item.import_provenance} />}
    </details>
  </article>;
}
