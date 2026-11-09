import { useEffect, useRef, useState } from "react";
import { api, request } from "./api";
import { StoredText } from "./StoredText";
import { RecordImage } from "./RecordVisuals";
import { artifactPath, interceptNavigation, navigate, objectPath } from "./routing";
import type { Artifact, ArtifactSummary, RecordObject } from "./types";

export function artifactTitle(item: Artifact | ArtifactSummary) {
  return item.title || [item.metadata.title, item.metadata.filename, item.metadata.original_filename].find(value => typeof value === "string" && value.trim()) as string || "Caller-supplied evidence";
}

export function Artifacts({ object, artifacts, artifactId, editable, onSaved, onDirty }: { object: RecordObject; artifacts: ArtifactSummary[]; artifactId?: string | null; editable: boolean; onSaved: () => Promise<void>; onDirty: (dirty: boolean) => void }) {
  const [selected, setSelected] = useState<string | null>(artifactId ?? null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [savedId, setSavedId] = useState<string | null>(null);
  const excerptId = new URLSearchParams(window.location.search).get("excerpt");
  const revision = useRef(object.revision);
  const documentKey = useRef(crypto.randomUUID());
  const pending = useRef<{ signature: string; key: string } | null>(null);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [reading, setReading] = useState(false);
  const summary = artifacts.find(item => item.id === selected);
  useEffect(() => {
    const controller = new AbortController();
    setArtifact(null); setError("");
    if (!selected || !summary) { setReading(false); return; }
    setReading(true);
    void request<{ artifact: Artifact }>(`artifacts/${selected}`, undefined, controller.signal)
      .then(result => { if (!controller.signal.aborted) setArtifact(result.artifact); })
      .catch(cause => { if (!controller.signal.aborted) setError(String(cause)); })
      .finally(() => { if (!controller.signal.aborted) setReading(false); });
    return () => controller.abort();
  }, [selected, summary?.id, object.revision]);
  const superseded = new Set(artifacts.map(item => item.supersedes_artifact_id));
  const current = artifacts.filter(item => !superseded.has(item.id));
  const primary = current.filter(item => item.id === object.fields.current_artifact_id || item.kind === "research_notes");
  const supporting = current.filter(item => !primary.includes(item));
  useEffect(() => { onDirty(editing); }, [editing, onDirty]);
  useEffect(() => {
    const guard = (event: Event) => { if (editing && !window.confirm("Discard the unsaved document draft?")) event.preventDefault(); };
    const unload = (event: BeforeUnloadEvent) => { if (editing) event.preventDefault(); };
    window.addEventListener("beforeappnavigate", guard); window.addEventListener("beforeunload", unload);
    return () => { window.removeEventListener("beforeappnavigate", guard); window.removeEventListener("beforeunload", unload); };
  }, [editing]);
  function begin(item?: Artifact) {
    setSelected(item?.id ?? null); setDraft(item?.body ?? ""); setTitle(item?.title ?? "");
    documentKey.current = crypto.randomUUID();
    revision.current = object.revision; pending.current = null; setEditing(true); setError(""); setNotice("");
  }
  async function save(input: unknown) {
    const operations = [{ op: "save_artifact", object_id: object.id, expected_revision: revision.current, artifact: input }];
    const signature = JSON.stringify(operations);
    if (pending.current?.signature !== signature) pending.current = { signature, key: crypto.randomUUID() };
    setBusy(true); setError("");
    try {
      const result = await api.apply(operations, pending.current.key);
      setSavedId(result.changes[0]?.artifact_id ?? null);
      setEditing(false); onDirty(false); pending.current = null; await onSaved(); setNotice("Version saved. Original evidence preserved.");
    } catch (cause) { setError(`${cause instanceof Error ? cause.message : "Save failed"}. Your draft is preserved.`); }
    finally { setBusy(false); }
  }
  const row = (item: Artifact | ArtifactSummary) => <a className="artifact-item" key={item.id} href={artifactPath(object.id, item.id)} onClick={event => interceptNavigation(event, artifactPath(object.id, item.id))}><strong>{artifactTitle(item)}</strong><span>{item.media_type?.startsWith("image/") ? "Image" : item.kind === "research_notes" ? "Document" : item.kind.replaceAll("_", " ")} · {item.capture_outcome}{object.fields.current_artifact_id === item.id ? " · Current capture" : ""}{superseded.has(item.id) ? " · historical version" : ""}</span></a>;
  return <div className="artifact-workspace">
    {!artifactId && <><div className="artifact-list">{primary.map(row)}</div>
      {!!supporting.length && (primary.length || supporting.length > 3 ? <details className="detail-disclosure"><summary>{primary.length ? "Supporting attachments" : "Captured material"} ({supporting.length})</summary>{supporting.map(row)}</details> : <div className="artifact-list">{supporting.map(row)}</div>)}
      {!artifacts.length && <p className="muted">No evidence yet.</p>}</>}
    {artifactId && !summary && <p role="alert">This artifact is not available on this Object. <a href={objectPath(object.id)} onClick={event => interceptNavigation(event, objectPath(object.id))}>Return to {object.title}</a></p>}
    {reading && <p role="status">Loading evidence…</p>}
    {editing ? <form className="form artifact-editor" onSubmit={event => { event.preventDefault(); void save({ kind: "research_notes", title, body: draft, media_type: artifact ? artifact.media_type : "text/markdown", metadata: artifact?.metadata ?? { document_key: documentKey.current }, supersedes_artifact_id: artifact?.id ?? null, semantic_indexing_enabled: artifact?.semantic_indexing_enabled ?? true }); }}>
      <label>Document title<input aria-label="Document title" value={title} required maxLength={500} autoFocus onChange={event => setTitle(event.target.value)} /></label>
      <label>Document content<textarea aria-label="Document content" value={draft} required onChange={event => setDraft(event.target.value)} /></label>
      <div className="create-actions"><button className="secondary" disabled={busy}>Save version</button><button type="button" disabled={busy} onClick={() => { setEditing(false); setError(""); }}>Cancel document edit</button></div>
      {error && <p role="alert" className="form-error">{error} Copy your draft before cancelling and reloading.</p>}
    </form> : artifact && <article className="artifact-reader">
      <header><h1 className="detail-title">{artifactTitle(artifact)}</h1><button className="text-button" onClick={() => navigate(objectPath(object.id))}>Close reader</button></header>
      <p className="muted">{superseded.has(artifact.id) ? "Historical version" : "Current version"} · {artifact.capture_outcome} · {artifact.size_bytes.toLocaleString()} bytes</p>
      {artifact.capture_reason && <p role="status">Capture limitation: {artifact.capture_reason}</p>}
      {!artifact.semantic_indexing_enabled && <p className="muted">Indexing disabled. Image viewing does not imply image understanding.</p>}
      {artifact.media_type?.startsWith("image/") ? <RecordImage key={artifact.id} className="artifact-image" src={`/api/artifacts/${artifact.id}/content`} alt={artifact.title ?? "Research image"} /> : artifact.body === null ? <p className="muted">Original content not stored. Reference: {artifact.uri || "not supplied"}</p> : excerptId ? <ExcerptBody key={`${artifact.id}:${excerptId}`} artifact={artifact} noteId={excerptId} /> : <StoredText key={artifact.id} body={artifact.body} format={artifact.media_type} />}
      <div className="create-actions">{(artifact.body !== null || artifact.media_type?.startsWith("image/")) && <a download href={`/api/artifacts/${artifact.id}/content`}>Download original</a>}{artifact.body !== null && <button onClick={() => { void navigator.clipboard.writeText(artifact.body!).then(() => setNotice("Copied exact document text.")).catch(() => setError("Clipboard unavailable; use Download original.")); }}>Copy text</button>}{editable && artifact.body !== null && !superseded.has(artifact.id) && artifact.kind === "research_notes" && <button onClick={() => begin(artifact)}>Edit document</button>}</div>
      <details className="detail-disclosure"><summary>Evidence metadata</summary><dl><dt>SHA-256</dt><dd>{artifact.sha256}</dd><dt>Artifact ID</dt><dd>{artifact.id}</dd><dt>Capture date</dt><dd>{artifact.captured_at ?? "Not supplied"}</dd><dt>Document key</dt><dd>{String(artifact.metadata.document_key ?? "Not supplied")}</dd></dl><pre className="source-text-preview">{JSON.stringify(artifact.metadata, null, 2)}</pre></details>
    </article>}
    {artifacts.some(item => superseded.has(item.id)) && <details className="detail-disclosure"><summary>Document history ({artifacts.filter(item => superseded.has(item.id)).length})</summary>{artifacts.filter(item => superseded.has(item.id)).map(row)}</details>}
    {!editing && error && <p role="alert" className="form-error">{error}</p>}{notice && <p role="status">{notice} {savedId && <a href={artifactPath(object.id, savedId)} onClick={event => interceptNavigation(event, artifactPath(object.id, savedId))}>Read saved version</a>}</p>}
  </div>;
}

function ExcerptBody({ artifact, noteId }: { artifact: Artifact; noteId: string }) {
  const [note, setNote] = useState<RecordObject | null>(null);
  const [error, setError] = useState("");
  const mark = useRef<HTMLElement>(null);
  useEffect(() => {
    let active = true;
    void api.detail(noteId).then(detail => { if (active) setNote(detail.object); }).catch(cause => { if (active) setError(String(cause)); });
    return () => { active = false; };
  }, [noteId]);
  useEffect(() => { mark.current?.scrollIntoView({ block: "center" }); }, [note]);
  const locator = note?.fields.source_locator;
  const characters = Array.from(artifact.body ?? "");
  const offsets = locator && typeof locator === "object" && !Array.isArray(locator) && locator.kind === "text_offset" && typeof locator.start === "number" && typeof locator.end === "number" ? { start: locator.start, end: locator.end } : null;
  const valid = note?.kind === "note" && note.fields.source_artifact_id === artifact.id && offsets && Number.isInteger(offsets.start) && Number.isInteger(offsets.end) && offsets.start >= 0 && offsets.end > offsets.start && offsets.end <= characters.length && characters.slice(offsets.start, offsets.end).join("") === note.fields.content;
  return <><p className="muted">{valid ? "Exact excerpt highlighted in original text; Markdown syntax is preserved." : error ? `Excerpt unavailable: ${error}` : note ? "No supported matching locator; showing the original without a highlight." : "Loading excerpt locator…"} {note && <a href={objectPath(note.id)} onClick={event => interceptNavigation(event, objectPath(note.id))}>Return to {note.title}</a>}</p>
    {valid && offsets ? <pre className="source-text-preview stored-text">{characters.slice(0, offsets.start).join("")}<mark ref={mark} className="excerpt-highlight">{characters.slice(offsets.start, offsets.end).join("")}</mark>{characters.slice(offsets.end).join("")}</pre> : <StoredText body={artifact.body ?? ""} format={artifact.media_type} />}
  </>;
}
