import { endpointPath } from "./routing";
import { PendingWrites } from "./pendingWrites";
import type { Connection, ConnectionGraphSnapshot, Credential, Detail, Fields, Identity, Participant, RecordObject, User } from "./types";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); }
}

export async function request<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("commons-session-expired"));
    throw new ApiError(payload?.error || `Request failed (${response.status})`, response.status);
  }
  return payload as T;
}

type ApplyResult = { local_refs: Record<string, string>; changes: { id: string; revision: number; artifact_id?: string }[] };
const updates = new PendingWrites<ApplyResult>();

export type ObjectPage = { objects: RecordObject[]; total: number; next_offset: number | null };
export type Sort = "recent" | "connected";
export const api = {
  me: () => request<Identity>("me"),
  users: async () => (await request<{ users: User[] }>("users")).users,
  async uploadAvatar(user: User, image: File, source: string) {
    if (!image.size || image.size > 262144) throw new Error("Choose an image up to 256 KiB.");
    const params = new URLSearchParams({ expected_revision: String(user.revision), source });
    const response = await fetch(`/api/users/${user.id}/avatar?${params}`, { method: "POST", headers: { "Content-Type": image.type }, body: image });
    if (!response.ok) throw new ApiError((await response.json()).error || "Avatar upload failed", response.status);
  },
  tokens: () => request<Credential[]>("tokens"),
  async detail(id: string, signal?: AbortSignal): Promise<Detail> {
    // Enumerate metadata to preserve version chains and correction lineage. Bodies
    // and historical snapshots are fetched only when their reader is opened.
    const path = `objects/${encodeURIComponent(id)}?view=compact&limit=200`;
    type Page = Detail & { page: { next_offset: number | null } };
    const first = await request<Page>(path, undefined, signal);
    let offset = first.page.next_offset;
    while (offset !== null) {
      signal?.throwIfAborted();
      const next = await request<Page>(`${path}&offset=${offset}&expected_revision=${first.object.revision}`, undefined, signal);
      for (const key of ["artifacts", "connections", "audit_events", "history", "corrections"] as const) {
        // Each array has a distinct element type; append through its own key.
        Object.assign(first, { [key]: [...first[key], ...next[key]] });
      }
      offset = next.page.next_offset;
    }
    return first;
  },
  objectPage(q = "", kind = "", sort: Sort = "recent", archived = false, offset = 0, signal?: AbortSignal): Promise<ObjectPage> {
    const params = new URLSearchParams({ q, sort, archived: String(archived), limit: "50", offset: String(offset) });
    if (kind) params.set("kind", kind);
    return request(`objects?${params}`, undefined, signal);
  },
  // Explicit full enumeration for consumers whose grouping needs the complete set.
  async objects(q = "", kind = "", sort: Sort = "recent", archived = false, signal?: AbortSignal) {
    const objects: RecordObject[] = [];
    let offset: number | null = 0;
    do {
      signal?.throwIfAborted();
      const page = await api.objectPage(q, kind, sort, archived, offset, signal);
      objects.push(...page.objects);
      offset = page.next_offset;
    } while (offset !== null);
    return objects;
  },
  async participants(objectIds: string[], signal?: AbortSignal) {
    const participants: Participant[] = [];
    for (let start = 0; start < objectIds.length; start += 100) {
      let offset: number | null = 0;
      do {
        const params = new URLSearchParams({ object_ids: objectIds.slice(start, start + 100).join(","), limit: "200", offset: String(offset) });
        const page: { participants: Participant[]; next_offset: number | null } = await request(`participants?${params}`, undefined, signal);
        participants.push(...page.participants);
        offset = page.next_offset;
      } while (offset !== null);
    }
    return participants;
  },
  async connections(objectId?: string, signal?: AbortSignal) {
    const connections: Connection[] = [];
    let offset: number | null = 0;
    do {
      const params = new URLSearchParams({ limit: "200", offset: String(offset) });
      if (objectId) params.set("object_id", objectId);
      const page: { connections: Connection[]; next_offset: number | null } = await request(`connections?${params}`, undefined, signal);
      connections.push(...page.connections);
      offset = page.next_offset;
    } while (offset !== null);
    return connections;
  },
  async connectionGraph(objectId?: string, signal?: AbortSignal, previous?: ConnectionGraphSnapshot): Promise<ConnectionGraphSnapshot> {
    const objectOffset = previous ? previous.continuation.objects : 0;
    const connectionOffset = previous ? previous.continuation.connections : 0;
    const params = new URLSearchParams({ limit: "200", offset: String(connectionOffset ?? 0) });
    if (objectId) params.set("object_id", objectId);
    const [objectPage, connectionPage] = await Promise.all([
      objectOffset === null ? null : objectId
        ? request<Detail>(`objects/${objectId}?view=compact&limit=1`, undefined, signal).then(detail => ({ objects: [detail.object], next_offset: null }))
        : api.objectPage("", "", "recent", false, objectOffset, signal),
      connectionOffset === null ? null : request<{ connections: Connection[]; total: number; next_offset: number | null }>(`connections?${params}`, undefined, signal),
    ]);
    const nodes = new Map((previous?.nodes ?? []).map(node => [node.id, node]));
    const edges = new Map((previous?.edges ?? []).map(edge => [edge.id, edge]));
    for (const { id, kind, title } of objectPage?.objects ?? []) nodes.set(id, { id, kind, title });
    for (const edge of connectionPage?.connections ?? []) {
      for (const endpoint of [edge.from_object, edge.to_object]) nodes.set(endpoint.id, { id: endpoint.id, kind: endpoint.kind, title: endpoint.title, href: endpointPath(endpoint) });
      edges.set(edge.id, { id: edge.id, source_object_id: edge.from_id, target_object_id: edge.to_id, kind: edge.kind, description: edge.explanation });
    }
    return { node_count: nodes.size, connection_count: edges.size, nodes: [...nodes.values()], edges: [...edges.values()],
      continuation: { objects: objectPage?.next_offset ?? null, connections: connectionPage?.next_offset ?? null },
      total_connections: connectionPage?.total ?? previous?.total_connections ?? 0 };
  },
  apply: (operations: unknown[], idempotencyKey: string = crypto.randomUUID()) => request<ApplyResult>("apply", { contract_version: "commons/0.1", idempotency_key: idempotencyKey, operations }),
  async update(object: RecordObject, changes: { title?: string; description?: string; body?: string; fields?: Fields }) {
    const operations = [{ op: "update_object", object_id: object.id, expected_revision: object.revision,
      ...changes }];
    let detail: Detail | undefined;
    await updates.resolve(object, operations, key => api.apply(operations, key), async accepted => {
      detail = await api.detail(object.id);
      // Do not silently rebase another open draft onto a concurrent writer's revision.
      if (detail.object.revision !== accepted.changes[0].revision) throw new ApiError("Server data changed after saving. Reload before editing again.", 409);
    });
    return detail!;
  },
};
