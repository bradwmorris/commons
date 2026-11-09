import { endpointPath } from "./routing";
// Shell, rows, details and modal markup adapted from Context 91b31f4 (MIT).
// See ../CONTEXT-LICENSE and ../REUSE.md. API/authority is Commons-owned.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, api, request, type Sort } from "./api";
import { InlineEditor } from "./InlineEditor";
import { Artifacts } from "./Artifacts";
import { StoredText } from "./StoredText";
import { ResearchDetails, ResearchInputs, initialResearch, researchKinds } from "./Research";
import { ConnectionId, ObjectId } from "./ObjectIdentity";
import { AttributionStack, ObjectTypeBadge, TaskStatusBadge, userAttribution } from "./RecordVisuals";
import { TaskAssignee, TaskIssueLink, TaskReadiness, taskOf } from "./TaskIdentity";
import { projectPresentation } from "./taskProject";
import { groupListByDateField } from "./taskDateGroups";
import { RecordList } from "./RecordList";
import { TaskBoard } from "./TaskBoard";
import { ConnectionGraphWorkspace, FocusedObjectGraph } from "./ConnectionGraph";
import { UserDetail, UserList } from "./Users";
import { SchemaWorkspace } from "./Schema";
import { ConversationWorkspace } from "./Conversations";
import { kindSections, sections, publishingCalendarUrl, parseRoute, navigate, interceptNavigation, objectPath, connectionPath, type Section } from "./routing";
import type { Connection, RelatedConnection, Endpoint, User, Credential, Detail, Fields, Identity, ObjectKind, ObjectVisual, Participant, RecordObject, TaskStatus } from "./types";

