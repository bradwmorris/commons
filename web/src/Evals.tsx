import { useEffect, useState, useRef } from "react";
import { request } from "./api";
import { interceptNavigation, navigate } from "./routing";
import { StoredText } from "./StoredText";
import { PendingWrites } from "./pendingWrites";
import "./evals.css";

const writes = new PendingWrites<{ id: string }>();
type Test = { id: string; title: string; request: string };
type Run = { id: string; test_id: string; created_at: string; snapshot: Test };
type Attempt = { id: string; arm: "without" | "with"; payload: {
  status: string; output: string; error: string;
  files: { name: string }[]; links: { label: string; url: string }[];
} };
type TestDetail = { test: Test; runs: Run[] };
type RunDetail = { run: Run; attempts: Attempt[] };
const message = (e: unknown) => e instanceof Error ? e.message : "Could not load evals.";
function Link({ path, children }: { path: string; children: React.ReactNode }) { return <a href={path} onClick={e => interceptNavigation(e, path)}>{children}</a>; }
function Output({ attempt }: { attempt?: Attempt }) {
  if (!attempt) return <p className="muted">No output yet.</p>;
  const a = attempt.payload;
  return <>
    {a.output ? <StoredText body={a.output} /> : !a.error && <p className="muted">No output yet.</p>}
    {a.status === "partial" && !a.error && <p className="muted">Incomplete.</p>}
    {a.error && <p role="note" className="form-error">{a.error}</p>}
    {!!(a.files.length + a.links.length) && <ul className="eval-files">{a.files.map((file, index) => <li key={index}><a download={file.name} href={`/api/eval-files/${attempt.id}/${index}`}>{file.name}</a></li>)}{a.links.map((link, index) => <li key={`link-${index}`}><a href={link.url} target="_blank" rel="noreferrer">{link.label}</a></li>)}</ul>}
  </>;
}
export function EvalWorkspace({ id, runView, writable, refreshKey, onLoaded }: { id: string | null; runView: boolean; writable: boolean; refreshKey: number; onLoaded: (value: { id: string; title: string }) => void }) {
  const owner = useRef({});
  const [tests, setTests] = useState<Test[]>([]);
  const [detail, setDetail] = useState<TestDetail | null>(null);
  const [comparison, setComparison] = useState<RunDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setDetail(null); setComparison(null); setCreating(false);
    async function load() {
      if (!id) {
        const p = await request<{ tests: Test[]; next_offset: number | null }>(`evals?q=${encodeURIComponent(query)}`, undefined, controller.signal);
        if (!controller.signal.aborted) { setTests(p.tests); setOffset(p.next_offset); }
      } else if (runView) {
        const run = await request<RunDetail>(`eval-runs/${id}`, undefined, controller.signal);
        if (!controller.signal.aborted) setComparison(run);
      } else {
        const d = await request<TestDetail>(`evals/${id}`, undefined, controller.signal);
        const run = d.runs.length ? await request<RunDetail>(`eval-runs/${d.runs[0].id}`, undefined, controller.signal) : null;
        if (!controller.signal.aborted) { setDetail(d); setComparison(run); }
      }
    }
    void load().catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [id, runView, query, refreshKey]);
  const selected = comparison?.run.snapshot ?? detail?.test;
  useEffect(() => { if (selected && id) onLoaded({ id, title: selected.title }); }, [id, selected, onLoaded]);
  return <section className="eval-page">
    <header><h1>{selected?.title ?? "Evals"}</h1></header>
    {error && <p role="alert" className="form-error">{error}</p>}
    {loading ? <p role="status">Loading…</p> : selected ? <>
      <Link path="/evals">All evals</Link>
      <div className="eval-request"><StoredText body={selected.request} /></div>
      {detail && detail.runs.length > 1 && <label className="eval-run-picker">Saved run<select aria-label="Saved run" value={comparison?.run.id} onChange={e => navigate(`/eval-runs/${e.target.value}`)}>{detail.runs.map((r, index) => <option key={r.id} value={r.id}>{index === 0 ? "Latest · " : ""}{new Date(r.created_at).toLocaleString()}</option>)}</select></label>}
      <div className="eval-pair">{(["without", "with"] as const).map(arm => <article key={arm}><h2>{arm === "without" ? "Without Commons" : "With Commons"}</h2><Output attempt={comparison ? [...comparison.attempts].reverse().find(a => a.arm === arm) : undefined} /></article>)}</div>
    </> : !id && <>
      <div className="eval-toolbar"><label>Find an eval<input value={query} onChange={e => setQuery(e.target.value)} type="search" disabled={busy} /></label>{writable && <button onClick={() => setCreating(v => !v)}>New eval</button>}</div>
      {creating && <form className="form" onSubmit={async e => {
        e.preventDefault(); const data = new FormData(e.currentTarget); setBusy(true); setError("");
        const body = { contract_version: "commons.evals/1", operation: { op: "create_test", title: data.get("title"), request: data.get("request"), configuration: {} } };
        try { const result = await writes.resolve(owner.current, body, async key => { await request("evals", { ...body, idempotency_key: key, validate_only: true }); return request<{ id: string }>("evals", { ...body, idempotency_key: key }); }, async accepted => { await request(`evals/${accepted.id}`); }); navigate(`/evals/${result.id}`); }
        catch (e) { setError(message(e)); } finally { setBusy(false); }
      }}><label>Name<input name="title" required maxLength={200} /></label><label>Task or question<textarea name="request" required maxLength={100000} rows={5} /></label><button disabled={busy}>{busy ? "Saving…" : "Save eval"}</button></form>}
      {tests.length ? <ul className="eval-list">{tests.map(t => <li key={t.id}><Link path={`/evals/${t.id}`}>{t.title}</Link></li>)}</ul> : <p>No evals yet.</p>}
      {offset !== null && <button disabled={busy} onClick={async () => { setBusy(true); try { const page = await request<{ tests: Test[]; next_offset: number | null }>(`evals?q=${encodeURIComponent(query)}&offset=${offset}`); setTests(t => [...t, ...page.tests]); setOffset(page.next_offset); } catch (e) { setError(message(e)); } finally { setBusy(false); } }}>Load more</button>}
    </>}
  </section>;
}
