import { cloneElement, useEffect, useId, useState, type ReactElement } from "react";
import { api, request } from "./api";
import { ObjectTypeBadge, RecordImage } from "./RecordVisuals";
import { artifactPath, interceptNavigation } from "./routing";
import { artifactTitle } from "./Artifacts";
import type { Artifact, ArtifactSummary, Detail, Fields, JsonValue, ObjectKind, RecordObject, User } from "./types";

const text = (v: unknown) => typeof v === "string" ? v : "";
const label = (key: string) => key.replaceAll("_", " ").replace(/^./, s => s.toUpperCase());
const kinds = ["person", "organization", "product", "project", "publication", "place", "concept", "other"];
const sourceKinds = ["article", "paper", "podcast_episode", "video", "book", "report", "document", "dataset", "web_page", "social_post", "other"];
export const researchKinds = ["source", "theme", "event", "entity", "note"];
export function initialResearch(kind: string): Fields {
  return kind === "source" ? { source_kind: "article" } : kind === "entity" ? { entity_kind: "other" } : kind === "note" ? { intent: "idea", content_format: "markdown" } : {};
}
function Field({ name, children }: { name: string; children: ReactElement<{ "aria-labelledby"?: string }> }) { const id = useId(); return <label className="research-field"><span id={id}>{name}</span>{cloneElement(children, { "aria-labelledby": id })}</label>; }

export function ResearchInputs({ kind, fields, change, artifacts = [] }: { kind: ObjectKind; fields: Fields; change: (v: Fields) => void; artifacts?: ArtifactSummary[] }) {
  const [error, setError] = useState("");
  const set = (key: string, value: JsonValue) => change({ ...fields, [key]: value });
  const input = (key: string, required = false, placeholder?: string) => <Field key={key} name={label(key)}><input value={text(fields[key])} required={required} placeholder={placeholder} onChange={e => set(key, e.target.value || null)} /></Field>;
  const select = (key: string, values: string[], optional = false) => <Field key={key} name={label(key)}><select value={text(fields[key])} onChange={e => set(key, e.target.value || null)}>{optional && <option value="">Not recorded</option>}{values.map(v => <option key={v} value={v}>{label(v)}</option>)}</select></Field>;
  const locator = (fields.source_locator && typeof fields.source_locator === "object" && !Array.isArray(fields.source_locator) ? fields.source_locator : {}) as Fields;
  return <div className="research-inputs">
    {kind === "source" && <>{select("source_kind", sourceKinds)}{["canonical_uri", "byline", "publisher", "published_at", "last_accessed_at", "original_language", "original_media_type", "original_artifact_reference"].map(k => input(k, false, k.endsWith("_at") ? "RFC3339 timestamp, if known" : undefined))}{select("published_at_precision", ["year", "month", "day", "instant"], true)}<Field name="Current artifact"><select value={text(fields.current_artifact_id)} onChange={e => set("current_artifact_id", e.target.value || null)}><option value="">Not set</option>{artifacts.filter(a => a.body_omitted && a.size_bytes > 0 && a.capture_outcome === "complete").map(a => <option key={a.id} value={a.id}>{a.title || a.kind} · {a.id.slice(0, 8)}</option>)}</select></Field></>}
    {kind === "theme" && input("slug", true, "lowercase-hyphenated-name")}
    {kind === "event" && <>{["starts_at", "ends_at"].map(k => <div key={k}>{input(k, false, "2024, 2024-06, 2024-06-15, or RFC3339")}{select(`${k}_precision`, ["year", "month", "day", "instant"], true)}</div>)}{input("timezone", false, "Australia/Sydney (optional)")}</>}
    {kind === "entity" && <>{select("entity_kind", kinds)}{input("image_url", false, "https://…")}</>}
    {kind === "note" && <><Field name="Intent"><select value={text(fields.intent)} onChange={e => change({ ...fields, intent: e.target.value, source_artifact_id: null, source_locator: null })}>{["idea", "excerpt", "fact", "insight", "question"].map(v => <option key={v}>{v}</option>)}</select></Field>{select("content_format", ["markdown", "plain_text", ...(fields.content_format === "plain" ? ["plain"] : [])])}
      {fields.intent === "excerpt" && <>{input("source_artifact_id", true, "Immutable artifact UUID")}<Field name="Locator kind"><select value={text(locator.kind)} onChange={e => set("source_locator", { kind: e.target.value })}><option value="">Choose locator</option>{["text_offset", "page", "timestamp", "section"].map(k => <option key={k}>{k}</option>)}</select></Field>
        {(locator.kind === "text_offset" ? ["start", "end"] : locator.kind === "page" ? ["page", "end_page"] : locator.kind === "timestamp" ? ["start_ms", "end_ms"] : []).map(k => <Field key={k} name={label(k)}><input type="number" min={k.includes("page") ? 1 : 0} value={typeof locator[k] === "number" ? locator[k] : ""} onChange={e => { const next = { ...locator }; if (e.target.value) next[k] = Number(e.target.value); else delete next[k]; set("source_locator", next); }} /></Field>)}
        <Field name="Locator label"><input value={text(locator.label)} onChange={e => { const next = { ...locator }; if (e.target.value) next.label = e.target.value; else delete next.label; set("source_locator", next); }} /></Field><p className="muted">Text offsets count Unicode characters, starting at zero, with an exclusive end. The excerpt must match the original exactly.</p></>}
    </>}{error && <p role="alert">{error}</p>}
  </div>;
}

