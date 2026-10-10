/**
 * Copilot region (F19 is implemented last, M7). Until the API reports the capability as
 * available, this panel states the truth from /capabilities and points to the deterministic
 * tools that already work. It never shows a scripted conversation.
 */
import { Bot, Compass, FileText, GitCompareArrows, Telescope, WifiOff } from "lucide-react";
import { useCapabilities } from "@/lib/api/queries";
import { useSelection } from "@/app/selection";
import { Chip, Skeleton, StatePanel } from "@/components/status";
import { Eyebrow } from "@/components/ui/primitives";
import { shortId } from "@/lib/formatting";

export function copilotAvailability(caps: ReturnType<typeof useCapabilities>["data"]): {
  available: boolean;
  label: string;
  reason: string;
} {
  if (!caps) return { available: false, label: "Unknown", reason: "Capabilities could not be read from the local API." };
  const feat = (caps.features as Record<string, unknown> | undefined)?.copilot ?? (caps.features as Record<string, unknown> | undefined)?.F19;
  const status = typeof feat === "string" ? feat : (feat as { status?: string } | undefined)?.status;
  const reasons = caps.feature_reasons as Record<string, string> | undefined;
  const reason =
    (feat as { reason?: string } | undefined)?.reason ?? reasons?.copilot ?? reasons?.F19 ?? caps.chat?.reason ?? null;
  if (status === "available" && caps.chat?.available !== false)
    return { available: true, label: "Available", reason: reason ?? "Hosted conversation connected." };
  if (caps.chat && caps.chat.key_configured === false)
    return { available: false, label: "Not configured", reason: reason ?? "No provider key is configured on this machine." };
  return {
    available: false,
    label: status ? status.replace(/_/g, " ") : "Not yet available",
    reason: reason ?? "The conversational copilot is the last feature in the build order (M7) and is not implemented in this build yet.",
  };
}

export function CopilotPanel() {
  const caps = useCapabilities();
  const sel = useSelection();
  const a = copilotAvailability(caps.data);
  return (
    <div className="flex h-full flex-col" data-testid="copilot-panel">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Bot size={16} className="text-water" aria-hidden />
          <h2 className="text-[13px] font-semibold text-ink">Copilot</h2>
        </div>
        <Chip size="sm" tone={a.available ? "vegetation" : "neutral"} icon={a.available ? undefined : <WifiOff size={11} aria-hidden />}>
          {caps.isLoading ? "Checking" : a.label}
        </Chip>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-4 py-2 text-[11px] text-ink-secondary">
        Context: <Chip size="sm">{sel.pilotId ?? "no pilot"}</Chip>
        {sel.runId ? <Chip size="sm">run {shortId(sel.runId)}</Chip> : null}
        {sel.fieldId ? <Chip size="sm">{sel.fieldId}</Chip> : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {caps.isLoading ? (
          <Skeleton className="h-24" />
        ) : a.available ? (
          <StatePanel state="empty" title="Copilot connected">
            The conversation interface is delivered with milestone M7. This build reports the capability as available, but this panel has not been wired to
            <code className="mx-1 font-mono">/copilot/sessions</code> yet.
          </StatePanel>
        ) : (
          <StatePanel state="blocked" title="Hosted conversation is not available">
            {a.reason}
          </StatePanel>
        )}
        <Eyebrow className="mb-2 mt-5">Available without the copilot</Eyebrow>
        <ul className="flex flex-col gap-1.5 text-[13px]">
          {[
            { icon: <Compass size={14} />, label: "Explain the selected field", to: () => sel.go("workspace") },
            { icon: <GitCompareArrows size={14} />, label: "Compare B0 · B1 · P", to: () => sel.go("compare") },
            { icon: <Telescope size={14} />, label: "Why-not, frontier and stress tests", to: () => sel.go("explore") },
            { icon: <FileText size={14} />, label: "Action plan and report", to: () => sel.go("report") },
          ].map((x) => (
            <li key={x.label}>
              <button type="button" onClick={x.to} className="flex w-full items-center gap-2 rounded-[10px] border border-border px-3 py-2 text-left text-ink hover:bg-surface-muted">
                <span className="text-water" aria-hidden>
                  {x.icon}
                </span>
                {x.label}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="border-t border-border p-3">
        <label htmlFor="copilot-input" className="sr-only">
          Message
        </label>
        <textarea
          id="copilot-input"
          disabled
          rows={2}
          placeholder={a.available ? "Copilot input arrives with M7" : "Unavailable — see status above"}
          className="w-full resize-none rounded-[10px] border border-border bg-surface-muted px-3 py-2 text-[13px] text-ink-secondary"
        />
      </div>
    </div>
  );
}
