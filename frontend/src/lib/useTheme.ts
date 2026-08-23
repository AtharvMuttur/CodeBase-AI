import { useEffect, useState } from "react";
import { getJSON, setJSON } from "./storage";

export type Theme = "dark" | "light";

const STORAGE_KEY = "codebase-ai.theme";

function systemPrefersLight(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: light)").matches
  );
}

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

/**
 * Read the user's stored preference (or OS fallback) synchronously.
 * Called once at boot from main.tsx so the first paint already has
 * the right [data-theme] and there's no flash of the wrong palette.
 */
export function getInitialTheme(): Theme {
  const stored = getJSON<Theme | null>(STORAGE_KEY, null);
  if (stored === "dark" || stored === "light") return stored;
  return systemPrefersLight() ? "light" : "dark";
}

/**
 * Theme hook. Persists user choice to localStorage; falls back to the OS
 * preference on first load. Updates <html data-theme> so CSS variables swap.
 */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(() => getInitialTheme());

  useEffect(() => {
    applyTheme(theme);
    setJSON(STORAGE_KEY, theme);
  }, [theme]);

  // Track OS preference only while the user has not explicitly chosen.
  useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      const stored = getJSON<Theme | null>(STORAGE_KEY, null);
      if (stored === null) setTheme(mql.matches ? "light" : "dark");
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return {
    theme,
    toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
  };
}
