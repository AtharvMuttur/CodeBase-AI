import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  CreateRepositoryResponse,
  RepositoryDetail,
  RepositorySummary,
} from "../lib/api";
import { useToasts } from "./Toast";
import { Modal } from "./Modal";
import {
  ChevronDownIcon,
  GithubIcon,
  FolderIcon,
  TrashIcon,
  SearchIcon,
  HomeIcon,
} from "./Icons";

interface Props {
  repos: RepositorySummary[];
  onReposChange: (next: RepositorySummary[]) => void;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  /** App-level loader so the list is shared with Chat. */
  loadRepos: () => Promise<void>;
}

/**
 * Sidebar with two ingest forms (GitHub URL and local path) and a
 * live list of indexed repositories. While a repository is in flight
 * the sidebar polls its detail endpoint so the user sees a real-time
 * status and progress bar.
 */
export function Sidebar({
  repos,
  onReposChange,
  selectedId,
  onSelect,
  loadRepos,
}: Props) {
  const { push } = useToasts();

  // --- GitHub form state ---
  const [githubUrl, setGithubUrl] = useState("");
  const [githubBusy, setGithubBusy] = useState(false);
  const [githubCollapsed, setGithubCollapsed] = useState(false);

  // --- Local-path form state (Phase 1, preserved) ---
  const [name, setName] = useState("sample-repo");
  const [path, setPath] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [localCollapsed, setLocalCollapsed] = useState(true);

  // --- Repository list state ---
  const [reposError, setReposError] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<number, RepositoryDetail>>({});
  const [filter, setFilter] = useState("");
  const [pendingDelete, setPendingDelete] = useState<RepositorySummary | null>(
    null,
  );

  const searchRef = useRef<HTMLInputElement | null>(null);

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
      try {
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
      } finally {
        if (!cancelled) {
          try {
            await loadRepos();
            setReposError(null);
          } catch (err) {
            setReposError((err as Error).message);
          }
        }
      }
    };
    const interval = inFlight ? 1000 : 5000;
    void tick();
    const id = window.setInterval(tick, interval);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [inFlight, repos, loadRepos]);

  // "/" focuses the search input (handled here so it scopes to this panel).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/") return;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName.toLowerCase();
      const isTyping =
        tag === "input" || tag === "textarea" || target?.isContentEditable;
      if (isTyping) return;
      e.preventDefault();
      searchRef.current?.focus();
      searchRef.current?.select();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const filteredRepos = useMemo(() => {
    if (!filter.trim()) return repos;
    const q = filter.trim().toLowerCase();
    return repos.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        (r.source_uri ?? "").toLowerCase().includes(q) ||
        (r.owner ?? "").toLowerCase().includes(q),
    );
  }, [filter, repos]);

  const mergeRepo = useCallback(
    (repo: RepositorySummary) => {
      onReposChange([
        ...repos.filter((r) => r.id !== repo.id),
        repo,
      ]);
    },
    [repos, onReposChange],
  );

  // --- GitHub submit ---
  const submitGithub = async (event: React.FormEvent) => {
    event.preventDefault();
    const url = githubUrl.trim();
    if (!url || githubBusy) return;
    setGithubBusy(true);
    try {
      const result: CreateRepositoryResponse =
        await api.createRepositoryFromGithub(url);
      push("success", result.message || `Queued ${result.name}.`);
      setGithubUrl("");
      await loadRepos();
      mergeRepo({
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
      push("error", (err as Error).message);
    } finally {
      setGithubBusy(false);
    }
  };

  // --- Local-path submit (Phase 1, preserved) ---
  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const result = await api.ingestRepository(name, path);
      push(
        "success",
        `Indexed ${result.file_count} files into ${result.chunk_count} chunks in ${result.elapsed_seconds}s.`,
      );
      await loadRepos();
      mergeRepo({
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
      push("error", (err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  // --- Delete ---
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const repo = pendingDelete;
    setPendingDelete(null);
    try {
      await api.deleteRepository(repo.id);
      setDetails((prev) => {
        const next = { ...prev };
        delete next[repo.id];
        return next;
      });
      await loadRepos();
      if (selectedId === repo.id) onSelect(null);
      push("info", `Deleted "${repo.name}".`);
    } catch (err) {
      push("error", (err as Error).message);
    }
  };

  const inFlightCount = repos.filter(
    (r) => r.status !== "ready" && r.status !== "failed",
  ).length;

  return (
    <aside className="sidebar" aria-label="Repository sidebar">
      {/* GitHub form */}
      <section className="sidebar__section" aria-labelledby="gh-heading">
        <h2
          id="gh-heading"
          className="sidebar__heading"
          data-collapsed={githubCollapsed ? "true" : "false"}
          onClick={() => setGithubCollapsed((v) => !v)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setGithubCollapsed((v) => !v);
            }
          }}
        >
          <span>Clone from GitHub</span>
          <span className="sidebar__heading-toggle" aria-hidden="true">
            <ChevronDownIcon size={14} />
          </span>
        </h2>
        {!githubCollapsed && (
          <form className="ingest-form" onSubmit={submitGithub}>
            <label htmlFor="repo-url">Public GitHub URL</label>
            <input
              id="repo-url"
              value={githubUrl}
              onChange={(e) => setGithubUrl(e.target.value)}
              placeholder="https://github.com/owner/repo"
              disabled={githubBusy}
              spellCheck={false}
            />
            <button type="submit" disabled={githubBusy || !githubUrl.trim()}>
              {githubBusy ? "Submitting…" : "Clone & Index"}
            </button>
          </form>
        )}
      </section>

      {/* Local-path form (Phase 1) */}
      <section className="sidebar__section" aria-labelledby="local-heading">
        <h2
          id="local-heading"
          className="sidebar__heading"
          data-collapsed={localCollapsed ? "true" : "false"}
          onClick={() => setLocalCollapsed((v) => !v)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setLocalCollapsed((v) => !v);
            }
          }}
        >
          <span>Index a local folder</span>
          <span className="sidebar__heading-toggle" aria-hidden="true">
            <ChevronDownIcon size={14} />
          </span>
        </h2>
        {!localCollapsed && (
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
              spellCheck={false}
            />
            <button type="submit" disabled={submitting || !name || !path}>
              {submitting ? "Indexing…" : "Index"}
            </button>
          </form>
        )}
      </section>

      {/* Repository list */}
      <section className="sidebar__section" aria-labelledby="repos-heading">
        <h2 id="repos-heading" className="sidebar__heading">
          <span>
            Indexed repositories
            {inFlightCount > 0 && (
              <span
                className="sidebar__count"
                style={{ marginLeft: 8 }}
                title={`${inFlightCount} indexing`}
              >
                {inFlightCount} indexing
              </span>
            )}
          </span>
          <span className="sidebar__count" title={`${repos.length} total`}>
            {repos.length}
          </span>
        </h2>

        <div className="sidebar__search-wrapper">
          <SearchIcon size={15} />
          <input
            ref={searchRef}
            type="search"
            className="sidebar__search"
            placeholder="Filter repositories… (/)"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            aria-label="Filter repositories"
          />
        </div>

        {reposError && (
          <div className="banner banner--error" role="alert">
            {reposError}
          </div>
        )}
        {repos.length === 0 && !reposError && (
          <div className="repo-list__empty">
            No repositories indexed yet. Clone a GitHub URL or index a local
            folder above.
          </div>
        )}
        {repos.length > 0 && filteredRepos.length === 0 && (
          <div className="repo-list__empty">
            No matches for "{filter}".
          </div>
        )}
        <div className="repo-list">
          <button
            type="button"
            className={`repo-card ${selectedId === null ? "repo-card--selected" : ""}`}
            onClick={() => onSelect(null)}
          >
            <div className="repo-card__body">
              <div className="repo-card__name">
                <span className="repo-card__name-icon">
                  <HomeIcon size={14} />
                </span>
                <span className="repo-card__name-text">All repositories</span>
              </div>
              <div className="repo-card__meta">
                <span>search across every indexed repo</span>
              </div>
            </div>
          </button>
          {filteredRepos.map((repo) => (
            <RepoCard
              key={repo.id}
              repo={repo}
              detail={details[repo.id]}
              selected={selectedId === repo.id}
              onSelect={() => onSelect(repo.id)}
              onDelete={() => setPendingDelete(repo)}
            />
          ))}
        </div>
      </section>

      {/* Delete confirmation modal */}
      <Modal
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title="Delete repository?"
        footer={
          <>
            <button
              type="button"
              className="secondary"
              onClick={() => setPendingDelete(null)}
            >
              Cancel
            </button>
            <button type="button" className="danger" onClick={confirmDelete}>
              Delete
            </button>
          </>
        }
      >
        {pendingDelete && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <p style={{ margin: 0 }}>
              This will permanently delete{" "}
              <strong>{pendingDelete.name}</strong> and remove all of its
              indexed files and chunks.
            </p>
            <p style={{ margin: 0, color: "var(--fg-muted)", fontSize: 12 }}>
              Source: {pendingDelete.source}
              {pendingDelete.source_uri ? ` · ${pendingDelete.source_uri}` : ""}
            </p>
          </div>
        )}
      </Modal>
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
  onDelete: () => void;
}) {
  const liveStatus = detail?.status ?? repo.status;
  const liveFiles = detail?.files_processed ?? repo.file_count;
  const liveTotal = detail?.total_files ?? 0;
  const liveError = detail?.error_message ?? repo.error_message;
  const isTerminal = liveStatus === "ready" || liveStatus === "failed";
  const pct =
    liveTotal > 0 ? Math.min(100, Math.round((liveFiles / liveTotal) * 100)) : 0;

  const SourceIconCmp = repo.source === "github" ? GithubIcon : FolderIcon;

  return (
    <div
      className={`repo-card ${selected ? "repo-card--selected" : ""}`}
      data-status={liveStatus}
    >
      <button
        type="button"
        className="repo-card__body"
        onClick={onSelect}
        aria-label={`Select ${repo.name}`}
        aria-pressed={selected}
      >
        <div className="repo-card__name">
          <span className="repo-card__name-icon" aria-hidden="true">
            <SourceIconCmp size={14} />
          </span>
          <span className="repo-card__name-text">{repo.name}</span>
        </div>
        <div className="repo-card__meta">
          <span className="repo-card__meta-item">#{repo.id}</span>
          <span className="repo-card__meta-item">{repo.source}</span>
          <span className={`status-pill status-${liveStatus}`}>
            {liveStatus}
          </span>
        </div>
        {liveStatus === "ready" && (
          <div className="repo-card__meta">
            <span className="repo-card__meta-item">
              {repo.file_count} files
            </span>
            <span className="repo-card__meta-item">
              {repo.chunk_count} chunks
            </span>
            {repo.commit_sha && (
              <span
                className="repo-card__meta-item"
                title={repo.commit_sha}
                style={{ fontFamily: "var(--mono)" }}
              >
                {repo.commit_sha.slice(0, 7)}
              </span>
            )}
          </div>
        )}
        {!isTerminal && (
          <div className="progress" aria-label={`indexing ${pct}%`}>
            <div className="progress__bar" style={{ width: `${pct}%` }} />
            <span className="progress__text">
              {liveTotal > 0
                ? `${liveFiles} / ${liveTotal} files`
                : liveStatus}
            </span>
          </div>
        )}
        {liveStatus === "failed" && liveError && (
          <div className="banner banner--error">{liveError}</div>
        )}
      </button>
      <button
        type="button"
        className="repo-card__delete"
        onClick={onDelete}
        title={`Delete ${repo.name}`}
        aria-label={`Delete ${repo.name}`}
      >
        <TrashIcon size={15} />
      </button>
    </div>
  );
}
