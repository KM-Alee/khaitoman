/**
 * Stage events of one job, read from the server's SSE stream (`/jobs/{id}/events`).
 * The stream replays every stored event from the start, so a reload shows the same log.
 * Nothing is synthesized: without EventSource (tests, old browsers) the log stays empty
 * and the screen falls back to the polled job stage on the intake record.
 */
import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api/client";

export interface StageEvent {
  id: number;
  at: string;
  type: string;
  stage: string;
  detail: string | null;
  progress: number | null;
}

export function useStageLog(jobId: string | null | undefined): StageEvent[] {
  const [events, setEvents] = useState<StageEvent[]>([]);
  useEffect(() => {
    setEvents([]);
    if (!jobId || typeof EventSource === "undefined") return;
    const es = new EventSource(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/events`);
    const seen = new Set<number>();
    const handle = (ev: MessageEvent) => {
      try {
        const e = JSON.parse(ev.data) as { event_id: number; created_at: string; type: string; payload?: Record<string, unknown> };
        if (seen.has(e.event_id) || e.type === "heartbeat") return;
        seen.add(e.event_id);
        const p = e.payload ?? {};
        const stage = typeof p.stage === "string" ? p.stage : e.type;
        const detail = typeof p.detail === "string" ? p.detail : null;
        const progress = typeof p.progress === "number" ? p.progress : null;
        setEvents((prev) => [...prev, { id: e.event_id, at: e.created_at, type: e.type, stage, detail, progress }]);
        if (e.type === "result" || e.type === "error" || e.type === "cancelled") es.close();
      } catch {
        /* ignore malformed event */
      }
    };
    for (const t of ["stage", "progress", "result", "error", "cancelled"]) es.addEventListener(t, handle as EventListener);
    return () => es.close();
  }, [jobId]);
  return events;
}
