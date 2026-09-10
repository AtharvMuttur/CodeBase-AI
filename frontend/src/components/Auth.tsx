import { useState } from "react";
import { api, AuthResponse } from "../lib/api";
import { SparklesIcon } from "./Icons";

interface Props {
  onAuthenticated: (result: AuthResponse) => void;
}

export function Auth({ onAuthenticated }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const result =
        mode === "login"
          ? await api.login(email, password)
          : await api.register(email, password);
      onAuthenticated(result);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-shell">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-brand">
          <span className="auth-brand__mark"><SparklesIcon size={18} /></span>
          <span>CodeBase<span className="accent"> AI</span></span>
        </div>
        <span className="auth-kicker">Private repository intelligence</span>
        <h1 id="auth-title">
          {mode === "login" ? "Welcome back" : "Create your workspace"}
        </h1>
        <p className="auth-subtitle">
          {mode === "login"
            ? "Sign in to access your indexed repositories."
            : "Your repositories will be visible only to you."}
        </p>

        <form className="auth-form" onSubmit={submit}>
          <label htmlFor="auth-email">Email</label>
          <input
            id="auth-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            required
          />
          <label htmlFor="auth-password">Password</label>
          <input
            id="auth-password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="At least 8 characters"
            minLength={8}
            required
          />
          {error && <div className="banner banner--error" role="alert">{error}</div>}
          <button type="submit" disabled={busy}>
            {busy ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button
          type="button"
          className="auth-switch"
          onClick={() => {
            setMode((current) => current === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "Need an account? Create one" : "Already have an account? Sign in"}
        </button>
      </section>
    </main>
  );
}
