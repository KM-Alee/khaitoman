import type { ApiErrorBody } from "./types";
import { apiRequestUrl, backendCredentials, BACKEND_ORIGIN } from "./urls";

export { API_BASE } from "./urls";
export const CONTRACT_VERSION = "2.0.0";

/** A typed API failure; preserves HTTP status and the domain error code (T9.3). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: Record<string, string>;
  readonly body: unknown;
  constructor(status: number, body: Partial<ApiErrorBody> | null, fallback: string) {
    const detail = typeof body?.detail === "string" ? body.detail : fallback;
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = (body?.code as string) ?? (status === 0 ? "NETWORK" : `HTTP_${status}`);
    this.fields = (body?.fields as Record<string, string>) ?? {};
    this.body = body;
  }
  get isNotFound() {
    return this.status === 404;
  }
  get isConflict() {
    return this.status === 409;
  }
  get isUnavailable() {
    return this.status === 503 || this.status === 0;
  }
}

/** Friendly copy for each failure class; never a generic "Something went wrong". */
export function describeError(err: unknown): { title: string; detail: string } {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "NOT_FOUND":
        return { title: "Not found", detail: err.message };
      case "VERSION_CONFLICT":
        return { title: "Inputs changed underneath this view", detail: err.message };
      case "ASSET_UNAVAILABLE":
        return { title: "A required local asset is missing", detail: err.message };
      case "INVALID_INPUT":
        return { title: "Input rejected by validation", detail: fieldDetail(err) };
      case "PROVIDER_UNAVAILABLE":
        return { title: "Hosted assistant unavailable", detail: err.message };
      case "NETWORK":
        return { title: `${BACKEND_ORIGIN ? "Backend" : "Local"} API not reachable`, detail: "The AabFlow service did not respond." };
      default:
        if (err.status >= 500) return { title: `Service error (${err.status})`, detail: err.message };
        return { title: `Request failed (${err.status})`, detail: err.message };
    }
  }
  if (err instanceof Error) return { title: "Request failed", detail: err.message };
  return { title: "Request failed", detail: String(err) };
}

function fieldDetail(err: ApiError): string {
  const entries = Object.entries(err.fields);
  if (!entries.length) return err.message;
  return entries.map(([k, v]) => `${k}: ${v}`).join("; ");
}

function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Mutations that create resources carry an Idempotency-Key (T9.1). */
  idempotent?: boolean;
  idempotencyKey?: string;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? (opts.body === undefined ? "GET" : "POST");
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: string | undefined;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (method !== "GET") {
    headers["X-Contract-Version"] = CONTRACT_VERSION;
    if (opts.idempotent || opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey ?? newIdempotencyKey();
  }
  const url = apiRequestUrl(path);
  let res: Response;
  try {
    res = await fetch(url, { method, headers, body, signal: opts.signal, credentials: backendCredentials(url) });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new ApiError(0, null, (e as Error)?.message ?? "Network error");
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) {
    const b = (parsed && typeof parsed === "object" ? parsed : null) as Partial<ApiErrorBody> | null;
    // FastAPI validation errors arrive as {detail: [...]}
    if (b && Array.isArray((b as { detail?: unknown }).detail)) {
      const list = (b as unknown as { detail: { loc?: unknown[]; msg?: string }[] }).detail;
      const fields: Record<string, string> = {};
      for (const d of list) fields[(d.loc ?? []).slice(1).join(".") || "request"] = d.msg ?? "invalid";
      throw new ApiError(res.status, { code: "INVALID_INPUT", detail: "Validation failed", fields }, res.statusText);
    }
    throw new ApiError(res.status, b, res.statusText || `HTTP ${res.status}`);
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body: unknown, opts: Omit<RequestOptions, "body" | "method"> = {}) =>
    request<T>(path, { ...opts, method: "POST", body }),
  patch: <T>(path: string, body: unknown, opts: Omit<RequestOptions, "body" | "method"> = {}) =>
    request<T>(path, { ...opts, method: "PATCH", body }),
};

/** Build a query string, dropping null/undefined. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}
