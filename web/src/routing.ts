// Navigation behavior adapted from Centaur Context 91b31f4 (MIT).
export const sections = {
  objects: "Objects", connections: "Connections", tasks: "Tasks", users: "Users",
  entities: "Entities", notes: "Notes", publishing: "Publishing", access: "Access",
  sources: "Sources", themes: "Themes", events: "Events",
  threads: "Threads", traces: "Traces", schema: "Schema", inventory: "Inventory",
} as const;
export const publishingCalendarUrl = import.meta.env.VITE_PUBLISHING_CALENDAR_URL?.trim() ?? "";
export type Section = keyof typeof sections;
export const kindSections: Record<string, Section> = { task: "tasks", entity: "entities", note: "notes", source: "sources", theme: "themes", event: "events", thread: "threads" };
export function parseRoute(overlayInventory = false) {
  const [rawSegment = "objects", id, child, artifact] = window.location.pathname.split("/").filter(Boolean);
  const segment = ({ memories: "notes", chats: "threads", runs: "traces" } as Record<string,string>)[rawSegment] ?? rawSegment;
  if (segment === "inventory" && !overlayInventory) {
    return { section: "objects" as const, id: null, artifactId: null, view: null };
  }
  return { section: (segment in sections && (segment !== "publishing" || publishingCalendarUrl) ? segment : "objects") as Section, id: id ?? null,
    artifactId: child === "artifacts" ? artifact ?? null : null,
    view: new URLSearchParams(window.location.search).get("view") };
}
export function objectPath(id: string) { return `/objects/${encodeURIComponent(id)}`; }
export function artifactPath(objectId: string, artifactId: string) { return `${objectPath(objectId)}/artifacts/${encodeURIComponent(artifactId)}`; }
export function connectionPath(id: string) { return `/connections/${encodeURIComponent(id)}`; }
export function connectionsPath(id?: string) { return `/connections${id ? `?${new URLSearchParams({ object: id })}` : ""}`; }
let historyIndex = window.history.state?.commonsIndex ?? 0;
let restoring = false;
window.history.replaceState({ ...window.history.state, commonsIndex: historyIndex }, "");
window.addEventListener("popstate", event => {
  if (!event.isTrusted) return;
  if (restoring) { restoring = false; event.stopImmediatePropagation(); return; }
  const nextIndex = event.state?.commonsIndex;
  if (typeof nextIndex !== "number") return;
  const path = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (nextIndex !== historyIndex && !window.dispatchEvent(new CustomEvent("beforeappnavigate", { cancelable: true, detail: path }))) {
    restoring = true;
    window.history.go(historyIndex - nextIndex);
    event.stopImmediatePropagation();
    return;
  }
  historyIndex = nextIndex;
});
export function navigate(path: string, replace = false) {
  if (`${window.location.pathname}${window.location.search}${window.location.hash}` === path) return;
  if (!window.dispatchEvent(new CustomEvent("beforeappnavigate", { cancelable: true, detail: path }))) return;
  if (!replace) historyIndex += 1;
  window.history[replace ? "replaceState" : "pushState"]({ commonsIndex: historyIndex }, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
export function interceptNavigation(event: React.MouseEvent<HTMLAnchorElement | SVGAElement>, path: string) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault(); navigate(path);
}

export function endpointPath(endpoint: { id: string; kind: string; object_id?: string }) { return endpoint.kind === "user" ? `/users/${endpoint.id}` : endpoint.kind === "trace" || endpoint.kind === "run" ? `/traces/${endpoint.id}` : endpoint.kind === "thread" ? `/threads/${endpoint.id}` : endpoint.kind === "artifact" && endpoint.object_id ? artifactPath(endpoint.object_id, endpoint.id) : objectPath(endpoint.id); }
