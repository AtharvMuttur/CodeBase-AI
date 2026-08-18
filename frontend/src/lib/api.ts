// Vite injects this at build time (see vite.config.ts).
// Fall back to "/api" so the dev-server proxy path works without env.
const RAW_BASE = import.meta.env.VITE_API_BASE as string | undefined;

// When VITE_API_BASE points at an absolute URL (http://… or //…) use it
// directly — the operator wants the built frontend to hit a real
// backend, not a proxy. When it's unset we use a relative "/api" so
// vite's dev-server proxy can forward to the local backend without
// CORS gymnastics.
const API_BASE: string = RAW_BASE && /^(https?:)?\/\//.test(RAW_BASE)
  ? `${RAW_BASE.replace(/\/$/, "")}/api`
  : "/api";

export interface Health {
  status: "ok" | "degraded" | "error";
  version: string;
  database: boolean;
  timestamp: string;
  details: Record<string, unknown>;
}

export interface RepositorySummary {
  id: number;
  name: string;
  source: string;
  source_uri: string | null;
  owner: string | null;
  branch: string | null;
  commit_sha: string | null;
  file_count: number;
  chunk_count: number;
  status: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface RepositoryDetail extends RepositorySummary {
  files_processed: number;
  total_files: number;
}

export interface CreateRepositoryResponse {
  repository_id: number;
  name: string;
  owner: string;
  url: string;
  status: string;
  branch: string | null;
  commit_sha: string | null;
  message: string | null;
}

export interface RepositoryFile {
  id: number;
  path: string;
  language: string | null;
  size_bytes: number;
  chunk_count: number;
}

export interface IngestResult {
  repository_id: number;
  name: string;
  status: string;
  file_count: number;
  chunk_count: number;
  skipped_files: number;
  elapsed_seconds: number;
  message: string;
}

export interface ChunkCitation {
  chunk_id: number;
  file_id: number;
  file_path: string;
  language: string | null;
  start_line: number;
  end_line: number;
  content: string;
  score: number;
}

export interface QueryResult {
  answer: string;
  chunks: ChunkCitation[];
  model: string;
  repository_id: number | null;
}

// --- helpers -------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    // FastAPI returns {detail: ...} on errors; surface that string.
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail))
        detail = body.detail.map((d: { msg?: string }) => d.msg ?? "").join(", ");
    } catch {
      // ignore JSON parse errors and keep the status string
    }
    throw new Error(detail);
  }
  // 204 No Content has no body to parse.
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

// --- public API ----------------------------------------------------------

export const api = {
  health: () => request<Health>("/health"),

  listRepositories: () => request<RepositorySummary[]>("/repositories"),

  getRepository: (id: number) => request<RepositoryDetail>(`/repositories/${id}`),

  listRepositoryFiles: (id: number) =>
    request<RepositoryFile[]>(`/repositories/${id}/files`),

  deleteRepository: (id: number) =>
    request<void>(`/repositories/${id}`, { method: "DELETE" }),

  createRepositoryFromGithub: (url: string) =>
    request<CreateRepositoryResponse>("/repositories", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  ingestRepository: (name: string, localPath: string) =>
    request<IngestResult>("/ingest", {
      method: "POST",
      body: JSON.stringify({ name, local_path: localPath }),
    }),

  query: (question: string, repositoryId: number | null, topK = 5) =>
    request<QueryResult>("/query", {
      method: "POST",
      body: JSON.stringify({
        question,
        repository_id: repositoryId,
        top_k: topK,
      }),
    }),
};