const writableKinds = ["task", "note", "entity", "source", "theme", "event"] as const;
type WritableKind = typeof writableKinds[number];
const icons: Record<Section, string> = { objects: "◇", connections: "⌁", tasks: "✓", users: "♙", entities: "◎", notes: "▱", sources: "▤", themes: "#", events: "◷", access: "⚿", threads: "☷", traces: "▷", schema: "▦", publishing: "▦" };
const issuePattern = "https://github[.]com/[A-Za-z0-9_.\\-]+/[A-Za-z0-9_.\\-]+/issues/[1-9][0-9]*";
const issueRegex = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/issues\/[1-9][0-9]*$/;
const text = (value: unknown) => typeof value === "string" ? value : "";
const titleCase = (value: string) => value[0].toUpperCase() + value.slice(1);
const message = (cause: unknown) => cause instanceof Error ? cause.message : "Could not complete the request.";
function relative(value: string) { if (!value || !Number.isFinite(new Date(value).getTime())) return "Not recorded"; const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000)); return seconds < 60 ? "now" : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)}h ago` : `${Math.floor(seconds / 86400)}d ago`; }

type Branding = { name: string; theme: "charcoal" | "blue-slate" };
type ReadingPosition = { top: number; expanded: string[] };
const brandMark = (name: string) => Array.from(name)[0].toUpperCase();

export default function App() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [automaticEntry, setAutomaticEntry] = useState<boolean | null>(null);
  const [branding, setBranding] = useState<Branding>({ name: "Commons", theme: "charcoal" });
  const [ready, setReady] = useState(false);
  const [authError, setAuthError] = useState("");
  useEffect(() => {
    void request<{ protected_demo: boolean; local_entry: boolean; branding: Branding }>("health").then(async health => {
      setBranding(health.branding);
      document.title = `${health.branding.name} — Context`;
      document.documentElement.dataset.theme = health.branding.theme;
      setAutomaticEntry(health.protected_demo || health.local_entry);
      await api.me().then(setIdentity).catch(() => {});
    }).catch(() => {}).finally(() => setReady(true));
  }, []);
  useEffect(() => {
    if (!identity) return;
    const expired = () => {
      if (automaticEntry) { window.location.reload(); return; }
      setIdentity(null); setAuthError("Your session ended. Sign in again.");
    };
    window.addEventListener("commons-session-expired", expired);
    return () => window.removeEventListener("commons-session-expired", expired);
  }, [identity, automaticEntry]);
  if (!ready) return <div className="blank-state" role="status">Loading {branding.name}…</div>;
  if (!identity && automaticEntry !== false) return <div className="blank-state" role="alert">{branding.name} is unavailable. <button onClick={() => window.location.reload()}>Reload</button></div>;
  if (!identity) return <Login branding={branding} error={authError} onLogin={async () => { setIdentity(await api.me()); setAuthError(""); }} />;
  return <Workspace branding={branding} identity={identity} automaticEntry={automaticEntry === true} onLogout={() => { setIdentity(null); setAuthError(""); }} />;
}

function Login({ branding, error: initialError, onLogin }: { branding: Branding; error: string; onLogin: () => Promise<void> }) {
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState(false);
  return <main className="login-page"><section className="create-modal"><header className="create-modal-head"><div><span className="modal-mark">{brandMark(branding.name)}</span><h1>{branding.name}</h1></div></header>
    <form className="create-form form" onSubmit={async event => {
      event.preventDefault(); setBusy(true); setError("");
      try { await request("login", Object.fromEntries(new FormData(event.currentTarget))); await onLogin(); }
      catch (cause) { setError(message(cause)); } finally { setBusy(false); }
    }}><Field label="Username"><input name="username" autoComplete="username" required autoFocus /></Field><Field label="Password"><input name="password" type="password" autoComplete="current-password" required /></Field>
      {error && <p className="form-error" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button><p className="muted">Organisation-shared records · named local login · no internal model</p>
    </form></section></main>;
}

function Workspace({ branding, identity, automaticEntry, onLogout }: { branding: Branding; identity: Identity; automaticEntry: boolean; onLogout: () => void }) {
  const [route, setRoute] = useState(parseRoute);
  const { section, id, view, artifactId } = route;
  const board = section === "tasks" && view === "kanban";
  const unavailableView = section === "tasks" && !id && !!view && view !== "kanban";
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 820px)").matches);
  const [collapsed, setCollapsed] = useState(narrow);
  const navToggle = useRef<HTMLButtonElement>(null);
  const readingPositions = useRef(new Map<string, ReadingPosition>());
  const [objects, setObjects] = useState<RecordObject[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [collectionTotal, setCollectionTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const collectionAbort = useRef<AbortController | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [historicalUsers, setHistoricalUsers] = useState<User[]>([]);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [loadedTitle, setLoadedTitle] = useState({ id: "", title: "" });
  const [loadedScope, setLoadedScope] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort | "due_date">("recent");
  const [project, setProject] = useState("");
  const [showDone, setShowDone] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshState, setRefreshState] = useState<"idle" | "refreshing" | "done" | "error">("idle");
  const [now, setNow] = useState(() => new Date());
  const writable = identity.role !== "reader";
  const collection = !id && section !== "access" && section !== "connections" && section !== "threads" && section !== "traces" && section !== "schema" && section !== "publishing";
  const kind = Object.entries(kindSections).find(([, value]) => value === section)?.[0] ?? "";
  const newKind = writableKinds.includes(kind as WritableKind) ? kind as WritableKind : "note";
  const scope = JSON.stringify([section, query, sort]);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 820px)");
    const resize = () => { setNarrow(media.matches); setCollapsed(media.matches); };
    media.addEventListener("change", resize);
    return () => media.removeEventListener("change", resize);
  }, []);
  useEffect(() => {
    const sync = () => setRoute(parseRoute());
    window.addEventListener("popstate", sync);
    if (window.location.pathname === "/") navigate("/objects", true);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  useEffect(() => { setQuery(""); setSort("recent"); setProject(""); setCreateOpen(false); }, [section]);
  useEffect(() => {
    let active = true;
    void api.users().then(items => { if (active) { setUsers(items.filter(u => u.active)); setHistoricalUsers(items); } }).catch(cause => { if (active) setError(message(cause)); });
    return () => { active = false; };
  }, [refreshKey]);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    collectionAbort.current = controller;
    setNextPage(null); setLoadingMore(false);
    setLoading(true); setError("");
    const timer = window.setTimeout(async () => {
      try {
        if (collection && section !== "users") {
          // Task grouping/project counts require complete data until the API supports
          // those aggregate filters. Other collections load one page at a time.
          const page = section === "tasks"
            ? { objects: await api.objects(query, kind, sort === "due_date" ? "recent" : sort, false, controller.signal), total: 0, next_offset: null }
            : await api.objectPage(query, kind, sort === "due_date" ? "recent" : sort, false, 0, controller.signal);
          if (!active) return;
          setObjects(page.objects); setParticipants([]); setLoadedScope(scope);
          setCollectionTotal(page.total); setNextPage(page.next_offset); setLoading(false);
          const related = await api.participants(page.objects.map(object => object.id), controller.signal);
          if (active) setParticipants(related);
        }
        if (active) setRefreshState(current => current === "refreshing" ? "done" : current);
      } catch (cause) { if (active) { setError(message(cause)); setRefreshState("error"); } }
      finally { if (active) setLoading(false); }
    }, 150);
    return () => { active = false; controller.abort(); window.clearTimeout(timer); };
  }, [collection, query, kind, sort, refreshKey, scope]);
  useEffect(() => { if (refreshState !== "done") return; const timer = window.setTimeout(() => setRefreshState("idle"), 1400); return () => clearTimeout(timer); }, [refreshState]);
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date()), 30_000); return () => clearInterval(timer); }, []);
  const displayUsers = useMemo(() => [...new Map([...historicalUsers, ...users].map(user => [user.id, user])).values()], [historicalUsers, users]);
  const visuals = useMemo(() => {
    const result = new Map<string, ObjectVisual>(displayUsers.map(user => [user.id, {
      object_id: user.id, source_provider: null, users: [userAttribution(user)],
    }]));
    for (const { object_id, user, role } of participants) {
      const visual = result.get(object_id) ?? { object_id, source_provider: null, users: [] };
      if (!visual.users.some(person => person.user_object_id === user.id)) visual.users.push(userAttribution(user, role));
      result.set(object_id, visual);
    }
    return result;
  }, [displayUsers, participants]);
  const scopedObjects = loadedScope === scope ? objects : [];
  const projects = [...new Set(scopedObjects.filter(object => object.kind === "task").map(object => text(object.fields.project) || "_none"))].sort();
  const items = section === "tasks" ? scopedObjects.filter(object => (!project || (text(object.fields.project) || "_none") === project) && (showDone || object.fields.status !== "done")) : scopedObjects;
  const groups = section === "tasks" && sort === "due_date" ? groupListByDateField(items.map(taskOf), "due_at", now, Intl.DateTimeFormat().resolvedOptions().timeZone, showDone) : null;
  const count = section === "users" ? displayUsers.filter(u => `${u.title} ${u.user_kind}`.toLowerCase().includes(query.toLowerCase())).length : section !== "tasks" ? (loadedScope === scope ? collectionTotal : 0) : groups ? groups.reduce((sum, group) => sum + group.tasks.length, 0) : items.length;
  async function loadMore() {
    const controller = collectionAbort.current;
    if (nextPage === null || loadingMore || !controller || controller.signal.aborted || loadedScope !== scope) return;
    setLoadingMore(true); setError("");
    try {
      const page = await api.objectPage(query, kind, sort === "due_date" ? "recent" : sort, false, nextPage, controller.signal);
      if (controller.signal.aborted) return;
      setObjects(current => [...new Map([...current, ...page.objects].map(object => [object.id, object])).values()]);
      setCollectionTotal(page.total); setNextPage(page.next_offset);
      const related = await api.participants(page.objects.map(object => object.id), controller.signal);
      if (!controller.signal.aborted) setParticipants(current => [...current, ...related]);
    } catch (cause) { if (!controller.signal.aborted) setError(message(cause)); }
    finally { if (!controller.signal.aborted) setLoadingMore(false); }
  }
  function closeNavigation() { setCollapsed(true); navToggle.current?.focus(); }
  function openSection(next: Section) { navigate(`/${next}`); if (narrow) setCollapsed(true); }
  async function changeTaskStatus(task: Readonly<RecordObject>, status: TaskStatus, blockedReason?: string) {
    if (!writable) throw new Error("Read-only access cannot move Tasks.");
    const fields: Fields = { status };
    if (status === "blocked") {
      if (!blockedReason?.trim()) throw new Error("A blocked reason is required.");
      fields.blocked_reason = blockedReason.trim();
    } else if (task.fields.status === "blocked") fields.blocked_reason = null;
    if (status === "done") fields.completed_at = new Date().toISOString();
    else if (task.fields.status === "done") fields.completed_at = null;
    const updated = await api.update(task, { fields });
    setObjects(current => current.map(object => object.id === task.id && object.revision <= updated.object.revision ? updated.object : object));
    setRefreshKey(value => value + 1);
  }
  return <main className={collapsed ? "app nav-collapsed" : "app"}>
    <aside className="nav-rail" onKeyDown={event => { if (event.key === "Escape" && narrow && !collapsed) { event.stopPropagation(); closeNavigation(); } }}><div className="nav-head"><div className="brand" title={branding.name}><span className="brand-mark">{brandMark(branding.name)}</span>{!collapsed && <span className="brand-name">{branding.name}</span>}</div><button ref={navToggle} className="collapse-button" title={branding.name} onClick={() => setCollapsed(value => !value)} aria-expanded={!collapsed} aria-controls="workspace-navigation" aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}><span className="collapse-chevron" aria-hidden="true">‹</span><span className="brand-mark collapsed-brand-mark" aria-hidden="true">{brandMark(branding.name)}</span></button></div>
      <nav id="workspace-navigation" aria-label={branding.name}>{(Object.keys(sections) as Section[]).filter(key => key !== "access" && (key !== "publishing" || publishingCalendarUrl)).map(key => <NavButton key={key} section={key} active={section === key} compact={collapsed} onClick={() => openSection(key)} />)}</nav>
      <div className="nav-access"><NavButton section="access" active={section === "access"} compact={collapsed} onClick={() => openSection("access")} />{!automaticEntry && <button className="nav-button" title={`Sign out (${identity.role})`} aria-label="Sign out" onClick={async () => { try { await request("logout", {}); onLogout(); } catch (cause) { setError(message(cause)); } }}><span aria-hidden="true">↪</span>{!collapsed && "Sign out"}</button>}</div>
      <div className="nav-foot" title={`Authenticated ${identity.role}`}><span className="status-dot" />{!collapsed && `${identity.role} · Shared workspace`}</div>
    </aside>
    {narrow && !collapsed && <button className="nav-backdrop" aria-label="Close navigation" onClick={closeNavigation} onKeyDown={event => { if (event.key === "Escape") closeNavigation(); }} />}
    <section className="main-panel" inert={narrow && !collapsed}><header className={`topbar${collection || section === "connections" || ((section === "threads" || section === "traces") && !id) ? " collection-toolbar" : ""}`}>
      <div className="page-path"><button className="path-root" onClick={() => navigate(`/${section}`)}>{sections[section]}</button>{id && <><span>›</span><strong title={loadedTitle.id === id ? loadedTitle.title : id}>{loadedTitle.id === id ? loadedTitle.title : id.slice(0, 8)}</strong>{artifactId && <span>› Reader</span>}</>}</div>
      {!collection && <div id="workspace-toolbar-slot" />}
      {collection && section === "tasks" && <div className="task-view-switcher" role="group" aria-label="Task views">{["list", "kanban"].map(value => <button key={value} aria-pressed={board === (value === "kanban")} onClick={() => {
        const params = new URLSearchParams(window.location.search);
        if (value === "kanban") params.set("view", value); else params.delete("view");
        navigate(`/tasks${params.size ? `?${params}` : ""}`);
      }}>{value === "list" ? "List" : "Board"}</button>)}</div>}
      {collection && <><label className="search" title="Lexical title and description search; bodies are read explicitly"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.25" /><path d="m10.25 10.25 3 3" /></svg><input aria-label={`Search ${sections[section].toLowerCase()}`} aria-describedby="search-scope" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search…" /></label><span id="search-scope" className="sr-only">Lexical metadata: titles and descriptions only. Artifact bodies are read explicitly.</span>
        {section === "tasks" && <label className="project-filter"><span className="sr-only">Filter task projects</span><select aria-label="Filter task projects" value={project} onChange={event => setProject(event.target.value)}><option value="">All projects</option>{projects.map(value => <option key={value} value={value}>{projectPresentation(value === "_none" ? null : value).label}</option>)}</select></label>}
        {!board && <label className="sort-control"><span className="sr-only">Sort {sections[section]}</span><select aria-label={`Sort ${sections[section]}`} value={sort} onChange={event => setSort(event.target.value as typeof sort)}><option value="recent">Recent</option><option value="connected">Connected</option>{section === "tasks" && <option value="due_date">Due date</option>}</select></label>}
        {section === "tasks" && <button className={`completed-toggle${showDone ? " active" : ""}`} aria-pressed={showDone} aria-label={showDone ? "Hide completed" : "Show completed"} onClick={() => setShowDone(value => !value)}>✓</button>}<span className="collection-count" aria-label={`${count} records`}>{count}</span></>}
      <button className="refresh-button" disabled={refreshState === "refreshing"} onClick={() => { setRefreshState("refreshing"); setRefreshKey(value => value + 1); }} aria-label="Refresh current view"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13.2 5.5A5.5 5.5 0 1 0 13 11" /><path d="M13.2 2.5v3.2H10" /></svg><span>{refreshState === "refreshing" ? "Refreshing…" : refreshState === "done" ? "Updated" : refreshState === "error" ? "Retry refresh" : "Refresh"}</span></button>
      {collection && writable && section !== "users" && <button className="collection-new" onClick={() => setCreateOpen(true)} aria-label={`New ${section === "objects" ? "object" : newKind}`}><span aria-hidden="true">＋</span> New</button>}
    </header>
    {(error || unavailableView) && <div className="error-banner"><div>{unavailableView && <span role="status">This view is unavailable. Showing the list. </span>}{error && <span role="alert">{error}</span>}</div>{error && <button aria-label="Dismiss error" onClick={() => setError("")}>×</button>}</div>}
    <div className="workspace">{section === "publishing" ? <iframe className="publishing-frame" title="Publishing calendar" src={`${publishingCalendarUrl}/#embed`} /> : section === "schema" ? <SchemaWorkspace id={id} refreshKey={refreshKey} /> : section === "users" ? id ? <UserDetail id={id} refreshKey={refreshKey} onLoaded={setLoadedTitle} /> : <UserList users={displayUsers} query={query} sort={sort} /> : section === "threads" || section === "traces" ? <ConversationWorkspace section={section} id={id} identity={identity} refreshKey={refreshKey} onLoaded={setLoadedTitle} /> : section === "access" ? <Access identity={identity} users={users} refreshKey={refreshKey} onUsersChanged={() => setRefreshKey(value => value + 1)} /> : section === "connections" ? id ? <ConnectionDetail id={id} refreshKey={refreshKey} visuals={visuals} onLoaded={setLoadedTitle} /> : <ConnectionGraphWorkspace refreshKey={refreshKey} /> : id ? <section className="detail-page" key={`${id}:${artifactId}`}><ObjectDetail id={id} artifactId={artifactId} readingPositions={readingPositions.current} onLoaded={setLoadedTitle} writable={writable} users={users} displayUsers={displayUsers} visuals={visuals} refreshKey={refreshKey} /></section> : board ? <TaskBoard objects={items} visuals={visuals} loading={loading || loadedScope !== scope && !error} loadError={error} writable={writable} showDone={showDone} now={now} changeStatus={changeTaskStatus} reload={() => setRefreshKey(value => value + 1)} /> : <RecordList objects={items} groups={groups} visuals={visuals} section={section} now={now} loading={loading || loadedScope !== scope && !error} error={error} query={query}>{nextPage !== null && loadedScope === scope && <div className="collection-pagination"><span>{items.length} of {collectionTotal} records loaded</span><button className="secondary" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? "Loading…" : "Load more records"}</button></div>}</RecordList>}</div></section>
    {createOpen && <NewObject initialKind={newKind} chooseKind={section === "objects"} users={users} identity={identity} onCancel={() => setCreateOpen(false)} onCreated={objectId => { setCreateOpen(false); navigate(objectPath(objectId)); }} />}
  </main>;
}

