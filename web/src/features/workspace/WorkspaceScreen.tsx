import { useMemo } from "react";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { useRun } from "@/lib/api/queries";
import { MapSlot } from "@/components/map/MapSlot";
import { ReviewFlagChips } from "@/components/status";
import { ResultBar, ResultStrip, type ResultState } from "./ResultStrip";
import { useScenario } from "./useScenario";
import { useShell } from "@/components/layout/AppShell";
import { formatDate } from "@/lib/formatting";
import { HD_IMAGERY_ATTRIBUTION, useHdStatus } from "@/components/map/hdImagery";

export function WorkspaceScreen() {
  const { sel, pilot, map } = usePilotData();
  const s = useScenario();
  const run = useRun(sel.runId);
  const { mobile } = useShell();
  const metric = useUI((st) => st.mapMetric);
  const runs = s.revisionRuns;
  const baselineRunId = sel.compareRunIds.find((id) => id !== sel.runId && (id === runs.B0 || id === runs.B1)) ?? runs.B1 ?? runs.B0 ?? sel.compareRunIds[0] ?? null;

  const state: ResultState = useMemo(() => {
    if (!sel.runId) return "none";
    if (s.phase === "dirty") return "draft";
    const runRev = run.data?.scenario_revision_id;
    if (runRev && s.active && runRev !== s.active.revisionId) return "stale";
    return "current";
  }, [sel.runId, s.phase, run.data, s.active]);

  const im = map.data?.imagery[0];
  const showImagery = useUI((s) => s.showImagery);
  const showHd = useUI((s) => s.showHdImagery);
  const hd = useHdStatus();
  const hdOn = hd === "ok" && showImagery && showHd;
  return (
    <div className="relative flex min-h-0 flex-1 flex-col" data-testid="workspace">
      <MapSlot
        runId={sel.runId}
        baselineRunId={metric === "change" ? baselineRunId : null}
        className={mobile ? "h-[56vh] shrink-0" : "min-h-0 flex-1"}
        label="Pilot map: fields, canals and assets"
      >
        {!mobile ? (
          <div className="pointer-events-none absolute inset-x-0 top-14 z-10 flex justify-center px-16">
            <div className="pointer-events-auto max-w-[720px]">
              <ResultBar state={state} runId={sel.runId} revisionId={s.active?.revisionId ?? null} onRun={() => void s.run()} />
            </div>
          </div>
        ) : null}
        <div className="pointer-events-none absolute bottom-3 right-3 z-10 hidden max-w-[48%] flex-col items-end gap-1 text-right lg:flex present-hide">
          <div className="pointer-events-auto rounded-[10px] bg-surface/90 px-2.5 py-1.5 text-[11px] text-ink-secondary shadow-1 backdrop-blur">
            {im ? (
              <>
                {hdOn ? <>{HD_IMAGERY_ATTRIBUTION} · analysis: </> : null}
                Sentinel-2 L2A · {formatDate(im.acquiredAt)} · {im.resolutionM ?? 10} m{hdOn ? "" : " · display-sharpened"}
              </>
            ) : (
              "No imagery"
            )}
          </div>
        </div>
      </MapSlot>
      <div className={mobile ? "flex flex-col gap-3 p-3" : "shrink-0 border-t border-border bg-canvas px-3 py-3"}>
        {mobile ? <ResultBar state={state} runId={sel.runId} revisionId={s.active?.revisionId ?? null} onRun={() => void s.run()} /> : null}
        <ResultStrip runId={sel.runId} baselineRunId={baselineRunId} className="shadow-1" />
      </div>
      {mobile ? (
        <div className="px-3 pb-4">
          <ReviewFlagChips flags={pilot.data?.pilot?.review_flags} />
        </div>
      ) : null}
    </div>
  );
}
