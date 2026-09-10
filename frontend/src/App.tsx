import { useCallback, useEffect, useState } from "react";
import { api, Health, RepositorySummary } from "./lib/api";
import { Sidebar } from "./components/Sidebar";
import { Chat } from "./components/Chat";
import { ShortcutsModal } from "./components/ShortcutsModal";
import { Auth } from "./components/Auth";
import { AuthResponse, User } from "./lib/api";
import { useTheme } from "./lib/useTheme";
import { MenuIcon, MoonIcon, SunIcon, KeyboardIcon, SparklesIcon } from "./components/Icons";

/**
 * Top-level layout. Owns the global state: which repository is selected,
 * the current backend health, the active theme, and whether the mobile
 * sidebar is open. The sidebar mutates the repo selection; the chat
 * reads it.
 *
 * The repository list is hoisted to App so the Chat component can show
 * a friendly repo name on each message without re-fetching.
 */
export default function App() {
  const [authChecked, setAuthChecked] = useState(false);
  const [authUser, setAuthUser] = useState<User | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [repos, setRepos] = useState<RepositorySummary[]>([]);
  const { theme, toggle: toggleTheme } = useTheme();

  useEffect(() => {
    if (!api.hasToken()) {
      setAuthChecked(true);
      return;
    }
    void api.me()
      .then(setAuthUser)
      .catch(() => api.clearToken())
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    if (!authUser) return;
    const refresh = async () => {
      try {
        const h = await api.health();
        setHealth(h);
        setHealthError(null);
      } catch (err) {
        setHealthError((err as Error).message);
      }
    };
    void refresh();
    const id = window.setInterval(refresh, 15_000);
    return () => window.clearInterval(id);
  }, [authUser]);

  // Hoisted repo loader — both Sidebar and Chat call this so they stay
  // in sync without duplicate GETs.
  const loadRepos = useCallback(async () => {
    try {
      const list = await api.listRepositories();
      setRepos(list);
    } catch {
      /* Sidebar surfaces its own copy of the error. */
    }
  }, []);

  // Global keyboard shortcuts: "?" opens the help, "/" focuses sidebar
  // search (handled inside Sidebar). Escape closes the mobile sidebar.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName.toLowerCase();
      const isTyping =
        tag === "input" || tag === "textarea" || target?.isContentEditable;
      if (e.key === "?" && !isTyping) {
        e.preventDefault();
        setShortcutsOpen((v) => !v);
      } else if (e.key === "Escape" && sidebarOpen) {
        setSidebarOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [sidebarOpen]);

  const handleSelect = useCallback((id: number | null) => {
    setSelectedRepo(id);
    setSidebarOpen(false);
  }, []);

  const handleAuthenticated = useCallback((result: AuthResponse) => {
    api.setToken(result.access_token);
    setAuthUser(result.user);
  }, []);

  if (!authChecked) {
    return <div className="auth-loading">Loading your workspace...</div>;
  }

  if (!authUser) {
    return <Auth onAuthenticated={handleAuthenticated} />;
  }

  const status = (() => {
    if (healthError) {
      return (
        <>
          <span className="status__dot status__dot--error" />
          <span>offline</span>
        </>
      );
    }
    if (health) {
      return (
        <>
          <span
            className={`status__dot ${health.database ? "status__dot--ok" : "status__dot--degraded"}`}
          />
          <span>v{health.version}</span>
        </>
      );
    }
    return (
      <>
        <span className="status__dot status__dot--idle" />
        <span>checking…</span>
      </>
    );
  })();

  return (
    <div className={`app ${sidebarOpen ? "app--sidebar-open" : ""}`}>
      <header className="topbar">
        <div className="topbar__brand">
          <button
            type="button"
            className="topbar__menu"
            aria-label="Toggle sidebar"
            onClick={() => setSidebarOpen((v) => !v)}
          >
            <MenuIcon size={18} />
          </button>
          <div className="topbar__logo" aria-hidden="true">
            <SparklesIcon size={16} />
          </div>
          <h1 className="topbar__title">
            CodeBase<span className="accent"> AI</span>
          </h1>
        </div>
        <div className="topbar__actions">
          <div className="topbar__user" title={authUser.email}>
            {authUser.email}
          </div>
          <div className="status" aria-live="polite">
            {status}
          </div>
          <button
            type="button"
            className="topbar__icon-button"
            aria-label={
              theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
            }
            title={
              theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
            }
            onClick={toggleTheme}
          >
            {theme === "dark" ? <SunIcon size={18} /> : <MoonIcon size={18} />}
          </button>
          <button
            type="button"
            className="topbar__signout"
            onClick={() => {
              api.clearToken();
              setAuthUser(null);
              setRepos([]);
              setSelectedRepo(null);
            }}
          >
            Sign out
          </button>
          <button
            type="button"
            className="topbar__icon-button"
            aria-label="Keyboard shortcuts (?)"
            title="Keyboard shortcuts (?)"
            onClick={() => setShortcutsOpen(true)}
          >
            <KeyboardIcon size={18} />
          </button>
        </div>
      </header>

      {sidebarOpen && (
        <div
          className="sidebar-overlay"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <Sidebar
        repos={repos}
        onReposChange={setRepos}
        selectedId={selectedRepo}
        onSelect={handleSelect}
        loadRepos={loadRepos}
      />

      <Chat repositoryId={selectedRepo} repos={repos} />

      <ShortcutsModal
        open={shortcutsOpen}
        onClose={() => setShortcutsOpen(false)}
      />
    </div>
  );
}
