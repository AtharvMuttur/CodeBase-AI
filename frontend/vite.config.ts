import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite picks up VITE_API_BASE from the environment (set in docker-compose,
// or in a local .env). Default to the in-cluster URL so a vanilla
// `vite dev` against the running backend "just works".
const apiBase = process.env.VITE_API_BASE || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      // During `vite dev`, forward /api requests to the backend so the
      // browser doesn't have to deal with CORS in development.
      "/api": {
        target: apiBase,
        changeOrigin: true,
      },
    },
  },
  define: {
    // Inject the configured API base so the runtime code reads it
    // from `import.meta.env.VITE_API_BASE` exactly like create-vite
    // would have set up.
    "import.meta.env.VITE_API_BASE": JSON.stringify(apiBase),
  },
});
