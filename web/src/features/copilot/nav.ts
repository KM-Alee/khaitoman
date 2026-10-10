/**
 * Copilot → UI navigation: citation clicks, action cards and server view intents. Only
 * IDs the server returned are used; the UI never retargets beyond the current pilot.
 */
import { useCallback } from "react";
import { useNavigate } from "react-router";
import { SCREENS, useSelection, type Screen } from "@/app/selection";
import { useUI } from "@/app/store";
import type { ActionKind, ViewIntent } from "./api";

export type RefKind = "run" | "field" | "evidence" | "comparison" | "analysis" | "report" | "branch" | "revision" | "job" | "other";

/** Normalise a citation/created-ref kind from the server into a navigable kind. */
export function refKind(kind: string | undefined, id: string): RefKind {
  const k = (kind ?? "").toLowerCase();
  if (k === "run" || k.endsWith("run") || id.startsWith("run_")) return "run";
  if (k === "field" || /:field-\d+/.test(id)) return "field";
  if (k === "comparison" || id.startsWith("cmp_")) return "comparison";
  if (k === "analysis" || id.startsWith("ana_")) return "analysis";
  if (k === "report" || id.startsWith("rep_")) return "report";
  if (k === "branch" || k === "scenario_revision" || k === "revision" || id.startsWith("rev_")) return "revision";
  if (k === "job" || id.startsWith("job_")) return "job";
  if (k.includes("evidence") || k === "source" || /^[a-z]+:/.test(id)) return "evidence";
  return "other";
}

export function actionKind(a: ActionKind): RefKind {
  return (
    { open_run: "run", open_branch: "revision", open_field: "field", open_report: "report", open_analysis: "analysis", open_comparison: "comparison" } as const
  )[a];
}

export function useCopilotNav() {
  const sel = useSelection();
  const navigate = useNavigate();
  const setUI = useUI((s) => s.set);

  /** Returns false when the ref has no view in this UI (e.g. a job or branch). */
  const open = useCallback(
    (kind: RefKind, id: string, extra?: { runIds?: string[] }): boolean => {
      switch (kind) {
        case "run":
          sel.setParams({ run: id }, false);
          return true;
        case "field":
          sel.setParams({ field: id }, false);
          return true;
        case "evidence":
          sel.go("evidence", { ev: id });
          return true;
        case "analysis":
          sel.go("explore", { analysis: id });
          return true;
        case "comparison":
          sel.go("compare", extra?.runIds?.length ? { runs: extra.runIds.join(",") } : {});
          return true;
        case "report":
          sel.go("report");
          return true;
        default:
          return false;
      }
    },
    [sel],
  );

  /** Apply a server view intent; returns a short human description of what changed (or why not). */
  const applyIntent = useCallback(
    (i: ViewIntent): { applied: boolean; label: string } => {
      switch (i.target) {
        case "run":
          if (i.run_id) sel.setParams({ run: i.run_id }, false);
          if (i.tab && SCREENS.includes(i.tab as Screen)) sel.go(i.tab as Screen, i.run_id ? { run: i.run_id } : {});
          return { applied: !!i.run_id, label: `Selected run ${i.run_id ?? ""}` };
        case "field":
          if (i.field_id) {
            sel.setParams({ field: i.field_id }, false);
          }
          return { applied: !!i.field_id, label: `Selected field ${i.field_id ?? ""}` };
        case "date":
          if (i.date) sel.setParams({ date: i.date }, false);
          return { applied: !!i.date, label: `Timeline date ${i.date ?? ""}` };
        case "tab":
          if (i.tab && SCREENS.includes(i.tab as Screen)) {
            sel.go(i.tab as Screen);
            return { applied: true, label: `Opened ${i.tab}` };
          }
          if (i.tab === "onboarding") {
            navigate("/onboarding");
            return { applied: true, label: "Opened onboarding" };
          }
          return { applied: false, label: `No ${i.tab ?? "unknown"} view in this build` };
        case "analysis":
          if (i.analysis_id) sel.go("explore", { analysis: i.analysis_id });
          return { applied: !!i.analysis_id, label: `Opened analysis ${i.analysis_id ?? ""}` };
        case "comparison":
          sel.go("compare");
          return { applied: true, label: "Opened Compare" };
        case "report":
          sel.go("report");
          return { applied: true, label: "Opened the report view" };
        case "pilot":
          if (i.pilot_id && i.pilot_id !== sel.pilotId)
            return { applied: false, label: `Pilot ${i.pilot_id} requested; switch pilots from the context bar (the next question uses it)` };
          return { applied: false, label: `Already on pilot ${i.pilot_id ?? ""}` };
        case "branch":
          setUI({ scenarioOpen: true });
          return { applied: false, label: `Branch ${i.scenario_revision_id ?? ""} is ready in the API; select it from the Scenario panel` };
        default:
          return { applied: false, label: "Unsupported view intent" };
      }
    },
    [sel, navigate, setUI],
  );

  return { open, applyIntent };
}
