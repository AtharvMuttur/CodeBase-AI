import { useCallback, useEffect, useState } from "react";
import {
  api,
  CreateRepositoryResponse,
  RepositoryDetail,
  RepositorySummary,
} from "../lib/api";

interface Props {
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  onIngested: (repo: RepositorySummary) => void;
}

/**
 * Sidebar with two ingest forms (GitHub URL and local path) and a
 * live list of indexed repositories. While a repository is in flight
 * the sidebar polls its detail endpoint so the user sees a real-time
 * status and progress bar.
 */
export function Sidebar({ selectedId, onSelect, onIngested }: Props) {
  // --- GitHub form state ---
  const [githubUrl, setGithubUrl] = useState("");
  const [githubBusy, setGithubBusy] = useState(false);
  const [githubError, setGithubError] = useState<string | null>(null);
  const [githubNotice, setGithubNotice] = useState<string | null>(null);

  // --- Local-path form state (Phase 1, preserved) ---
  const [name, setName] = useState("sample-repo");
  const [path, setPath] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // --- Repository list state ---
  const [repos, setRepos] = useState<RepositorySummary[]>([]);
  const [reposError, setReposError] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<number, RepositoryDetail>>({});

  const loadRepos = useCallback(async () => {
    try {
      const list = await api.listRepositories();
      setRepos(list);
      setReposError(null);
    } catch (err) {
      setReposError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void loadRepos();
  }, [loadRepos]);

  // Keep a live detail snapshot for any repo that isn't terminal.
  // We poll once a second while at least one row is in flight, and
  // once every five seconds as a safety net so a row that flips
  // from queued → ready off-screen still refreshes quickly.
  const inFlight = repos.some(
    (r) => r.status !== "ready" && r.status !== "failed",
  );
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      for (const repo of repos) {
        if (repo.status === "ready" || repo.status === "failed") continue;
        try {
          const detail = await api.getRepository(repo.id);
          if (cancelled) return;
          setDetails((prev) => ({ ...prev, [repo.id]: detail }));
        } catch {
          // network blip — try again next tick
        }
      }
      await loadRepos();
    };
    const interval = inFlight ? 1000 : 5000;
    void tick();
    const id = window.setInterval(tick, interval);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [inFlight, repos, loadRepos]);

  // --- GitHub submit ---
  const submitGithub = async (event: React.FormEvent) => {
    event.preventDefault();
    const url = githubUrl.trim();
    if (!url || githubBusy) return;
    setGithubError(null);
    setGithubNotice(null);
    setGithubBusy(true);
    try {
      const result: CreateRepositoryResponse = await api.createRepositoryFromGithub(url);
      setGithubNotice(result.message || `Queued ${result.name}.`);
      setGithubUrl("");
      await loadRepos();
      onIngested({
        id: result.repository_id,
        name: result.name,
        source: "github",
        source_uri: result.url,
        owner: result.owner,
        branch: result.branch,
        commit_sha: result.commit_sha,
        file_count: 0,
        chunk_count: 0,
        status: result.status,
        error_message: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      onSelect(result.repository_id);
    } catch (err) {
      setGithubError((err as Error).message);
    } finally {
      setGithubBusy(false);
    }
  };

  // --- Local-path submit (Phase 1, preserved) ---
  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setSubmitting(true);
    try {
      const result = await api.ingestRepository(name, path);
      setSuccess(
        `Indexed ${result.file_count} files into ${result.chunk_count} chunks in ${result.elapsed_seconds}s.`,
      );
      await loadRepos();
      onIngested({
        id: result.repository_id,
        name: result.name,
        source: "local",
        source_uri: path,
        owner: null,
        branch: null,
        commit_sha: null,
        file_count: result.file_count,
        chunk_count: result.chunk_count,
        status: result.status,
        error_message: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      onSelect(result.repository_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  // --- Delete ---
  const handleDelete = async (event: React.MouseEvent, repo: RepositorySummary) => {
    event.stopPropagation();
    if (
      !window.confirm(
        `Delete repository "${repo.name}"? Its files and chunks will be removed.`,
      )
    ) {
      return;
    }
    try {
      await api.deleteRepository(repo.id);
      setDetails((prev) => {
        const next = { ...prev };
        delete next[repo.id];
        return next;
      });
      await loadRepos();
      if (selectedId === repo.id) onSelect(null);
    } catch (err) {
      setReposError((err as Error).message);
    }
  };

  return (
    <aside className="sidebar">
      {/* GitHub form */}
      <div>
        <h2>Clone from GitHub</h2>
        <form className="ingest-form" onSubmit={submitGithub}>
          <label htmlFor="repo-url">Public GitHub URL</label>
          <input
            id="repo-url"
            value={githubUrl}
            onChange={(e) => setGithubUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            required
            disabled={githubBusy}
          />
          <button type="submit" disabled={githubBusy || !githubUrl.trim()}>
            {githubBusy ? "Submitting…" : "Clone & Index"}
          </button>
          {githubError && <div className="banner error">{githubError}</div>}
          {githubNotice && <div className="banner success">{githubNotice}</div>}
        </form>
      </div>

      {/* Local-path form (Phase 1) */}
      <div>
        <h2>Index a local folder</h2>
        <form className="ingest-form" onSubmit={handleSubmit}>
          <label htmlFor="repo-name">Name</label>
          <input
            id="repo-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-project"
            required
          />
          <label htmlFor="repo-path">Local path</label>
          <input
            id="repo-path"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="C:\Users\you\projects\my-project"
            required
          />
          <button type="submit" disabled={submitting}>
            {submitting ? "Indexing…" : "Index"}
          </button>
          {error && <div className="banner error">{error}</div>}
          {success && <div className="banner success">{success}</div>}
        </form>
      </div>

      {/* Repository list */}
      <div>
        <h2>Indexed repositories</h2>
        {reposError && <div className="banner error">{reposError}</div>}
        {repos.length === 0 && !reposError && (
          <div className="banner">No repositories indexed yet.</div>
        )}
        <div className="repo-list">
          <button
            type="button"
            className={`repo-card ${selectedId === null ? "selected" : ""}`}
            onClick={() => onSelect(null)}
          >
            <div className="name">All repositories</div>
            <div className="meta">search across every indexed repo</div>
          </button>
          {repos.map((repo) => (
            <RepoCard
              key={repo.id}
              repo={repo}
              detail={details[repo.id]}
              selected={selectedId === repo.id}
              onSelect={() => onSelect(repo.id)}
              onDelete={(e) => handleDelete(e, repo)}
            />
          ))}
        </div>
      </div>
    </aside>
  );
}

function RepoCard({
  repo,
  detail,
  selected,
  onSelect,
  onDelete,
}: {
  repo: RepositorySummary;
  detail?: RepositoryDetail;
  selected: boolean;
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
}) {
  const liveStatus = detail?.status ?? repo.status;
  const liveFiles = detail?.files_processed ?? repo.file_count;
  const liveTotal = detail?.total_files ?? 0;
  const liveError = detail?.error_message ?? repo.error_message;
  const isTerminal = liveStatus === "ready" || liveStatus === "failed";
  const pct =
    liveTotal > 0 ? Math.min(100, Math.round((liveFiles / liveTotal) * 100)) : 0;

  return (
    <div className={`repo-card ${selected ? "selected" : ""}`}>
      <button
        type="button"
        className="repo-card-button"
        onClick={onSelect}
        aria-label={`Select ${repo.name}`}
      >
        <div className="name">{repo.name}</div>
        <div className="meta">
          <span>#{repo.id}</span>
          <span>src: {repo.source}</span>
          <span className={`status-pill status-${liveStatus}`}>{liveStatus}</span>
        </div>
        {liveStatus === "ready" && (
          <div className="meta">
            <span>{repo.file_count} files</span>
            <span>{repo.chunk_count} chunks</span>
            {repo.commit_sha && <span>{repo.commit_sha.slice(0, 7)}</span>}
          </div>
        )}
        {!isTerminal && (
          <div className="progress" aria-label={`indexing ${pct}%`}>
            <div className="progress-bar" style={{ width: `${pct}%` }} />
            <span className="progress-text">
              {liveTotal > 0
                ? `${liveFiles} / ${liveTotal} files`
                : liveStatus}
            </span>
          </div>
        )}
        {liveStatus === "failed" && liveError && (
          <div className="banner error">{liveError}</div>
        )}
      </button>
      <button
        type="button"
        className="repo-delete"
        onClick={onDelete}
        title={`Delete ${repo.name}`}
      >
        ×
      </button>
    </div>
  );
}
