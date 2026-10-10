/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// Dev: Vite on 5173 proxies the API and assets to FastAPI on 8000 (T1.1).
// In compose the API is the `api` service (VITE_API_TARGET=http://api:8000).
const apiTarget = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  // Read VITE_* from the repo-root .env (e.g. VITE_ARCGIS_KEY); only VITE_-prefixed vars reach the client.
  envDir: fileURLToPath(new URL("..", import.meta.url)),
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    // Compose service names used by the Playwright container (e2e → web).
    allowedHosts: ["localhost", "127.0.0.1", "web"],
    proxy: {
      "/api/v2": apiTarget,
      "/assets": apiTarget,
    },
  },
  build: {
    outDir: "dist",
    assetsDir: "static",
    chunkSizeWarningLimit: 1100,
    rollupOptions: {
      output: {
        manualChunks: (id) =>
          id.includes("node_modules/maplibre-gl")
            ? "maplibre"
            : id.includes("node_modules/echarts") || id.includes("node_modules/zrender")
              ? "echarts"
              : id.includes("node_modules/react") || id.includes("node_modules/@radix-ui") || id.includes("node_modules/@tanstack")
                ? "vendor"
                : undefined,
      },
    },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test-setup.ts"] },
});
