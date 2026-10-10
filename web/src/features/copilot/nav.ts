/**
 * Copilot → app navigation. Citation chips, action buttons, chart clicks and server view
 * intents all go through `useAppActions` (docs/UI_SYSTEM.md §7), so the copilot moves the app
 * exactly like the rest of the UI. Only IDs the server returned are used.
 */
import { useCallback, useMemo } from "react";
import { useNavigate } from "react-router";
import { useAppActions } from "@/app/actions";
import { SCREENS, useSelection, type Screen } from "@/app/selection";
import type { ActionKind, ViewIntent } from "./types";

export type RefKind = "run" | "field" | "evidence" | "comparison" | "analysis" | "report" | "revision" | "job" | "instance" | "other";

/** Normalise a citation / created-ref / column kind into something the app can open. */
export function refKind(kind: string | null | undefined, id: string): RefKind {
  const k = (kind ?? "").toLowerCase();
  if (k === "run" || id.startsWith("run_")) return "run";
  if (k === "field" || /:field-\d+/.test(id)) return "field";
  if (k === "comparison" || id.startsWith("cmp_")) return "comparison";
  if (k === "analysis" || id.startsWith("ana_")) return "analysis";
  if (k === "report" || id.startsWith("rpt_")) return "report";
  if (k === "branch" || k === "scenario_revision" || k === "revision" || id.startsWith("rev_")) return "revision";
  if (k === "job" || id.startsWith("job_")) return "job";
  if (k === "instance") return "instance";
  if (k.includes("evidence") || /^(ev|asm|metric|src):/.test(id)) return "evidence";
  return "other";
}

export function actionRef(a: ActionKind): RefKind {
  const m: Record<ActionKind, RefKind> = {
    open_run: "run",
    open_branch: "revision",
    open_field: "field",
    open_report: "report",
    open_analysis: "analysis",
    open_comparison: "comparison",
  };
  return m[a];
}

export interface CopilotNav {
  /** Open an entity; returns a short description of what happened, or null when the UI has no view for it. */
  open: (kind: RefKind, id: string, extra?: { runIds?: string[] }) => string | null;
  applyIntent: (i: ViewIntent) => { applied: boolean; label: string };
  showFields: (ids: string[]) => void;
  clearHighlight: () => void;
}

export function useCopilotNav(): CopilotNav {
  const actions = useAppActions();
  const sel = useSelection();
  const navigate = useNavigate();

  const showFields = useCallback(
    (ids: string[]) => {
      actions.highlightFields(ids);
      if (sel.screen !== "workspace") actions.openScreen("workspace");
    },
    [actions, sel.screen],
  );

  const open = useCallback(
    (kind: RefKind, id: string, extra?: { runIds?: string[] }): string | null => {
      switch (kind) {
        case "run":
          actions.openRun(id);
          return "Opened the run";
        case "field":
          actions.selectField(id);
          actions.highlightFields([id]);
          return "Selected the field on the map";
        case "evidence":
          actions.openScreen("evidence", { ev: id });
          return "Opened the source";
        case "analysis":
          actions.openAnalysis(id);
          return "Opened the analysis";
        case "comparison":
          actions.openScreen("compare", extra?.runIds?.length ? { runs: extra.runIds.join(","), run: extra.runIds[extra.runIds.length - 1] } : {});
          return "Opened Compare";
        case "report":
          actions.openScreen("report");
          return "Opened the report";
        default:
          return null;
      }
    },
    [actions],
  );

  const applyIntent = useCallback(
    (i: ViewIntent): { applied: boolean; label: string } => {
      switch (i.target) {
        case "run":
          if (!i.run_id) return { applied: false, label: "No run given" };
          if (i.tab && SCREENS.includes(i.tab as Screen)) actions.openRun(i.run_id, i.tab as Screen);
          else actions.openRun(i.run_id);
          return { applied: true, label: "Opened the run" };
        case "field":
          if (!i.field_id) return { applied: false, label: "No field given" };
          actions.selectField(i.field_id);
          actions.highlightFields([i.field_id]);
          return { applied: true, label: "Selected the field" };
        case "date":
          if (!i.date) return { applied: false, label: "No date given" };
          actions.setDate(i.date);
          return { applied: true, label: `Moved the timeline to ${i.date}` };
        case "tab":
          if (i.tab && SCREENS.includes(i.tab as Screen)) {
            actions.openScreen(i.tab as Screen);
            return { applied: true, label: `Opened ${i.tab}` };
          }
          if (i.tab === "onboarding") {
            navigate("/onboarding");
            return { applied: true, label: "Opened “Add a new region”" };
          }
          return { applied: false, label: `No ${i.tab ?? "unknown"} view` };
        case "analysis":
          if (!i.analysis_id) return { applied: false, label: "No analysis given" };
          actions.openAnalysis(i.analysis_id);
          return { applied: true, label: "Opened the analysis" };
        case "comparison":
          actions.openScreen("compare");
          return { applied: true, label: "Opened Compare" };
        case "report":
          actions.openScreen("report");
          return { applied: true, label: "Opened the report" };
        case "pilot":
          return { applied: false, label: `Switch to ${i.pilot_id ?? "that watercourse"} from the top bar; the next question will use it` };
        case "branch":
          return { applied: false, label: "The new scenario is saved; open its run from the answer" };
        default:
          return { applied: false, label: "Unsupported view" };
      }
    },
    [actions, navigate],
  );

  return useMemo(() => ({ open, applyIntent, showFields, clearHighlight: () => actions.highlightFields(null) }), [open, applyIntent, showFields, actions]);
}
