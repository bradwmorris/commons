import { useEffect, useState } from "react";
import { request } from "./api";
import { interceptNavigation } from "./routing";

type Column = { table: string; name: string; type: string; nullable: boolean; position: number };
type Relation = { from_table: string; from_column: string; to_table: string; to_column: string };
type Snapshot = { schema_version: number; columns: Column[]; relationships: Relation[]; object_kinds: string[] };
const descriptions: Record<string, string> = {
  objects: "Your notes, tasks, sources, entities, themes, events and threads.",
  users: "The people and agents with accounts in this Commons.",
  credentials: "Login sessions and access tokens belonging to users.",
  artifacts: "Original documents, transcripts, images and other source material.",
  connections: "Links explaining how two records relate to each other.",
  changes: "The history of changes made to records.",
  request_receipts: "Saved write results that prevent a retried request from being applied twice.",
  traces: "Recorded agent runs associated with a thread.",
  trace_items: "The individual events recorded during an agent run.",
  chunks: "Searchable text and embeddings: one entry per object, multiple for long artifacts.",
};
export function SchemaWorkspace({ id, refreshKey }: { id: string | null; refreshKey: number }) {
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController(); setError("");
    void request<Snapshot>("schema", undefined, controller.signal).then(setData).catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    return () => controller.abort();
  }, [refreshKey]);
  if (error) return <p role="alert">{error}</p>;
  if (!data) return <p role="status">Loading installed schema…</p>;
  const tables = [...new Set(data.columns.map(column => column.table))].sort((a, b) => a === "objects" ? -1 : b === "objects" ? 1 : a.localeCompare(b));
  const selected = id || "objects";
  const columns = data.columns.filter(column => column.table === selected).sort((a, b) => a.position - b.position);
  return <section className="schema-review" aria-label="Installed schema">
    <p className="schema-caption">Installed schema {data.schema_version} · {tables.length} tables</p>
    <div className="schema-layout">
      <nav className="schema-tables" aria-label="Schema tables">{tables.map(table => <a key={table} href={`/schema/${table}`} aria-current={table === selected ? "page" : undefined} onClick={event => interceptNavigation(event, `/schema/${table}`)}><span>{table}</span><small>{data.columns.filter(column => column.table === table).length}</small></a>)}</nav>
      <div className="schema-table-detail">
        <h1>{selected}</h1>
        {!columns.length ? <p role="alert">This table is not in the installed schema.</p> : <>
          <p className="schema-caption">{descriptions[selected] || `${columns.length} columns in the installed database.`}</p>
          <table className="schema-column-table" aria-label={`${selected} columns`}><thead><tr><th>Column</th><th>Type</th><th>Nullable</th></tr></thead><tbody>{columns.map(column => <tr key={column.name}><th scope="row"><span>{column.name}</span>{data.relationships.filter(relation => relation.from_table === selected && relation.from_column === column.name).map(relation => <a key={`${relation.to_table}.${relation.to_column}`} href={`/schema/${relation.to_table}`} title={`References ${relation.to_table}.${relation.to_column}`} onClick={event => interceptNavigation(event, `/schema/${relation.to_table}`)}>→ {relation.to_table}.{relation.to_column}</a>)}</th><td title={column.type}>{column.type}</td><td>{column.nullable ? "Yes" : "No"}</td></tr>)}</tbody></table>
          {selected === "objects" && <p className="schema-kinds">Kinds: {data.object_kinds.join(" · ")}</p>}
        </>}
      </div>
    </div>
  </section>;
}
