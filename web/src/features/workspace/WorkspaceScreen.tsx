/**
 * Plan (Workspace): the watercourse on real imagery with AI-drawn, reviewed field
 * boundaries. Settings on the left, the answer on the right (ResultPanel in the inspector);
 * on phones the answer follows the map.
 */
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { journeyFor } from "@/app/journey";
import { MapSlot, MetricSwitcher } from "@/components/map/MapSlot";
import { ReviewFlagChips } from "@/components/status";
import { useShell } from "@/components/layout/AppShell";
import { formatDate } from "@/lib/formatting";
import { HD_IMAGERY_ATTRIBUTION, useHdStatus } from "@/components/map/hdImagery";
import { Term } from "@/components/ui/Term";
import { useLadderRuns } from "@/features/compare/useLadder";
import { ResultPanel } from "./ResultPanel";

export function WorkspaceScreen() {
  const { sel, pilot, map, fieldIndex } = usePilotData();
  const { mobile, tablet } = useShell();
  const metric = useUI((st) => st.mapMetric);
  const highlight = useUI((st) => st.assistantHighlight);
  const scenarioOpen = useUI((st) => st.scenarioOpen);
  const presentation = useUI((st) => st.presentation);
  const { byKind } = useLadderRuns();
  const baselineRunId = [byKind.get("B0")?.run_id, byKind.get("B1")?.run_id].find((id) => id && id !== sel.runId) ?? null;

  const im = map.data?.imagery[0];
  const showImagery = useUI((s) => s.showImagery);
  const showHd = useUI((s) => s.showHdImagery);
  const hd = useHdStatus();
  const hdOn = hd === "ok" && showImagery && showHd;
  const j = journeyFor("workspace");
  const settingsHidden = !mobile && !tablet && (!scenarioOpen || presentation);
  return (
    <div className={`relative flex min-h-0 flex-1 flex-col ${mobile ? "overflow-y-auto" : ""}`} data-testid="workspace">
      <MapSlot
        runId={sel.runId}
        baselineRunId={metric === "change" ? baselineRunId : null}
        className={mobile ? "h-[52vh] shrink-0" : "min-h-0 flex-1"}
        label="Map of the watercourse: fields, canals and works"
        highlightFieldIds={highlight}
        ownMetricSwitcher={!mobile}
      >
        {!mobile ? (
          <div className={`pointer-events-none absolute top-3 z-10 max-w-[min(560px,52%)] ${settingsHidden ? "left-40" : "left-3"} present-hide`} data-tour="map-intro">
            <div className="glass pointer-events-auto rounded-[16px] border border-border/70 px-4 py-3 shadow-2">
              <div className="eyebrow flex items-center gap-2">
                <span className="num grid h-5 w-5 place-items-center rounded-full bg-water text-[10.5px] font-bold tracking-normal text-on-water">{j.step}</span>
                {pilot.data?.pilot?.name ?? sel.pilotId}
              </div>
              <h1 className="display mt-1 text-[21px] leading-tight text-ink">{j.question}</h1>
              <p className="mt-1 text-[12.5px] leading-snug text-ink-secondary">
                {fieldIndex.size || "—"} fields on real satellite imagery, with <Term id="aiBoundaries">AI-drawn boundaries</Term> checked by a person. Click a field for its water and harvest.
              </p>
              <div className="mt-2.5 flex flex-wrap items-center gap-2" data-tour="map-metric">
                <span className="text-[11.5px] font-medium text-ink-tertiary">Colour fields by</span>
                <MetricSwitcher />
              </div>
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
      {mobile ? (
        <div className="flex flex-col gap-3 pb-4">
          <div className="px-4 pt-4">
            <div className="eyebrow">Step 1 · Plan</div>
            <h1 className="display mt-1 text-[24px] leading-tight text-ink">{j.question}</h1>
          </div>
          <ResultPanel className="pt-0" />
          <div className="px-4">
            <ReviewFlagChips flags={pilot.data?.pilot?.review_flags} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