function NavButton({ section, active, compact, onClick }: { section: Section; active: boolean; compact: boolean; onClick: () => void }) { return <button className={active ? "nav-button active" : "nav-button"} aria-label={sections[section]} aria-current={active ? "page" : undefined} title={compact ? sections[section] : undefined} onClick={onClick}><span aria-hidden="true">{icons[section]}</span>{!compact && sections[section]}</button>; }

function ObjectDetail({ id, artifactId, readingPositions, onLoaded, writable, displayUsers: users, visuals, refreshKey }: { id: string; artifactId: string | null; readingPositions: Map<string, ReadingPosition>; onLoaded: (value: { id: string; title: string }) => void; writable: boolean; users: User[]; displayUsers: User[]; visuals: ReadonlyMap<string, ObjectVisual>; refreshKey: number }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const deleteRequest = useRef<{ revision: number; key: string } | null>(null);
  const [error, setError] = useState("");
  const page = useRef<HTMLDivElement>(null);
  const loaded = detail !== null;
  useLayoutEffect(() => {
    if (!loaded || artifactId) return;
    const scroller = page.current!.closest<HTMLElement>(".detail-page")!;
    const disclosures = () => [...scroller.querySelectorAll("details")];
    const label = (element: HTMLDetailsElement) => element.querySelector("summary")?.textContent ?? "";
    const previous = readingPositions.get(id);
    if (previous) {
      for (const element of disclosures()) element.open = previous.expanded.includes(label(element));
      scroller.scrollTop = previous.top;
    }
    return () => { readingPositions.set(id, { top: scroller.scrollTop, expanded: disclosures().filter(element => element.open).map(label) }); };
  }, [id, artifactId, loaded, readingPositions]);
  const latest = useRef<Detail | null>(null);
  const dirty = useRef(new Set<string>());
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const mounted = useRef(true);
  const reading = useRef<AbortController | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; reading.current?.abort(); }; }, []);
  const load = useCallback(async () => {
    if (dirty.current.size) throw new Error("Unsaved draft preserved. Finish editing before refreshing another field.");
    reading.current?.abort();
    const controller = new AbortController(); reading.current = controller;
    let next: Detail, related: Participant[];
    try {
      next = await api.detail(id, controller.signal);
      related = await api.participants([...new Set([id, ...next.connections.flatMap(c => [c.from_object.id,c.to_object.id])])], controller.signal);
    }
    catch (cause) { if (controller.signal.aborted) return; if (cause instanceof ApiError && cause.status === 404) { try { await request(`users/${id}`); navigate(`/users/${id}`, true); return; } catch { /* Keep the original missing-Object error. */ } } throw cause; }
    if (!mounted.current || controller.signal.aborted) return;
    latest.current = next; setDetail(next); setParticipants(related); setError("");
    onLoaded({ id, title: next.object.title });
    const section = kindSections[next.object.kind];
    const path = `/${section}/${id}${artifactId ? `/artifacts/${artifactId}` : ""}`;
    if (section && window.location.pathname !== path) navigate(`${path}${window.location.search}${window.location.hash}`, true);
  }, [id, artifactId, onLoaded]);
  useEffect(() => { if (dirty.current.size) { setError("Unsaved draft preserved. Finish editing or reload the server value before refreshing."); return; } void load().catch(cause => setError(message(cause))); }, [load, refreshKey]);
  function save(changes: { title?: string; description?: string; body?: string; fields?: Fields }) {
    const result = chain.current.then(async () => {
      const next = await api.update(latest.current!.object, changes);
      latest.current = next; setDetail(next); setError(""); onLoaded({ id, title: next.object.title });
      const related = await api.participants([...new Set([id,...next.connections.flatMap(c => [c.from_object.id,c.to_object.id])])]);
      if (mounted.current) setParticipants(related);
      return next.object;
    });
    chain.current = result.catch(() => {}); return result;
  }
  if (!detail) return <Blank error={error} />;
  const object = detail.object;
  const relatedConnections = detail.connections;
  const detailVisuals = new Map(visuals);
  for (const p of participants) {
    const previous = detailVisuals.get(p.object_id);
    const people = [...(previous?.users ?? [])];
    if (!people.some(u => u.user_object_id === p.user.id)) people.push(userAttribution(p.user,p.role));
    detailVisuals.set(p.object_id,{object_id:p.object_id,source_provider:previous?.source_provider ?? null,users:people});
  }
  const editable = writable && writableKinds.includes(object.kind as WritableKind);
  const isTask = object.kind === "task";
  const label = isTask ? "Task" : object.kind === "note" ? "Note" : "Object";
  const markDirty = (field: string, value: boolean) => { if (value) dirty.current.add(field); else dirty.current.delete(field); };
  const reloadField = async (field: string) => { dirty.current.delete(field); await load(); };
  const editor = (field: "title" | "description" | "body", fieldLabel: string, className: string, multiline = false, required = false) => {
    const value = object[field];
    const renderValue = field === "body" ? (body: string) => <StoredText body={body} format={text(object.fields.content_format)} /> : undefined;
    return editable ? <InlineEditor label={fieldLabel} value={value} className={className} heading={field === "title"} multiline={multiline} required={required} maxLength={field === "title" ? 200 : field === "description" ? 600 : undefined}
      renderValue={renderValue}
      onDirtyChange={value => markDirty(field, value)}
      onSave={async value => { if (new TextEncoder().encode(value).length > 16 * 1024 * 1024) throw new Error("Field exceeds 16 MiB UTF-8 bytes."); const next = await save({ [field]: value }); return next[field]; }}
      onReload={() => reloadField(field)} /> : field === "title" ? <h1 className="detail-title">{value}</h1> : renderValue ? renderValue(value) : <p className={className}>{value || "Not set"}</p>;
  };
  const changeField = async (key: string, value: string | boolean) => { try { await save({ fields: { [key]: value } }); } catch (cause) { setError(message(cause)); } };
  if (artifactId) return <div className="record-page artifact-page"><div className="record-primary">
    <a className="reader-parent" href={objectPath(id)} onClick={event => interceptNavigation(event, objectPath(id))}>← {object.title}</a>
    <Artifacts object={object} artifacts={detail.artifacts} artifactId={artifactId} editable={editable} onSaved={load} onDirty={value => markDirty("artifact", value)} />
  </div></div>;
  return <div ref={page} className={`record-page${isTask ? " task-detail" : ""}`}><div className="record-primary"><div className="detail-form">
    {editor("title", `${label} title`, "detail-title-editor", false, true)}
    <div className="detail-object-id"><ObjectId id={id} rowPill /><AttributionStack users={participants.filter(p => p.object_id === id).map(p => userAttribution(p.user, p.role))} limit={participants.length} /></div>
    {isTask ? <section className="properties-block" aria-label="Task properties"><div className="task-workflow-properties">
      <Property label="Status"><TaskStatusBadge status={taskOf(object).status} /></Property>
      <Property label="Assigned to"><TaskAssignee task={taskOf(object)} visuals={visuals} /></Property>
      <Property label="Due">{text(object.fields.due_at) ? <time dateTime={text(object.fields.due_at)}>{new Date(text(object.fields.due_at)).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</time> : "Not recorded"}</Property>
      <Property label="Priority">{text(object.fields.priority) ? titleCase(text(object.fields.priority)) : "Not set"}</Property>
      <Property label="Project">{text(object.fields.project) || "Not set"}</Property>
      <Property label="Work type">{object.fields.work_kind === "code" ? "Code / repository change" : "General"}</Property>
    </div></section> : researchKinds.includes(object.kind) ? <ResearchDetails detail={detail} editable={editable} onSaved={load} onDirty={value => markDirty("research", value)} /> : null}
    {editor("description", `${label} description`, "detail-body-editor", true)}
    {!isTask && <Section title="Body">{editor("body", "Body", "note-content-editor", true)}</Section>}
    {isTask && <><Section title="Brief">{editor("body", "Task body", "detail-body-editor task-brief-editor", true)}</Section><details className="task-metadata detail-disclosure"><summary>More details</summary><div className="properties-grid">
      <Property label="Object ID"><ObjectId id={id} label={false} navigate /></Property><Property label="Type"><ObjectTypeBadge kind="task" /></Property><Property label="Agent suitability"><label className="check"><input type="checkbox" checked={!!object.fields.agent_suitable} disabled={!editable} onChange={event => void changeField("agent_suitable", event.target.checked)} />Suitable for an external agent</label></Property><Property label="Created by"><Actor id={object.metadata.created_by} users={users} /></Property><Property label="Completed">{text(object.fields.completed_at) || "Not complete"}</Property><Property label="Blocked reason">{text(object.fields.blocked_reason) || "None"}</Property>
      <Property label="GitHub issue" className="task-issue-property"><TaskIssueLink url={text(object.fields.github_issue_url)} showLabel />{editable && <InlineEditor label="GitHub issue URL" value={text(object.fields.github_issue_url)} placeholder="Not linked" onDirtyChange={value => markDirty("issue", value)} onSave={async value => { const issue = value.trim(); if (issue && !issueRegex.test(issue)) throw new Error("Enter a canonical GitHub Issue URL or leave it empty."); return text((await save({ fields: { github_issue_url: issue || null } })).fields.github_issue_url); }} onReload={() => reloadField("issue")} />}</Property><Property label="Revision">{object.revision}</Property><Property label="Updated">{relative(object.metadata.updated_at ?? "")}</Property></div></details><TaskReadiness task={taskOf(object)} /></>}
    </div>{error && <p className="form-error" role="alert">{error}</p>}
    {detail.artifacts.length > 0 && <Section title="Artifacts"><Artifacts object={object} artifacts={detail.artifacts} editable={editable} onSaved={load} onDirty={value => markDirty("artifact", value)} /></Section>}
    {editable && <button className="secondary" onClick={() => { if (dirty.current.size) { setError("Finish editing before deleting this Object."); return; } setDeleteOpen(true); }}>Delete Object</button>}
    {deleteOpen && <CreateModal title="Delete Object" onClose={() => { if (!deleting) setDeleteOpen(false); }}><div className="create-form">
      <p>Delete “{object.title}”, its owned Artifacts and stored content history? The ID and deletion audit remain. Connected independent records survive. External copies and historical backups may remain.</p>
      <button className="secondary" disabled={deleting} onClick={() => setDeleteOpen(false)}>Cancel</button>
      <button disabled={deleting} onClick={async () => {
        setDeleting(true);
        const pending = deleteRequest.current ?? { revision: object.revision, key: crypto.randomUUID() }; deleteRequest.current = pending;
        try { await api.apply([{ op: "delete_object", object_id: id, expected_revision: pending.revision, acknowledge_owned_content_deletion: true }], pending.key); navigate(`/${kindSections[object.kind] ?? "objects"}`); }
        catch (cause) { setError(message(cause)); if (cause instanceof ApiError && cause.status === 409) deleteRequest.current = null; }
        finally { setDeleting(false); }
      }}>{deleting ? "Deleting…" : "Confirm deletion"}</button>
      {error && <p role="alert">{error}</p>}
    </div></CreateModal>}
    <RelatedGroups object={object} connections={relatedConnections} visuals={detailVisuals} />
    <FocusedObjectGraph objectId={id} objectTitle={object.title} refreshKey={object.revision + refreshKey} />
  </div></div>;
}

