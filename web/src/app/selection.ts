/**
 * URL-encoded stable selections (T10.2): pilot/version in the path; run, field, date,
 * compared runs, analysis and evidence in the query string. Never secrets or transcripts.
 */
import { useCallback, useMemo } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";

export type Screen =
  | "workspace"
  | "compare"
  | "replay"
  | "explore"
  | "impact"
  | "report"
  | "evidence";

export const SCREENS: Screen[] = ["workspace", "compare", "replay", "explore", "impact", "report", "evidence"];

export interface Selection {
  pilotId: string | undefined;
  version: string | undefined;
  pilotKey: string;
  screen: Screen;
  runId: string | null;
  fieldId: string | null;
  date: string | null;
  compareRunIds: string[];
  analysisId: string | null;
  tab: string | null;
  evidenceId: string | null;
  q: string | null;
}

export function useSelection(): Selection & {
  setParams: (p: Partial<Record<"run" | "field" | "date" | "runs" | "analysis" | "tab" | "ev" | "q", string | null>>, replace?: boolean) => void;
  go: (screen: Screen, p?: Partial<Record<string, string | null>>) => void;
  hrefFor: (screen: Screen, p?: Partial<Record<string, string | null>>) => string;
} {
  const { pilotId, version, screen } = useParams();
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();

  const sel = useMemo<Selection>(
    () => ({
      pilotId,
      version,
      pilotKey: `${pilotId ?? ""}@${version ?? ""}`,
      screen: (SCREENS.includes(screen as Screen) ? screen : "workspace") as Screen,
      runId: sp.get("run"),
      fieldId: sp.get("field"),
      date: sp.get("date"),
      compareRunIds: (sp.get("runs") ?? "").split(",").filter(Boolean),
      analysisId: sp.get("analysis"),
      tab: sp.get("tab"),
      evidenceId: sp.get("ev"),
      q: sp.get("q"),
    }),
    [pilotId, version, screen, sp],
  );

  const setParams = useCallback(
    (p: Partial<Record<string, string | null>>, replace = true) => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(p)) {
            if (v === null || v === undefined || v === "") next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace },
      );
    },
    [setSp],
  );

  const hrefFor = useCallback(
    (target: Screen, p: Partial<Record<string, string | null>> = {}) => {
      const keep = new URLSearchParams();
      // Carry stable selections across screens.
      for (const k of ["run", "field", "date", "runs"]) {
        const v = sp.get(k);
        if (v) keep.set(k, v);
      }
      for (const [k, v] of Object.entries(p)) {
        if (v === null || v === undefined || v === "") keep.delete(k);
        else keep.set(k, v);
      }
      const q = keep.toString();
      return `/p/${encodeURIComponent(pilotId ?? "")}/${encodeURIComponent(version ?? "")}/${target}${q ? `?${q}` : ""}`;
    },
    [pilotId, version, sp],
  );

  const go = useCallback(
    (target: Screen, p: Partial<Record<string, string | null>> = {}) => {
      const href = hrefFor(target, p);
      if (href !== location.pathname + location.search) navigate(href);
    },
    [hrefFor, navigate, location],
  );

  return { ...sel, setParams, go, hrefFor };
}
