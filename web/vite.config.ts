/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// Dev: Vite on 5173 proxies the API and assets to FastAPI on 8000 (T1.1).
// In compose the API is the `api` service (VITE_API_TARGET=http://api:8000).
const apiTarget = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      "/api/v2": apiTarget,
      "/assets": apiTarget,
    },
  },
  build: { outDir: "dist", assetsDir: "static" },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test-setup.ts"] },
});