function RecordAttribution({ object, visuals }: { object: Endpoint; visuals: ReadonlyMap<string, ObjectVisual> }) {
  return <AttributionStack users={visuals.get(object.id)?.users ?? visuals.get(object.metadata?.created_by ?? "")?.users ?? []} />;
}
function RelatedGroups({ object, connections, visuals }: { object: RecordObject; connections: RelatedConnection[]; visuals: ReadonlyMap<string, ObjectVisual> }) {
  return <Section title={`Connections (${connections.length})`}><div className="connections related-object-list">{connections.map(connection => <RelatedObject key={connection.id} connection={connection} currentId={object.id} visuals={visuals} />)}</div>{!connections.length && <p className="muted">No connections.</p>}</Section>;
}

function RelatedObject({ connection, currentId, visuals }: { connection: RelatedConnection; currentId: string; visuals: ReadonlyMap<string, ObjectVisual> }) {
  const outbound = connection.from_id === currentId;
  const related = outbound ? connection.to_object : connection.from_object;
  return <article className="related-object-row"><ObjectTypeBadge kind={related.kind} compact /><ObjectId id={related.id} rowPill /><span className="related-object-copy"><a className="related-object-title" title={related.title} href={endpointPath(related)} onClick={event => interceptNavigation(event, endpointPath(related))}>{related.title}</a><span className="related-object-description" title={connection.explanation}>{connection.explanation}</span></span><RecordAttribution object={related} visuals={visuals} /><span className="related-object-meaning">{outbound ? "→" : "←"} {connection.kind.replaceAll("_", " ")}</span><a className="related-connection-link" href={connectionPath(connection.id)} onClick={event => interceptNavigation(event, connectionPath(connection.id))}>Connection</a></article>;
}
function ConnectionDetail({ id, refreshKey, visuals, onLoaded }: { id: string; refreshKey: number; visuals: ReadonlyMap<string, ObjectVisual>; onLoaded: (value: { id: string; title: string }) => void }) {
  const [connection, setConnection] = useState<Connection | null>(null); const [error, setError] = useState("");
  useEffect(() => { let active = true; request<{ connection: Connection }>(`connections/${encodeURIComponent(id)}`).then(result => { if (active) { setConnection(result.connection); onLoaded({ id, title: `${result.connection.from_object.title} → ${result.connection.to_object.title}` }); } }).catch(cause => { if (active) setError(message(cause)); }); return () => { active = false; }; }, [id, refreshKey, onLoaded]);
  if (!connection) return <Blank error={error} />;
  const endpoint = (object: Endpoint) => <div className="connection-endpoint"><strong>{object.title}</strong><ObjectTypeBadge kind={object.kind} /><RecordAttribution object={object} visuals={visuals} /><ObjectId id={object.id} linkPill href={endpointPath(object)} /></div>;
  return <section className="detail-page"><div className="record-page"><div className="record-primary"><h1 className="detail-title">{connection.kind.replaceAll("_", " ")}</h1><p className="detail-description">{connection.explanation}</p><div className="connection-flow">{endpoint(connection.from_object)}<span aria-label="points to">→</span>{endpoint(connection.to_object)}</div><Property label="Connection ID"><ConnectionId id={id} label={false} /></Property><Property label="Created">{connection.metadata.created_at ? new Date(connection.metadata.created_at).toLocaleString() : "Not recorded"}</Property>{error && <p role="alert">{error}</p>}</div></div></section>;
}