// Structured historical fields remain readable without making raw JSON the primary UI.
export function Values({ value }: { value: JsonValue | undefined }) {
  if (value == null) return <span className="muted">Not recorded</span>;
  if (Array.isArray(value)) return <ul>{value.map((v, i) => <li key={i}><Values value={v} /></li>)}</ul>;
  if (typeof value === "object") return <dl className="record-values">{Object.entries(value).map(([k, v]) => <div key={k}><dt>{label(k)}</dt><dd><Values value={v} /></dd></div>)}</dl>;
  return typeof value === "string" && /^https?:\/\//i.test(value)
    ? <a className="record-scalar" href={value} target="_blank" rel="noreferrer">{value}</a>
    : <span className="record-scalar">{String(value)}</span>;
}

export function ResearchDetails({ detail, editable, onSaved, onDirty }: { detail: Detail; editable: boolean; onSaved: () => Promise<void>; onDirty: (v: boolean) => void }) {
  const [draft, setDraft] = useState<RecordObject | null>(null);
  const [error, setError] = useState("");
  const object = detail.object;
  const rows: [string, string][] = object.kind === "source"
    ? [["source_kind", "Kind"], ["canonical_uri", "Canonical URL"], ["byline", "Byline"], ["publisher", "Publisher"], ["published_at", "Published"], ["last_accessed_at", "Accessed"], ["original_language", "Original language"], ["original_media_type", "Original media type"], ["original_artifact_reference", "Original reference"]]
    : object.kind === "event" ? [["starts_at", "Starts"], ["ends_at", "Ends"], ["timezone", "Timezone"]]
    : object.kind === "entity" ? [["entity_kind", "Kind"], ["image_url", "Image"]]
    : object.kind === "note" ? [["intent", "Intent"], ["content_format", "Format"]]
    : [["slug", "Slug"]];
  const secondary = Object.fromEntries(Object.entries(object.fields).filter(([key]) =>
    !rows.some(([name]) => name === key || `${name}_precision` === key && (object.fields[name] != null || object.fields[key] == null)) &&
    !(object.kind === "note" && key === "content") && !["current_artifact_id", "source_artifact_id"].includes(key)));
  return <section className="properties-block research-properties" aria-label={`${label(object.kind)} properties`}>
    <div className="properties-grid">{rows.map(([key, name]) => <div className="property" key={key}><span>{name}</span><div>
      {key.endsWith("_kind") && <ObjectTypeBadge kind={object.kind} />}
      <Values value={key.endsWith("_kind") ? text(object.fields[key]).replaceAll("_", " ") || null : object.fields[key]} />
      {key === "image_url" && typeof object.fields[key] === "string" && <RecordImage key={object.fields[key]} src={object.fields[key]} alt={object.title} />}
      {object.fields[key] != null && object.fields[`${key}_precision`] != null && <span className="muted">({text(object.fields[`${key}_precision`])})</span>}
    </div></div>)}</div>
    {typeof object.fields.current_artifact_id === "string" && <p className="excerpt-reference"><a href={artifactPath(object.id, object.fields.current_artifact_id)} onClick={event => interceptNavigation(event, artifactPath(object.id, text(object.fields.current_artifact_id)))}>Read current capture</a></p>}
    {typeof object.fields.source_artifact_id === "string" && <ExcerptSource key={`${object.id}:${object.revision}`} object={object} />}
    {Object.keys(secondary).length > 0 && <details className="detail-disclosure"><summary>Additional properties</summary><Values value={secondary} /></details>}
    {draft ? <form className="form" onSubmit={async e => { e.preventDefault(); try { await api.update(draft, { fields: draft.fields }); onDirty(false); setDraft(null); await onSaved(); } catch (e) { setError(String(e)); } }}><ResearchInputs kind={object.kind} fields={draft.fields} artifacts={detail.artifacts} change={fields => setDraft({ ...draft, fields })} /><div className="create-actions"><button className="primary">Save research details</button><button type="button" onClick={() => { setDraft(null); onDirty(false); setError(""); }}>Cancel details</button></div><p className="muted">This draft uses revision {draft.revision}. Conflicts preserve your inputs.</p></form> : editable && <button className="secondary" onClick={() => { setDraft(structuredClone(object)); onDirty(true); }}>Edit research details</button>}
    {error && <p role="alert" className="form-error">{error}</p>}
  </section>;
}

