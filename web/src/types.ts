export type ObjectKind = "task" | "thread" | "entity" | "source" | "note" | "theme" | "event";
export type TaskStatus = "backlog" | "todo" | "doing" | "review" | "done" | "blocked";
export type SourceKind = "article" | "paper" | "podcast_episode" | "video" | "book" | "report" | "document" | "dataset" | "web_page" | "social_post" | "other";
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type Fields = Record<string, JsonValue>;
export interface RecordObject {
  id: string;
  kind: ObjectKind;
  title: string;
  description: string;
  fields: Fields;
  revision: number;
  metadata: { created_by: string | null; updated_by: string | null; created_at: string | null; updated_at: string | null };
  body: string;
  connection_count: number;
  provenance: Fields;
}
export interface Connection {
  id: string;
  from_id: string;
  to_id: string;
  kind: string;
  explanation: string;
  revision: number;
  metadata: RecordObject["metadata"];
  provenance: Fields;
  from_object: Endpoint;
  to_object: Endpoint;
}
export interface Participant { object_id: string; direction: "outgoing" | "incoming"; role: string; user: User; connection: Omit<Connection, "from_object" | "to_object"> }
export interface Detail {
  object: RecordObject;
  artifacts: ArtifactSummary[];
  connections: RelatedConnection[];
  audit_events: { id: number; object_id: string; actor_id: string; credential_id: string; action: string; revision: number; occurred_at: string }[];
  history: { id: string; target_type: string; action: string; revision: number; actor_id: string | null; occurred_at: string; state_omitted?: boolean; before_state?: Fields | null; after_state?: Fields | null; import_provenance?: Fields | null }[];
  corrections: { id: string; target_type: string; target_id: string; reason: string; representation_omitted?: boolean; representation?: Fields; actor_id: string | null; created_at: string; supersedes_correction_id: string | null; import_provenance?: Fields | null }[];
}
export interface Artifact {
  id: string; object_id: string; body: string | null; origin: string; created_by: string | null; created_at: string;
  kind: string; title: string | null; media_type: string | null; uri: string | null; language: string | null;
  sha256: string; size_bytes: number; capture_outcome: string; capture_reason: string | null;
  expected_size_bytes: number | null; semantic_indexing_enabled: boolean; metadata: Record<string, unknown>;
  supersedes_artifact_id: string | null; captured_at: string | null;
}
export interface Identity { id: string; role: "admin" | "member" | "reader"; mode: "session" | "agent"; write_kinds: string[]; overlay_inventory?: boolean }
export interface Credential { id: string; account_id: string; label: string; write_kinds: string[]; revoked: boolean }

// Retained Context presentation contracts; no fabricated provenance or actor type.
export interface UserAttribution { user_object_id: string; title: string; user_kind: "human" | "agent" | "system" | "unknown"; role: string; avatar_asset_url: string | null }
export interface ObjectVisual { object_id: string; source_provider: string | null; users: UserAttribution[] }
export interface Task {
  object_id: string;
  title: string;
  status: TaskStatus;
  owner_object_id: string | null;
  due_at: string | null;
  github_issue_url: string | null;
  body: string;
  project: string | null;
  work_kind: "general" | "code";
}
export interface ConnectionGraphNode { id: string; kind: ObjectKind | "run" | "trace" | "user" | "artifact"; title: string; href?: string }
export interface ConnectionGraphEdge { id: string; source_object_id: string; target_object_id: string; kind: string; description: string; reference?: boolean }
export interface ConnectionGraphSnapshot {
  node_count: number; connection_count: number; nodes: ConnectionGraphNode[]; edges: ConnectionGraphEdge[];
  continuation: { objects: number | null; connections: number | null };
  total_connections: number;
}

export type ArtifactSummary = Pick<Artifact, "id" | "object_id" | "title" | "kind" | "created_at" | "media_type" | "sha256" | "size_bytes" | "capture_outcome" | "capture_reason" | "supersedes_artifact_id" | "metadata"> & { body_omitted: boolean };
export type RelatedRecord = Pick<RecordObject, "id" | "kind" | "title" | "metadata"> & { owner_object_id?: JsonValue; fields?: Fields };
export type RelatedConnection = Omit<Connection, "from_object" | "to_object"> & { from_object: Endpoint; to_object: Endpoint };

export interface User { connection_count?: number; id: string; title: string; user_kind: "human" | "agent" | "system" | "unknown"; username: string | null; role: string; active: boolean; revision: number; profile: Fields; metadata: RecordObject["metadata"]; provenance: Fields; avatar_asset_url: string | null }
export interface Endpoint { id: string; title: string; kind: ObjectKind | "user" | "artifact" | "trace"; endpoint_type?: "object" | "user" | "artifact" | "trace"; object_id?: string; revision?: number; metadata?: RecordObject["metadata"]; fields?: Fields; }