function NewObject({ initialKind, chooseKind, users, identity, onCancel, onCreated }: { initialKind: WritableKind; chooseKind: boolean; users: User[]; identity: Identity; onCancel: () => void; onCreated: (id: string) => void }) {
  const [kind, setKind] = useState(initialKind); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [research, setResearch] = useState(() => initialResearch(initialKind));
  const pending = useRef<{ signature: string; key: string } | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError(""); const data = new FormData(event.currentTarget);
    try {
      const fields: Fields = kind === "task" ? { status: "todo", priority: String(data.get("priority")), owner_object_id: String(data.get("owner_object_id")), due_at: new Date(String(data.get("due_at"))).toISOString(), work_kind: String(data.get("work_kind")), project: String(data.get("project") || "") || null, agent_suitable: data.get("agent_suitable") === "on" } : kind === "note" ? { content_format: String(data.get("content_format")), intent: String(data.get("intent")) } : kind === "entity" ? { entity_kind: String(data.get("entity_kind") || "other") } : {};
      if (kind === "task" && String(data.get("github_issue_url")).trim()) fields.github_issue_url = String(data.get("github_issue_url")).trim();

      if (["source", "theme", "event"].includes(kind)) { for (const key of Object.keys(fields)) delete fields[key]; Object.assign(fields, research); }
      const operations = [{ op: "create_object", local_ref: "new", kind, title: String(data.get("title")), description: String(data.get("description")), body: String(data.get("body") || ""), fields }];
      const signature = JSON.stringify(operations);
      if (pending.current?.signature !== signature) pending.current = { signature, key: crypto.randomUUID() };
      const result = await api.apply(operations, pending.current.key); onCreated(result.local_refs.new);
    } catch (cause) { setError(message(cause)); } finally { setBusy(false); }
  };
  return <CreateModal title={`New ${kind}`} onClose={onCancel}><form className={`create-form ${kind === "task" ? "task-create-form" : "typed-create-form"}`} onSubmit={submit}>
    <input className="create-title" name="title" required maxLength={200} autoFocus placeholder={`${titleCase(kind)} title`} aria-label="Title" />
    <textarea className="create-body" name="description" rows={5} maxLength={600} required placeholder="State plainly what this record is and what it concerns." aria-label="Description" />
    {kind === "task" && <div className="task-fields"><label>Assigned to<select name="owner_object_id" required defaultValue={identity.id}>{users.map(user => <option key={user.id} value={user.id}>{user.title}</option>)}</select></label><label>Project<input name="project" maxLength={64} pattern="[A-Za-z][A-Za-z0-9-]{0,63}" placeholder="Project name (optional)" /></label><label>Due date &amp; time (required; local time)<input name="due_at" type="datetime-local" required /></label><label>Work kind<select name="work_kind"><option value="general">general</option><option value="code">code</option></select></label><label>Priority<select name="priority" defaultValue="medium">{["low", "medium", "high"].map(priority => <option key={priority}>{priority}</option>)}</select></label><label>GitHub Issue (optional)<input name="github_issue_url" type="url" pattern={issuePattern} placeholder="https://github.com/owner/repo/issues/1" /></label><label>Brief (required before doing)<textarea name="body" placeholder="Outcome, acceptance, next action, and any inputs or blockers" /></label></div>}
    {["source", "theme", "event"].includes(kind) && <ResearchInputs kind={kind} fields={research} change={setResearch} />}
    {kind === "entity" && <Field label="Kind"><input name="entity_kind" placeholder="organization" /></Field>}
    {kind === "note" && <div className="task-fields"><label>Intent<select name="intent"><option>idea</option><option>fact</option></select></label><label>Format<select name="content_format"><option value="markdown">Markdown</option><option value="plain_text">Plain text</option></select></label></div>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {kind !== "task" && <Field label="Body"><textarea name="body" placeholder="Short supporting detail (optional)" /></Field>}
    <p className="muted">Title + description + body: maximum 500 tokens. Long content belongs in an Artifact.</p>
    <div className="create-footer">{chooseKind ? <Field label="Type"><select value={kind} onChange={event => { setKind(event.target.value as WritableKind); setResearch(initialResearch(event.target.value)); setError(""); }}>{writableKinds.map(kind => <option key={kind}>{kind}</option>)}</select></Field> : <span className="property-chip">{titleCase(kind)}</span>}{kind === "task" && <label className="property-chip"><input type="checkbox" name="agent_suitable" />Agent suitable</label>}<div className="create-actions"><button type="button" className="ghost" onClick={onCancel}>Cancel</button><button className="primary" disabled={busy || (kind === "task" && !users.length)}>{busy ? "Creating…" : `Create ${kind}`}</button></div></div>
  </form></CreateModal>;
}

