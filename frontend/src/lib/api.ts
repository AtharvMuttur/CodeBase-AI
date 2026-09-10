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
const TOKEN_KEY = "codebase-ai-access-token";

function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export interface Health {
  status: "ok" | "degraded" | "error";
  version: string;
  database: boolean;
  timestamp: string;
  details: Record<string, unknown>;
}

export interface User {
  id: number;
  email: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
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
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  // Honour AbortSignal — the caller may pass one via init.signal to cancel
  // an in-flight request. The browser will surface that as a DOMException
  // (AbortError) here; we let it propagate so callers can render "stopped".
  if (init?.signal?.aborted) {
    throw new DOMException("Request aborted", "AbortError");
  }
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
  hasToken: () => Boolean(getToken()),

  setToken: (token: string) => {
    window.localStorage.setItem(TOKEN_KEY, token);
  },

  clearToken: () => {
    window.localStorage.removeItem(TOKEN_KEY);
  },

  register: (email: string, password: string) =>
    request<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }).then((result) => {
      api.setToken(result.access_token);
      return result;
    }),

  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }).then((result) => {
      api.setToken(result.access_token);
      return result;
    }),

  me: () => request<User>("/auth/me"),

  health: () => request<Health>("/health"),

  listRepositories: () => request<RepositorySummary[]>("/repositories"),

  getRepository: (id: number) => request<RepositoryDetail>(`/repositories/${id}`),

  listRepositoryFiles: (id: number) =>
    request<RepositoryFile[]>(`/repositories/${id}/files`),

  deleteRepository: (id: number) =>
    request<void>(`/repositories/${id}`, { method: "DELETE" }),

  createRepositoryFromGithub: (url: string, signal?: AbortSignal) =>
    request<CreateRepositoryResponse>("/repositories", {
      method: "POST",
      body: JSON.stringify({ url }),
      signal,
    }),

  ingestRepository: (name: string, localPath: string, signal?: AbortSignal) =>
    request<IngestResult>("/ingest", {
      method: "POST",
      body: JSON.stringify({ name, local_path: localPath }),
      signal,
    }),

  query: (
    question: string,
    repositoryId: number | null,
    topK = 5,
    signal?: AbortSignal,
  ) =>
    request<QueryResult>("/query", {
      method: "POST",
      body: JSON.stringify({
        question,
        repository_id: repositoryId,
        top_k: topK,
      }),
      signal,
    }),
};
