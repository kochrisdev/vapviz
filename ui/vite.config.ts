import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy every backend route to the API server. `/metrics` and `/search`
      // were missing, so in dev they fell through to the SPA index.html and the
      // Analytics page hung on "Loading metrics…" (r.json() on HTML throws).
      "/runs": { target: "http://localhost:8001", changeOrigin: true },
      "/metrics": { target: "http://localhost:8001", changeOrigin: true },
      "/search": { target: "http://localhost:8001", changeOrigin: true },
    },
  },
});