function ExcerptSource({ object }: { object: RecordObject }) {
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void request<{ artifact: Artifact }>(`artifacts/${encodeURIComponent(text(object.fields.source_artifact_id))}`)
      .then(result => { if (active) setArtifact(result.artifact); }).catch(cause => { if (active) setError(String(cause)); });
    return () => { active = false; };
  }, [object.fields.source_artifact_id]);
  if (!artifact) return <p className="muted" role={error ? "alert" : "status"}>{error ? `Excerpt source unavailable: ${error}` : "Loading excerpt source…"}</p>;
  const path = `${artifactPath(artifact.object_id, artifact.id)}?excerpt=${encodeURIComponent(object.id)}`;
  const locator = object.fields.source_locator;
  return <div className="excerpt-reference"><a href={path} onClick={event => interceptNavigation(event, path)}>Read original excerpt evidence · {artifactTitle(artifact)}</a>
    <p className="muted">{artifact.capture_outcome} capture · {artifact.body === null ? "Original bytes unavailable; no highlight shown." : locator && typeof locator === "object" && !Array.isArray(locator) && locator.kind === "text_offset" ? "Unicode text offsets; the reader highlights only an exact matching excerpt." : "This locator has no supported highlight. Original evidence remains readable."}</p>
  </div>;
}

