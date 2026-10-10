/** Leave local development on its existing origin; use HTTPS for a separate laptop API. */
export function parseBackendOrigin(raw: string | undefined): string {
  const value = raw?.trim().replace(/\/$/, "") ?? "";
  if (!value) return "";
  const url = new URL(value);
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if ((url.protocol !== "https:" && !(url.protocol === "http:" && local)) ||
      url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("VITE_BACKEND_ORIGIN must be an HTTPS origin (or loopback HTTP for testing)");
  }
  return url.origin;
}

export const BACKEND_ORIGIN = parseBackendOrigin(import.meta.env.VITE_BACKEND_ORIGIN as string | undefined);
/** Public deployments omit the Access login UI; protected deployments default to it. */
export const BACKEND_ACCESS_REQUIRED = import.meta.env.VITE_BACKEND_ACCESS_REQUIRED !== "false";
export const API_BASE = `${BACKEND_ORIGIN}/api/v2`;

/** Resolve server-returned map, report and API links without rewriting unrelated URLs. */
export function backendUrl(path: string): string {
  return /^\/(?:api\/v2|assets)(?:\/|\?|$)/.test(path) ? BACKEND_ORIGIN + path : path;
}

export function apiRequestUrl(path: string): string {
  if (path.startsWith("/") && !path.startsWith("//") &&
      !/^\/(?:api\/v2|assets)(?:\/|\?|$)/.test(path)) return API_BASE + path;
  return backendUrl(path);
}

/** Include same-site Cloudflare Access cookies only on requests to our backend. */
export function backendCredentials(url: string): "include" | "same-origin" {
  const resolved = backendUrl(url);
  if (!BACKEND_ORIGIN || resolved === BACKEND_ORIGIN || resolved.startsWith(`${BACKEND_ORIGIN}/`)) return "include";
  return "same-origin";
}

export function backendMapRequest(url: string) {
  return { url: backendUrl(url), credentials: backendCredentials(url) };
}
