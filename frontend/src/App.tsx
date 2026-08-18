import { useEffect, useState } from "react";
import { api, Health } from "./lib/api";
import { Sidebar } from "./components/Sidebar";
import { Chat } from "./components/Chat";

/**
 * Top-level layout. Owns the global state: which repository is selected,
 * and the current backend health. The sidebar mutates these; the chat
 * reads them.
 */
export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<number | null>(null);

  useEffect(() => {
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
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <h1>
          CodeBase<span className="accent"> AI</span>
        </h1>
        <div className="status">
          {healthError ? (
            <>
              <span className="dot error" />
              <span>backend offline — {healthError}</span>
            </>
          ) : health ? (
            <>
              <span className={`dot ${health.database ? "ok" : "degraded"}`} />
              <span>
                v{health.version} · db {health.database ? "ok" : "offline"}
              </span>
            </>
          ) : (
            <>
              <span className="dot" />
              <span>checking…</span>
            </>
          )}
        </div>
      </header>

      <Sidebar
        selectedId={selectedRepo}
        onSelect={setSelectedRepo}
        onIngested={() => {
          /* The sidebar already refreshed the repo list and selected
           * the freshly-created row. Nothing for the parent to do. */
        }}
      />

      <Chat repositoryId={selectedRepo} />
    </div>
  );
}
