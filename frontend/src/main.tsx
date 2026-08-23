import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ToastProvider } from "./components/Toast";
import { getInitialTheme } from "./lib/useTheme";
// Self-hosted variable fonts — bundled by Vite so they work offline/air-gapped.
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

// Apply theme synchronously before first render so there's no flash of
// the wrong palette when the user has chosen light mode (or the OS does).
document.documentElement.dataset.theme = getInitialTheme();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </React.StrictMode>,
);
