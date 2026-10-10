/**
 * Job tracking: SSE `/jobs/{id}/events` with resumable event IDs (native EventSource sends
 * Last-Event-ID on reconnect), plus a GET /jobs/{id} poll as a fallback. Progress comes only
 * from server events — heartbeats update "last update", never a fake percentage.
 */
import { API_BASE, api } from "@/lib/api/client";
import type { Job, JobEvent } from "@/lib/api/types";

export interface JobUpdate {
  state?: Job["state"];
  stage?: string | null;
  progress?: number | null;
  resultRef?: string | null;
  error?: string | null;
}

export function watchJob(jobId: string, onUpdate: (u: JobUpdate) => void): () => void {
  let closed = false;
  let es: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const fromJob = (j: Job): JobUpdate => ({
    state: j.state,
    stage: j.stage,
    progress: j.progress,
    resultRef: j.result_ref,
    error: j.error ? String((j.error as { detail?: string }).detail ?? (j.error as { code?: string }).code ?? "Job failed") : null,
  });

  const poll = async () => {
    if (closed) return;
    try {
      const j = await api.get<Job>(`/jobs/${encodeURIComponent(jobId)}`);
      onUpdate(fromJob(j));
      if (["succeeded", "failed", "cancelled", "interrupted"].includes(j.state)) {
        stop();
        return;
      }
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 404) {
        onUpdate({ state: "interrupted", error: "The API no longer knows this job (restarted or removed)." });
        stop();
        return;
      }
    }
    timer = setTimeout(poll, 1500);
  };

  try {
    if (typeof EventSource !== "undefined") {
      es = new EventSource(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/events`);
      const handle = (ev: MessageEvent) => {
        try {
          const e = JSON.parse(ev.data) as Partial<JobEvent> & { state?: Job["state"] };
          const p = (e.payload ?? {}) as Record<string, unknown>;
          if (e.type === "stage") {
            const label = String(p.stage ?? p.label ?? "");
            onUpdate({
              stage: typeof p.detail === "string" && p.detail ? `${label} · ${p.detail}` : label,
              state: (p.state as Job["state"]) ?? "running",
              // Stage events may carry the worker's measured fraction; never invent one.
              ...(typeof p.progress === "number" ? { progress: p.progress } : {}),
            });
          }
          else if (e.type === "progress") onUpdate({ progress: typeof p.progress === "number" ? p.progress : null, stage: (p.stage as string) ?? undefined, state: "running" });
          else if (e.type === "result") void poll(); // authoritative terminal state via GET
          else if (e.type === "error" || e.type === "cancelled") void poll();
          else if (e.type === "heartbeat") onUpdate({});
        } catch {
          /* ignore malformed event */
        }
      };
      es.onmessage = handle;
      for (const t of ["stage", "progress", "result", "error", "cancelled", "heartbeat"]) es.addEventListener(t, handle as EventListener);
      es.onerror = () => {
        // EventSource reconnects with Last-Event-ID by itself; polling continues meanwhile.
      };
    }
  } catch {
    es = null;
  }
  void poll();

  function stop() {
    closed = true;
    es?.close();
    if (timer) clearTimeout(timer);
  }
  return stop;
}
