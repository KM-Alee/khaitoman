import { defineConfig } from "@playwright/test";

// Viewports from T10.6.
export default defineConfig({
  testDir: "../tests/e2e",
  use: { baseURL: "http://127.0.0.1:8000" },
  projects: [
    { name: "desktop-1920", use: { viewport: { width: 1920, height: 1200 } } },
    { name: "laptop-1366", use: { viewport: { width: 1366, height: 768 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
});
