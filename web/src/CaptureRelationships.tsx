import { useEffect, useMemo, useState } from "react";
import { api, request } from "./api";
import { FocusedObjectGraph } from "./ConnectionGraph";
import { ObjectTypeBadge } from "./RecordVisuals";
import { connectionPath, interceptNavigation, objectPath } from "./routing";
import type { Connection, ConnectionGraphSnapshot, ObjectKind } from "./types";

type Reference = { id: string; title: string | null; kind: ObjectKind | "trace" | "user" | "artifact" | null; relation: string; archived_at: string | null };
type ReferencePage = { references: Reference[]; next_offset: number | null };
const labels: Record<string, string> = { participant: "Participant", parent_thread: "Parent thread", run: "Trace", linked_run_work: "Work linked through a Run", run_actor: "Run actor", actor: "Actor", thread: "Thread", primary_object: "Primary object", consulted: "Read", created: "Created", updated: "Updated", trace: "Trace", parent_run: "Parent Run", child_run: "Child Run" };
const pathFor = (reference: Reference) => reference.kind === "trace" ? `/traces/${reference.id}` : reference.kind === "user" ? `/users/${reference.id}` : objectPath(reference.id);

export function CaptureRelationships({ id, title, section, refreshKey }: { id: string; title: string; section: "threads" | "traces"; refreshKey: number }) {
  const focusId = section === "traces" ? `run:${id}` : id;
  const [references, setReferences] = useState<ReferencePage | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setReferences(null); setError("");
    Promise.all([
      request<ReferencePage>(`${section}/${id}/relationships?limit=50&offset=${offset}`, undefined, controller.signal),
      section === "threads" ? api.connections(id, controller.signal) : Promise.resolve([]),
    ]).then(([refs, links]) => { if (!controller.signal.aborted) { setReferences(refs); setConnections(links); } })
      .catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not load relationships."); });
    return () => controller.abort();
  }, [id, section, offset, refreshKey]);
  const graph = useMemo<ConnectionGraphSnapshot>(() => {
    const nodes: ConnectionGraphSnapshot["nodes"] = [{ id: focusId, title, kind: section === "threads" ? "thread" : "trace", href: `/${section}/${id}` }];
    const edges: ConnectionGraphSnapshot["edges"] = [];
    for (const link of connections.slice(0, 200)) {
      nodes.push(link.from_object, link.to_object);
      edges.push({ id: link.id, source_object_id: link.from_id, target_object_id: link.to_id, kind: link.kind, description: link.explanation });
    }
    for (const ref of references?.references ?? []) {
      if (!ref.kind || !ref.title) continue;
      const targetId = ref.kind === "trace" ? `run:${ref.id}` : ref.id;
      nodes.push({ id: targetId, title: ref.title, kind: ref.kind, href: pathFor(ref) });
      edges.push({ id: `${ref.relation}:${ref.id}`, source_object_id: focusId, target_object_id: targetId, kind: ref.relation, description: `Supplied reference: ${labels[ref.relation] ?? ref.relation}`, reference: true });
    }
    const unique = [...new Map(nodes.map(node => [node.id, node])).values()];
    return { nodes: unique, edges, node_count: unique.length, connection_count: edges.length, total_connections: edges.length, continuation: { objects: null, connections: null } };
  }, [id, focusId, title, section, references, connections]);
  return <>
    <section className="detail-section" aria-label="Related objects"><header><h3>Related objects</h3></header>
      {error ? <p role="alert">{error}</p> : !references ? <p role="status">Loading relationships…</p> : <>
        {!connections.length && !references.references.length && <p className="muted">No related objects recorded.</p>}
        <div className="connections related-object-list">
          {connections.map(link => {
            const outgoing = link.from_id === id, target = outgoing ? link.to_object : link.from_object;
            const path = objectPath(target.id);
            return <article className="related-object-row" key={link.id}><ObjectTypeBadge kind={target.kind} compact /><span className="related-object-copy"><a className="related-object-title" href={path} onClick={event => interceptNavigation(event, path)}>{target.title}</a><span className="related-object-description">{link.explanation}</span></span><span className="related-object-meaning">{outgoing ? "→" : "←"} {link.kind.replaceAll("_", " ")}</span><a href={connectionPath(link.id)} onClick={event => interceptNavigation(event, connectionPath(link.id))}>Connection</a></article>;
          })}
          {references.references.map(ref => <article className="related-object-row" key={`${ref.relation}:${ref.id}`}>
            {ref.kind && <ObjectTypeBadge kind={ref.kind} compact />}<span className="related-object-copy">{ref.title && ref.kind ? <a className="related-object-title" href={pathFor(ref)} onClick={event => interceptNavigation(event, pathFor(ref))}>{ref.title}</a> : <span>Unavailable object · {ref.id}</span>}<span className="related-object-description">{labels[ref.relation] ?? ref.relation} · supplied reference{ref.archived_at ? " · archived" : ""}</span></span>
          </article>)}
        </div>
        {(offset > 0 || references.next_offset !== null) && <div className="inline-editor-actions" aria-label="Relationship pagination"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous relationships</button><span>Page {offset / 50 + 1}</span><button disabled={references.next_offset === null} onClick={() => setOffset(references.next_offset!)}>Next relationships</button></div>}
        <p className="muted">Recorded references include Trace activity and supplied links. Saved Connections retain their explanations. No links are inferred from message text.</p>
        {connections.length > 200 && <p role="status">The map shows the first 200 saved Connections; the list above includes all saved Connections.</p>}
        {(offset > 0 || references.next_offset !== null) && <p role="status">The map shows this page of supplied references and saved Connections.</p>}
      </>}
    </section>
    {references && !error && <FocusedObjectGraph objectId={focusId} objectTitle={title} suppliedGraph={graph} />}
  </>;
}