export function RecordHistory({ detail, users, editable, onSaved }: { detail: Detail; users: User[]; editable: boolean; onSaved: () => Promise<void> }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const object = detail.object;
  async function apply(op: object) { setBusy(true); setError(""); try { await api.apply([op]); await onSaved(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <section className="detail-section record-history"><header><h3>History and preservation</h3></header>
    {detail.corrections.map(c => <CorrectionEntry key={`${object.revision}:${c.id}`} entry={c} historical={detail.corrections.some(next => next.supersedes_correction_id === c.id)} actor={users.find(user => user.id === c.actor_id)?.title} />)}
    {editable && <details className="detail-disclosure"><summary>Correct evidence</summary><form className="form research-inputs" onSubmit={e => { e.preventDefault(); const d = new FormData(e.currentTarget); const target = String(d.get("target")); void apply({ op: "correct_evidence", object_id: object.id, expected_revision: object.revision, target_type: target === object.id ? "object" : "artifact", target_id: target, reason: d.get("reason"), representation: { body: d.get("body") } }); }}><Field name="Correction target"><select name="target"><option value={object.id}>This Object</option>{detail.artifacts.map(a => <option value={a.id} key={a.id}>{a.title || a.kind} · {a.id.slice(0, 8)}</option>)}</select></Field><Field name="Correction reason"><input name="reason" required /></Field><Field name="Corrected representation"><textarea name="body" required /></Field><button disabled={busy}>Save correction</button></form></details>}
    <details className="detail-disclosure" onToggle={e => { if (e.target === e.currentTarget) setHistoryOpen(e.currentTarget.open); }}><summary>Revision history ({detail.history.length})</summary>{historyOpen && detail.history.map(h => <HistoryEntry key={`${object.revision}:${h.id}`} entry={h} actor={users.find(user => user.id === h.actor_id)?.title} />)}</details>
    <details className="detail-disclosure"><summary>Original provenance and import mapping</summary><Values value={object.provenance} /></details>
    {error && <p role="alert" className="form-error">{error}</p>}
  </section>;
}

function useHistoricalEntry<T>(path: string, key: string, initial: T, omitted: boolean, open: boolean) {
  const [loaded, setLoaded] = useState<T | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open || !omitted) return;
    const controller = new AbortController();
    setLoaded(null); setError("");
    void request<Record<string, T>>(path, undefined, controller.signal)
      .then(result => { if (!controller.signal.aborted) setLoaded(result[key]); })
      .catch(cause => { if (!controller.signal.aborted) setError(String(cause)); });
    return () => controller.abort();
  }, [path, key, omitted, open]);
  return { value: omitted ? loaded : initial, error };
}

function HistoryEntry({ entry, actor }: { entry: Detail["history"][number]; actor?: string }) {
  const [open, setOpen] = useState(false);
  const { value: h, error } = useHistoricalEntry(`history/${entry.id}`, "history", entry, !!entry.state_omitted, open);
  return <details className="detail-disclosure" onToggle={e => { if (e.target === e.currentTarget) setOpen(e.currentTarget.open); }}><summary>Revision {entry.revision} · {entry.action} · {entry.occurred_at}</summary>{open && (error ? <p role="alert">{error} Close and reopen to retry.</p> : !h ? <p role="status">Loading history…</p> : <><p>{h.import_provenance ? "Supplied historical event" : "Server observation"} · <span title={h.actor_id ?? undefined}>{actor ?? h.actor_id ?? "No historical actor claimed"}</span></p><h3>Before</h3><Values value={h.before_state} /><h3>After</h3><Values value={h.after_state} /></>)}</details>;
}

function CorrectionEntry({ entry, historical, actor }: { entry: Detail["corrections"][number]; historical: boolean; actor?: string }) {
  const [open, setOpen] = useState(!historical);
  const { value: c, error } = useHistoricalEntry(`corrections/${entry.id}`, "correction", entry, !!entry.representation_omitted, open);
  return <details className="detail-disclosure" open={open} onToggle={e => { if (e.target === e.currentTarget) setOpen(e.currentTarget.open); }}><summary>{historical ? "Historical" : "Current"} correction · {entry.target_type} · {entry.reason}</summary>{open && (error ? <p role="alert">{error} Close and reopen to retry.</p> : !c ? <p role="status">Loading correction…</p> : <><p>{c.created_at} · <span title={c.actor_id ?? undefined}>{actor ?? c.actor_id ?? "No historical actor claimed"}</span> · {c.import_provenance ? "Imported history" : "Authenticated write"}</p><Values value={c.representation} /><p className="muted">Original evidence remains unchanged above.</p></>)}</details>;
}
