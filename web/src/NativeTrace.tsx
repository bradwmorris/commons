import { useMemo, useState, type ReactNode } from "react";
import "./native-trace.css";

type Attribute = { key: string; value?: Record<string, unknown> };
type Span = { traceId: string; spanId: string; parentSpanId?: string; name: string; startTimeUnixNano: string | number; endTimeUnixNano: string | number; status?: { code?: number; message?: string }; attributes?: Attribute[]; events?: { name: string; timeUnixNano?: string; attributes?: Attribute[] }[]; links?: unknown[] };
export type NativeSpan = { resource: unknown; scope: unknown; resourceSchemaUrl?: string; scopeSchemaUrl?: string; span: Span };
const nano = (n: string | number) => { try { return BigInt(n); } catch { return 0n; } };
const ms = (n: bigint) => Number(n) / 1e6;
const duration = (s: Span) => ms(nano(s.endTimeUnixNano) - nano(s.startTimeUnixNano));
const outcome = (s: Span) => s.status?.code === 2 ? "Error" : s.status?.code === 1 ? "OK" : "Unreported";
const key = (id: string | undefined) => id?.toLowerCase() || "";
const valueText = (value?: Record<string, unknown>) => {
  const v = Object.values(value ?? {})[0];
  return typeof v === "object" ? JSON.stringify(v) : String(v ?? "");
};
const attribute = (s: Span, name: string) => s.attributes?.find(a => a?.key === name)?.value?.stringValue as string | undefined;
type Usage = { input?: number; output?: number; cached?: number; reasoning?: number };
const numberAttribute = (s: Span, names: string[]) => {
  for (const name of names) {
    const value = s.attributes?.find(a => a.key === name)?.value;
    const raw = value?.intValue ?? value?.doubleValue;
    if ((typeof raw === "string" || typeof raw === "number") && raw !== "") {
      const n = Number(raw);
      if (Number.isSafeInteger(n) && n >= 0) return n;
    }
  }
};
function usage(s: Span): Usage {
  return {
    input: numberAttribute(s, ["codex.turn.token_usage.input_tokens", "gen_ai.usage.input_tokens", "llm.token_count.prompt"]),
    output: numberAttribute(s, ["codex.turn.token_usage.output_tokens", "gen_ai.usage.output_tokens", "llm.token_count.completion"]),
    cached: numberAttribute(s, ["codex.turn.token_usage.cached_input_tokens", "gen_ai.usage.cache_read.input_tokens", "llm.token_count.prompt_details.cache_read"]),
    reasoning: numberAttribute(s, ["codex.turn.token_usage.reasoning_output_tokens", "codex.usage.reasoning_output_tokens"]),
  };
}
const hasUsage = (s: Span) => Object.values(usage(s)).some(v => v !== undefined);
const toolName = (s: Span) => attribute(s, "tool_name") || attribute(s, "tool.name");
function kind(s: Span) {
  if (s.name === "run_turn" || s.name === "session_task.turn") return "Turn";
  if (attribute(s, "codex.tool.phase") === "dispatch" || attribute(s, "openinference.span.kind") === "TOOL" || (toolName(s) && s.name === toolName(s))) return "Tool";
  if (hasUsage(s) || attribute(s, "openinference.span.kind") === "LLM" || /responses\.(stream_)?request|sampling_request|model_client/.test(s.name)) return "Model";
  return "Span";
}
function label(s: Span) {
  if (kind(s) === "Turn") return "Turn";
  if (kind(s) === "Tool") return toolName(s) || s.name;
  if (kind(s) === "Model") {
    if (s.name === "handle_responses" && hasUsage(s)) return "Model response";
    if (!hasUsage(s) && attribute(s, "openinference.span.kind") !== "LLM") return s.name;
    return attribute(s, "model") || attribute(s, "gen_ai.request.model") || "Model request";
  }
  return s.name;
}
const formatCount = (value: number | undefined) => value === undefined ? "—" : value.toLocaleString("en-US");
function TokenUsage({ values, compact = false }: { values: Usage; compact?: boolean }) {
  const fields: [keyof Usage, string][] = [["input", "Input tokens"], ["output", "Output tokens"], ["cached", "Cached input"], ["reasoning", "Reasoning output"]];
  return <dl className={compact ? "trace-token-summary" : "span-token-usage"}>{fields.filter(([key]) => compact ? key !== "reasoning" : values[key] !== undefined).map(([key, name]) => <div key={key} title={key === "cached" ? "Included in input tokens" : key === "reasoning" ? "Included in output tokens" : undefined}><dt>{name}</dt><dd>{formatCount(values[key])}</dd></div>)}</dl>;
}
function Attributes({ values }: { values: Attribute[] }) {
  if (!values.length) return <p className="muted">No attributes recorded.</p>;
  return <table className="span-attribute-table"><tbody>{values.filter(a => a && typeof a.key === "string").map((a, i) => <tr key={`${a.key}:${i}`}><th scope="row">{a.key}</th><td>{valueText(a.value)}</td></tr>)}</tbody></table>;
}

