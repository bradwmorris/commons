import { useEffect, useState } from "react";
import { request } from "./api";
import { AttributionStack, userAttribution } from "./RecordVisuals";
import { ObjectId } from "./ObjectIdentity";
import { interceptNavigation } from "./routing";
import type { User } from "./types";

export function UserList({ users, query, sort }: { users: User[]; query: string; sort: string }) {
  const rows = [...users].sort((a,b) => sort === "connected" ? (b.connection_count ?? 0) - (a.connection_count ?? 0) : (b.metadata.created_at ?? "").localeCompare(a.metadata.created_at ?? "")).filter(user => `${user.title} ${user.user_kind}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="list-view" aria-label="Users"><div className="list-group-head"><strong>All users</strong><span>{rows.length}</span></div><div className="record-list">{rows.map(user => <div className="record" key={user.id}>
    <a className="record-open" href={`/users/${user.id}`} aria-label={`Open ${user.title}`} onClick={e => interceptNavigation(e, `/users/${user.id}`)} />
    <span className="record-kind"><AttributionStack users={[userAttribution(user)]} /></span><span className="record-id"><ObjectId id={user.id} rowPill /></span>
    <span className="record-main"><span className="record-title"><strong>{user.title}</strong></span></span><p className="description-snippet">{user.user_kind} · {user.active ? user.role : "Historical identity · no login access"}</p><time>{user.active ? "Active" : "Historical"}</time>
  </div>)}</div>{!rows.length && <p className="empty-list">No users match.</p>}</section>;
}
export function UserDetail({ id, refreshKey, onLoaded }: { id: string; refreshKey: number; onLoaded: (v: { id: string; title: string }) => void }) {
  const [user, setUser] = useState<User | null>(null); const [error, setError] = useState("");
  useEffect(() => { const c = new AbortController(); setUser(null); setError(""); void request<{ user: User }>(`users/${id}`, undefined, c.signal).then(r => { setUser(r.user); onLoaded({ id, title: r.user.title }); }).catch(e => { if (!c.signal.aborted) setError(String(e)); }); return () => c.abort(); }, [id, refreshKey, onLoaded]);
  return <section className="detail-page"><div className="record-page"><div className="record-primary">{error ? <p role="alert">{error}</p> : !user ? <p role="status">Loading user…</p> : <><h1 className="detail-title">{user.title}</h1><p className="detail-description"><AttributionStack users={[userAttribution(user)]} /> {user.user_kind} · {user.active ? user.role : "Historical identity; login disabled"}</p><details className="detail-disclosure"><summary>Details</summary><p>{user.username || "No login name"}</p><p>{user.id}</p><p>Revision {user.revision}</p></details></>}</div></div></section>;
}
