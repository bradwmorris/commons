import { useEffect, useRef, useState, type FormEvent } from "react";
import { request } from "./api";
import { interceptNavigation } from "./routing";

type Match = { id: string; title: string; match: { read?: { resource: string; id: string; expected_revision: number; offset: number; limit: number } } };
type Result = { mode: string; truncated: boolean; context: { objects: Match[] } };
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "Search failed.";

export function ThreadSearch() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [window, setWindow] = useState<{ title: string; text: string; partial: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const search = async (event: FormEvent) => {
    event.preventDefault();
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError(""); setWindow(null); setResult(null);
    try { const next = await request<Result>(`retrieve?${new URLSearchParams({ q: query, scope: "threads", neighbours: "0", limit: "10" })}`, undefined, controller.signal); if (!controller.signal.aborted) setResult(next); }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  };
  const open = async (candidate: Match) => {
    const read = candidate.match.read;
    if (!read || read.resource !== "thread_text") return;
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError(""); setWindow(null);
    try {
      const text = await request<{ text: string; coverage?: { status?: string } }>(`threads/${read.id}/text?${new URLSearchParams({ expected_revision: String(read.expected_revision), offset: String(read.offset), limit: String(read.limit) })}`, undefined, controller.signal);
      if (!controller.signal.aborted) setWindow({ title: candidate.title, text: text.text, partial: text.coverage?.status !== "complete" });
    } catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  };
  return <section className="detail-section thread-search" aria-label="Conversation search">
    <form className="thread-search-form" onSubmit={event => void search(event)}>
      <label>Search conversations<input aria-label="Search conversations" value={query} maxLength={500} onChange={event => setQuery(event.target.value)} /></label>
      <button disabled={busy || !query.trim()} type="submit">Search stored text</button>
    </form>
    <p className="muted">Searches stored visible messages, tool bodies and current corrections. Capture may be partial. Native span telemetry is separate.</p>
    {busy && <p role="status">Searching or reading…</p>}
    {error && <p role="alert">{error}</p>}
    {result && <><p className="muted">{result.mode === "hybrid" ? "Keyword and semantic search" : "Keyword search"} · Up to 10 ranked matches{result.truncated ? " · Results truncated" : ""}</p>
      {!result.context.objects.length && <p>No matching stored text found.</p>}
      <ul>{result.context.objects.map(candidate => <li key={candidate.id}><a href={`/threads/${candidate.id}`} onClick={event => interceptNavigation(event, `/threads/${candidate.id}`)}>{candidate.title}</a>{candidate.match.read?.resource === "thread_text" && <button className="secondary" disabled={busy} onClick={() => void open(candidate)}>Read matching text</button>}</li>)}</ul></>}
    {window && <section aria-label="Matching conversation text"><h3>{window.title}</h3>{window.partial && <p className="muted">Partial capture; this window does not establish a complete transcript.</p>}<pre className="source-text-preview">{window.text}</pre></section>}
  </section>;
}