function Access({ identity, users, refreshKey, onUsersChanged }: { identity: Identity; users: User[]; refreshKey: number; onUsersChanged: () => void }) {
  const [tokens, setTokens] = useState<Credential[]>([]); const [secret, setSecret] = useState(""); const [error, setError] = useState(""); const [notice, setNotice] = useState(""); const [busy, setBusy] = useState(false);
  const [userKind, setUserKind] = useState("human");
  useEffect(() => { let active = true; api.tokens().then(items => { if (active) setTokens(items); }).catch(cause => { if (active) setError(message(cause)); }); return () => { active = false; }; }, [refreshKey]);
  const run = async (action: () => Promise<void>) => { setError(""); setNotice(""); setBusy(true); try { await action(); } catch (cause) { setError(message(cause)); } finally { setBusy(false); } };
  return <section className="detail-page"><div className="record-page"><div className="record-primary"><h1 className="detail-title">Access</h1><p className="detail-description">Records are shared with authenticated organisation users. Data read by an external agent leaves Commons for its environment/provider. Credentials act as their selected User, never as a Task's assignee. Assignment starts no execution.</p>{error && <p className="form-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Section title="Agent credentials"><form className="form" onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); void run(async () => { const result = await request<{ token: string }>("tokens", { label: data.get("label"), write_kinds: data.getAll("kind"), account_id: data.get("account_id") || identity.id }); setSecret(result.token); setTokens(await api.tokens()); }); }}>
      {identity.role === "admin" && <Field label="Credential identity"><select name="account_id" defaultValue={identity.id}><option value={identity.id}>My account</option>{users.filter(user => user.user_kind === "agent").map(user => <option key={user.id} value={user.id}>{user.title} · agent</option>)}</select></Field>}
      <Field label="Label"><input name="label" required maxLength={100} /></Field><fieldset><legend>Allowed write kinds</legend>{[...writableKinds, "thread"].map(kind => <label className="check" key={kind}><input type="checkbox" name="kind" value={kind} disabled={identity.role === "reader"} />{kind}</label>)}</fieldset><p className="muted">Thread permission allows supplied capture; it does not enable collection. Enable or disable each source on its execution host.</p><button className="secondary" disabled={busy}>Create credential</button></form>{secret && <div className="secret-display"><label>Copy now; not stored in browser storage<input readOnly value={secret} aria-label="New agent token" /></label><button className="text-button" onClick={() => setSecret("")}>Dismiss secret</button></div>}{tokens.map(token => <article className="credential-row" key={token.id}><strong>{token.label}</strong><span>{users.find(user => user.id === token.account_id)?.title ?? "Account"} · {token.write_kinds.join(", ") || "read only"}</span>{token.revoked ? <span>Revoked</span> : <button className="text-button" disabled={busy} onClick={() => void run(async () => { await request(`tokens/${token.id}/revoke`, {}); setSecret(""); setTokens(await api.tokens()); })}>Revoke {token.label}</button>}</article>)}</Section>
    {identity.role === "admin" && <><Section title="Create named user"><form className="form" onSubmit={event => { event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); void run(async () => { await request("users", data); form.reset(); setUserKind("human"); onUsersChanged(); setNotice("User created."); }); }}>
      <Field label="User kind"><select name="user_kind" value={userKind} onChange={event => setUserKind(event.target.value)}><option value="human">Human</option><option value="agent">Agent</option></select></Field>
      <Field label="Username"><input name="username" required maxLength={80} autoComplete="off" /></Field><Field label="Display name"><input name="title" required maxLength={200} /></Field>
      {userKind === "human" ? <Field label="Password"><input name="password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></Field> : <p className="muted">Agents have no password login. An administrator issues their scoped credentials above.</p>}
      <Field label="Role"><select name="role" key={userKind}><option>member</option><option>reader</option>{userKind === "human" && <option>admin</option>}</select></Field><button className="secondary" disabled={busy}>Create user</button></form></Section>
      <Section title="User avatars"><form className="form" onSubmit={event => { event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); const user = users.find(user => user.id === data.get("user_id")); void run(async () => { if (!user) throw new Error("Select a User."); await api.uploadAvatar(user, data.get("image") as File, String(data.get("source"))); onUsersChanged(); form.reset(); setNotice("Avatar saved."); }); }}>
        <Field label="Avatar user"><select name="user_id" required>{users.map(user => <option key={user.id} value={user.id}>{user.title}</option>)}</select></Field>
        <Field label="Avatar image"><input name="image" type="file" accept="image/png,image/jpeg,image/webp" required /></Field><Field label="Image source / permission"><input name="source" required maxLength={600} placeholder="Owner supplied for this installation" /></Field>
        <p className="muted">PNG, JPEG or WebP, up to 256 KiB. Stored privately with this installation; visible to its authenticated users.</p><button className="secondary" disabled={busy}>Upload avatar</button>
      </form></Section></>}
  </div></div></section>;
}