export function NativeTrace({ id, entries, coverage, context, source }: { id: string; entries: unknown[]; coverage: unknown; context?: ReactNode; source?: unknown }) {
  const [showInternal, setShowInternal] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState("overview");
  const graph = useMemo(() => {
    const spans = (entries as NativeSpan[]).filter(e => e.span?.spanId);
    const byId = new Map(spans.map(e => [key(e.span.spanId), e]));
    const children = new Map<string, NativeSpan[]>();
    for (const e of spans) {
      const parent = key(e.span.parentSpanId);
      const siblings = children.get(parent) ?? [];
      siblings.push(e); children.set(parent, siblings);
    }
    const sort = (a: NativeSpan, b: NativeSpan) => nano(a.span.startTimeUnixNano) < nano(b.span.startTimeUnixNano) ? -1 : nano(a.span.startTimeUnixNano) > nano(b.span.startTimeUnixNano) ? 1 : a.span.spanId.localeCompare(b.span.spanId);
    for (const siblings of children.values()) siblings.sort(sort);
    const ordered: { entry: NativeSpan; depth: number; missing: boolean }[] = [];
    const visited = new Set<string>();
    function visit(entry: NativeSpan) {
      const stack = [{ entry, depth: 0 }];
      while (stack.length) {
        const item = stack.pop()!; const sid = key(item.entry.span.spanId);
        if (visited.has(sid)) continue;
        visited.add(sid);
        ordered.push({ ...item, missing: !!item.entry.span.parentSpanId && !byId.has(key(item.entry.span.parentSpanId)) });
        for (const child of [...(children.get(sid) ?? [])].reverse()) stack.push({ entry: child, depth: item.depth + 1 });
      }
    }
    for (const e of spans.filter(e => !e.span.parentSpanId || !byId.has(key(e.span.parentSpanId))).sort(sort)) visit(e);
    for (const e of [...spans].sort(sort)) if (!visited.has(key(e.span.spanId))) visit(e);
    const start = spans.reduce((n, e) => nano(e.span.startTimeUnixNano) < n ? nano(e.span.startTimeUnixNano) : n, nano(spans[0]?.span.startTimeUnixNano ?? 0));
    const end = spans.reduce((n, e) => nano(e.span.endTimeUnixNano) > n ? nano(e.span.endTimeUnixNano) : n, start);
    return { spans, byId, children, ordered, start, end };
  }, [entries]);
  const roots = graph.ordered.filter(e => e.depth === 0).map(e => e.entry);
  const root = roots[0];
  const isAncestor = (ancestor: string, child: Span) => {
    let parent = key(child.parentSpanId); const seen = new Set<string>();
    while (parent && !seen.has(parent)) {
      if (parent === ancestor) return true;
      seen.add(parent); parent = key(graph.byId.get(parent)?.span.parentSpanId);
    }
    return false;
  };
  // Usage-bearing calls are more precise than nested transport wrappers.
  const usageModels = graph.spans.filter(e => kind(e.span) === "Model" && hasUsage(e.span));
  const leafUsage = usageModels.filter(e => !usageModels.some(other => other !== e && isAncestor(key(e.span.spanId), other.span)));
  const agentIds = new Set(graph.spans.filter(e => roots.includes(e) || kind(e.span) === "Tool" || e.span.status?.code === 2 || (kind(e.span) === "Model" && (leafUsage.includes(e) || attribute(e.span, "openinference.span.kind") === "LLM" || (!usageModels.length && !hasUsage(e.span))))).map(e => key(e.span.spanId)));
  const displayedIds = showInternal ? new Set(graph.byId.keys()) : agentIds;
  const displayedChildren = new Map<string, number>();
  const projected = graph.ordered.filter(e => displayedIds.has(key(e.entry.span.spanId))).map(e => {
    let parent = key(e.entry.span.parentSpanId); const seen = new Set<string>(); let depth = 0; let nearest = "";
    while (parent && !seen.has(parent)) {
      seen.add(parent);
      if (displayedIds.has(parent)) { depth++; if (!nearest) nearest = parent; }
      parent = key(graph.byId.get(parent)?.span.parentSpanId);
    }
    if (nearest) displayedChildren.set(nearest, (displayedChildren.get(nearest) ?? 0) + 1);
    return { ...e, depth };
  });
  const item = selected && displayedIds.has(selected) ? graph.byId.get(selected) : root;
  if (!item) return <p>No native spans saved.</p>;
  const needle = query.trim().toLowerCase();
  const included = new Set<string>();
  if (needle) for (const e of graph.spans.filter(e => displayedIds.has(key(e.span.spanId)))) {
    if (![e.span.name, label(e.span), toolName(e.span), attribute(e.span, "model"), attribute(e.span, "call_id")].filter(Boolean).join(" ").toLowerCase().includes(needle)) continue;
    let sid = key(e.span.spanId); const seen = new Set<string>();
    while (sid && !seen.has(sid)) { seen.add(sid); if (displayedIds.has(sid)) included.add(sid); sid = key(graph.byId.get(sid)?.span.parentSpanId); }
  }
  let hiddenBelow: number | null = null;
  const visible = projected.filter(({ entry, depth }) => {
    if (needle) return included.has(key(entry.span.spanId));
    if (hiddenBelow !== null && depth > hiddenBelow) return false;
    hiddenBelow = collapsed.has(key(entry.span.spanId)) ? depth : null;
    return true;
  });
  // Use reported turn totals, never turn + child totals. Fallback uses disjoint
  // leaf model calls; any missing field stays unknown rather than becoming zero.
  const rootUsage = roots.length === 1 ? usage(root.span) : {};
  const summaryUsage: Usage = Object.values(rootUsage).some(v => v !== undefined) ? rootUsage : Object.fromEntries((["input", "output", "cached", "reasoning"] as const).map(field => {
    const values = leafUsage.map(e => usage(e.span)[field]);
    const total = values.length && values.every(v => v !== undefined) ? values.reduce<number>((sum, v) => sum + v!, 0) : undefined;
    return [field, total !== undefined && Number.isSafeInteger(total) ? total : undefined];
  }));
  const model = root && (attribute(root.span, "model") || attribute(root.span, "gen_ai.request.model"));
  const selectedUsage = usage(item.span);
  const selectedBody = [["Input", attribute(item.span, "input.value")], ["Output", attribute(item.span, "output.value")]].filter(([, value]) => value);
  const tabs = ["overview", ...(item.span.attributes?.length ? ["attributes"] : []), ...(item.span.events?.length ? ["events"] : []), "raw"];
  const activeTab = tabs.includes(tab) ? tab : "overview";
  const elapsed = ms(graph.end - graph.start);
  const coverageStatus = coverage && typeof coverage === "object" && "status" in coverage ? String(coverage.status) : "Unknown coverage";
  return <section className="native-trace" aria-label="OpenTelemetry trace">
    <div className="native-trace-heading"><strong>{graph.spans.length} spans · {elapsed.toFixed(2)} ms</strong><span className="trace-coverage" title="See trace details for capture gaps.">{coverageStatus}</span>{context && <span className="trace-page-meta">{context}</span>}<a href={`/api/traces/${id}/otlp`} download aria-label="Export trace as OTLP JSON" title="Download trace as OTLP JSON">Export ↓</a></div>
    <div className="trace-agent-summary">{model && <div className="trace-model"><span>Model</span><strong>{model}</strong></div>}<TokenUsage values={summaryUsage} compact /></div>
    <div className="native-trace-controls"><label className="search"><span aria-hidden="true">⌕</span><input aria-label="Find span" placeholder="Find a span, model or tool…" value={query} onChange={e => setQuery(e.target.value)} /></label><label className="trace-internal-toggle"><input type="checkbox" checked={showInternal} onChange={e => { setShowInternal(e.target.checked); setCollapsed(new Set()); }} />Show internal spans</label><button onClick={() => setCollapsed(new Set())}>Expand all</button><button disabled={!!needle} onClick={() => setCollapsed(new Set(graph.spans.filter(e => displayedChildren.has(key(e.span.spanId))).map(e => key(e.span.spanId))))}>Collapse all</button><span>{visible.length} of {graph.spans.length} spans</span></div>
    <div className="native-trace-layout">
      <div className="native-span-browser"><div className="native-span-columns"><span>Span</span><span className="native-time-axis"><span>0 ms</span><span>{(elapsed / 2).toFixed(0)} ms</span><span>{elapsed.toFixed(0)} ms</span></span><span>Duration</span></div>
        <div className="native-span-list" role="group" aria-label="Span tree and timing waterfall">
          {!visible.length && <p className="empty-list">No matching spans.</p>}
          {visible.map(({ entry: { span }, depth, missing }) => {
            const sid = key(span.spanId), hasChildren = displayedChildren.has(sid), expanded = !!needle || !collapsed.has(sid), active = key(item.span.spanId) === sid;
            return <div key={sid} className={`native-span-row${active ? " selected" : ""}${span.status?.code === 2 ? " failed" : ""}`}>
              <div className="native-span-name" style={{ paddingLeft: `${Math.min(depth, 10) * 12}px` }}>
                {hasChildren ? <button className="span-chevron" disabled={!!needle} aria-label={`${expanded ? "Collapse" : "Expand"} ${span.name}`} aria-expanded={expanded} onClick={() => setCollapsed(current => { const next = new Set(current); if (next.has(sid)) next.delete(sid); else next.add(sid); return next; })}>{expanded ? "▾" : "▸"}</button> : <span className="span-chevron" />}
                <button className="native-span-select" title={span.name} aria-label={`Select span ${span.name}`} aria-pressed={active} onClick={() => setSelected(sid)}>{kind(span) !== "Span" && <span className={`span-kind kind-${kind(span).toLowerCase()}`}>{kind(span)}</span>}<span className="span-label"><span>{label(span)}</span>{hasUsage(span) && <small className="span-row-usage">{formatCount(usage(span).input)} in · {formatCount(usage(span).output)} out</small>}</span>{missing && <small title="Native parent was not captured">↖</small>}{span.status?.code === 2 && <small className="span-error-mark">!</small>}</button>
              </div>
              <button className="native-span-track" aria-label={`Timing for ${span.name}`} onClick={() => setSelected(sid)}><span className={span.status?.code === 2 ? "native-span-bar error" : "native-span-bar"} style={{ left: `${elapsed ? ms(nano(span.startTimeUnixNano) - graph.start) / elapsed * 100 : 0}%`, width: `${elapsed ? Math.max(.4, duration(span) / elapsed * 100) : 100}%` }} /></button>
              <span className="native-span-duration">{duration(span).toFixed(2)} ms</span>
            </div>;
          })}
        </div>
      </div>
      <section className="native-span-detail" aria-label="Selected span"><header>{kind(item.span) !== "Span" && <span className={`span-kind kind-${kind(item.span).toLowerCase()}`}>{kind(item.span)}</span>}<h2>{label(item.span)}</h2><p title={item.span.status?.code ? undefined : "The source did not report a span status."} className={item.span.status?.code === 2 ? "span-error-mark" : "muted"}>{duration(item.span).toFixed(3)} ms · {outcome(item.span)}</p></header>
        <div className="span-detail-tabs" role="tablist" aria-label="Span details">{tabs.map(name => <button key={name} role="tab" id={`span-tab-${name}`} aria-selected={activeTab === name} aria-controls="span-detail-content" tabIndex={activeTab === name ? 0 : -1} onKeyDown={event => {
          const names = tabs;
          const next = event.key === "ArrowRight" ? names[(names.indexOf(name) + 1) % names.length] : event.key === "ArrowLeft" ? names[(names.indexOf(name) + names.length - 1) % names.length] : event.key === "Home" ? names[0] : event.key === "End" ? names.at(-1) : undefined;
          if (next) { event.preventDefault(); setTab(next); document.getElementById(`span-tab-${next}`)?.focus(); }
        }} onClick={() => setTab(name)}>{name[0].toUpperCase() + name.slice(1)}{name === "events" && !!item.span.events?.length && ` (${item.span.events.length})`}</button>)}</div>
        <div id="span-detail-content" role="tabpanel" aria-labelledby={`span-tab-${activeTab}`} className="span-detail-content">
          {activeTab === "overview" && <>{hasUsage(item.span) && <TokenUsage values={selectedUsage} />}{item.span.status?.message && <p className="span-error-mark">{item.span.status.message}</p>}<dl className="span-overview">{item.span.name === "handle_responses" && hasUsage(item.span) && <div><dt>Duration measures</dt><dd>Response processing</dd></div>}{label(item.span) !== item.span.name && <div><dt>Native span</dt><dd>{item.span.name}</dd></div>}<dt>Offset</dt><dd>{ms(nano(item.span.startTimeUnixNano) - graph.start).toFixed(3)} ms</dd>{["model", "tool_name", "call_id"].map(name => attribute(item.span, name) ? <div key={name}><dt>{name.replaceAll("_", " ")}</dt><dd>{attribute(item.span, name)}</dd></div> : null)}</dl>{selectedBody.map(([name, value]) => <div className="span-recorded-body" key={name}><strong>{name}</strong><pre>{value}</pre></div>)}</>}
          {activeTab === "attributes" && <Attributes values={item.span.attributes ?? []} />}
          {activeTab === "events" && ((item.span.events?.length ?? 0) ? item.span.events!.map((e, index) => <article className="span-event" key={index}><strong>{e.name}</strong>{e.timeUnixNano && <small>+{ms(nano(e.timeUnixNano) - graph.start).toFixed(3)} ms</small>}<Attributes values={e.attributes ?? []} /></article>) : <p className="muted">No events recorded.</p>)}
          {activeTab === "raw" && <pre>{JSON.stringify(item, null, 2)}</pre>}
        </div>
      </section>
    </div>
    <details className="trace-source-details"><summary>Trace details</summary><pre>{JSON.stringify({ source, coverage }, null, 2)}</pre></details>
  </section>;
}
