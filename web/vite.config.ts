import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In dev the API runs on 8090 (`python -m orchestrator.cli serve`); in production the same server serves this build.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5190, proxy: { "/api": "http://127.0.0.1:8090" } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
