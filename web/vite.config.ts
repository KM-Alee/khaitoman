/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// Dev: Vite on 5173 proxies the API and assets to FastAPI on 8000 (T1.1).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      "/api/v2": "http://127.0.0.1:8000",
      "/assets": "http://127.0.0.1:8000",
    },
  },
  build: { outDir: "dist", assetsDir: "static" },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test-setup.ts"] },
});