function CreateModal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const panel = useRef<HTMLElement>(null);
  const previousFocus = useRef(document.activeElement as HTMLElement | null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = previousFocus.current;
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); close.current(); }
      if (event.key === "Tab") {
        const controls = [...(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href]') ?? [])];
        const first = controls[0]; const last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    window.addEventListener("keydown", keys);
    return () => { window.removeEventListener("keydown", keys); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><section ref={panel} className="create-modal" role="dialog" aria-modal="true" aria-labelledby="create-modal-title"><header className="create-modal-head"><div><span className="modal-mark">C</span><span className="modal-separator">›</span><h2 id="create-modal-title">{title}</h2></div><button className="modal-close" aria-label="Close" onClick={onClose}>×</button></header>{children}</section></div>;
}
function Actor({ id, users }: { id: string | null; users: User[] }) { const user = users.find(user => user.id === id); return user ? <AttributionStack users={[userAttribution(user, "writer")]} /> : <span role="img" aria-label={id ? `Unresolved User ${id}` : "Attribution not recorded"}>♙</span>; }
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="field"><span>{label}</span>{children}</label>; }
function Property({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) { return <div className={`property ${className}`.trim()}><span>{label}</span><div>{children}</div></div>; }
function Section({ title, children }: { title: string; children: ReactNode }) { return <section className="detail-section"><header><h3>{title}</h3></header>{children}</section>; }
function Blank({ error }: { error: string }) { return <div className="blank-state" role={error ? "alert" : "status"}><span>◇</span><h2>{error ? "Could not load" : "Loading"}</h2><p>{error || "Reading the shared record…"}</p></div>; }
