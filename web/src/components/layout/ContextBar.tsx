import { useNavigate } from "react-router";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Command,
  FileDown,
  GitCompareArrows,
  Monitor,
  Moon,
  Play,
  Presentation,
  SlidersHorizontal,
  Sun,
  Wifi,
  WifiOff,
} from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { useHealth } from "@/lib/api/queries";
import { formatDate, shortId, titleCase } from "@/lib/formatting";
import { Button, IconButton } from "@/components/ui/Button";
import { Chip } from "@/components/status";
import { Tooltip } from "@/components/ui/primitives";
import { useScenario } from "@/features/workspace/useScenario";
import { cn } from "@/lib/cn";
import { BrandMark } from "./NavigationRail";

export function ConnectionState({ compact }: { compact?: boolean }) {
  const health = useHealth();
  const ok = health.data?.status === "ok";
  const label = health.isLoading ? "Connecting" : ok ? "Local API online" : "Local API unreachable";
  return (
    <Tooltip content={health.data ? `Contract ${health.data.contract_version} · schema ${health.data.schema_version ?? "—"}` : label}>
      <span
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium",
          ok ? "text-vegetation" : health.isLoading ? "text-ink-tertiary" : "bg-danger-soft text-danger",
        )}
        role="status"
        aria-label={label}
        data-testid="connection-state"
      >
        {ok || health.isLoading ? <Wifi size={14} aria-hidden /> : <WifiOff size={14} aria-hidden />}
        {compact ? null : <span>{ok ? "Local" : health.isLoading ? "…" : "Offline"}</span>}
      </span>
    </Tooltip>
  );
}

export function ContextBar({ compact, onOpenScenario }: { compact?: boolean; onOpenScenario?: () => void }) {
  const { sel, pilots, pilot } = usePilotData();
  const scenario = useScenario();
  const navigate = useNavigate();
  const set = useUI((s) => s.set);
  const presentation = useUI((s) => s.presentation);
  const theme = useUI((s) => s.theme);
  const season = scenario.catalog.seasons.data?.find((s) => s.season_id === scenario.draft?.season_id);
  const p = pilot.data?.pilot;
  const pilotList = pilots.data ?? [];

  // Primary call to action follows state (PRD §4.2)
  let cta: { label: string; icon: React.ReactNode; onClick: () => void; disabled?: boolean; busy?: boolean; testid: string };
  const onCompare = sel.screen === "compare" || sel.screen === "replay" || sel.screen === "explore" || sel.screen === "impact";
  if (scenario.phase === "loading" || scenario.phase === "unavailable") {
    cta = { label: "Review inputs", icon: <SlidersHorizontal size={16} />, onClick: () => { sel.go("workspace"); onOpenScenario?.(); }, testid: "cta-review" };
  } else if (scenario.phase === "running") {
    cta = { label: "Running plan", icon: null, onClick: () => {}, disabled: true, busy: true, testid: "cta-running" };
  } else if (scenario.phase === "draft" || scenario.phase === "dirty" || !sel.runId) {
    cta = { label: scenario.phase === "dirty" ? "Run again" : "Run plan", icon: <Play size={15} />, onClick: () => void scenario.run(), busy: scenario.busy, testid: "cta-run" };
  } else if (!onCompare) {
    cta = { label: "Compare results", icon: <GitCompareArrows size={16} />, onClick: () => sel.go("compare"), testid: "cta-compare" };
  } else {
    cta = { label: "Export action plan", icon: <FileDown size={16} />, onClick: () => sel.go("report"), testid: "cta-export" };
  }

  return (
    <header
      className="no-print flex h-[var(--header-h)] shrink-0 items-center gap-3 border-b border-border bg-surface/90 px-3 backdrop-blur md:px-4"
      data-testid="context-bar"
    >
      {compact ? <BrandMark className="h-8 w-8 shrink-0" /> : null}
      {/* Pilot selector */}
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            className="group flex min-w-0 items-center gap-2 rounded-[10px] px-2 py-1 text-left hover:bg-surface-muted"
            aria-label={`Pilot: ${p?.name ?? sel.pilotId ?? "none"}. Change pilot`}
            data-testid="pilot-switcher"
          >
            <div className="min-w-0">
              <div className="truncate text-[11px] font-medium uppercase tracking-[0.06em] text-ink-tertiary">Pilot · {sel.version}</div>
              <div className="truncate text-[15px] font-semibold leading-tight tracking-[-0.01em] text-ink present-lg">{p?.name ?? sel.pilotId}</div>
            </div>
            <ChevronDown size={14} className="shrink-0 text-ink-tertiary" aria-hidden />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content sideOffset={6} align="start" className="z-[70] min-w-[260px] rounded-[12px] border border-border bg-surface p-1 shadow-3">
            <DropdownMenu.Label className="px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-tertiary">Published pilots</DropdownMenu.Label>
            {pilotList.map((x) => (
              <DropdownMenu.Item
                key={`${x.pilot_id}@${x.pilot_version}`}
                onSelect={() => navigate(`/p/${encodeURIComponent(x.pilot_id)}/${encodeURIComponent(x.pilot_version)}/${sel.screen}`)}
                className="flex cursor-pointer items-center justify-between gap-3 rounded-[8px] px-2.5 py-2 text-[13px] text-ink outline-none data-[highlighted]:bg-surface-muted"
              >
                <span>
                  <span className="font-medium">{x.name}</span>
                  <span className="ml-2 text-ink-tertiary">{x.pilot_version}</span>
                </span>
                {x.pilot_id === sel.pilotId && x.pilot_version === sel.version ? <Check size={14} aria-hidden className="text-water" /> : null}
              </DropdownMenu.Item>
            ))}
            <DropdownMenu.Separator className="my-1 h-px bg-border" />
            <DropdownMenu.Item
              onSelect={() => navigate("/onboarding")}
              className="cursor-pointer rounded-[8px] px-2.5 py-2 text-[13px] font-medium text-water outline-none data-[highlighted]:bg-surface-muted"
            >
              Add region…
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>

      {!compact ? (
        <div className="hidden min-w-0 items-center gap-1.5 lg:flex" aria-label="Scenario context">
          <span className="h-6 w-px bg-border" aria-hidden />
          {season ? (
            <Chip tone="vegetation" title={`${season.season_id}: ${formatDate(season.start)} – ${formatDate(season.end)}`}>
              {titleCase(season.crop)} · {season.label ?? season.season_id.replace(/^(wheat|cotton)-/, "")}
            </Chip>
          ) : null}
          {scenario.draft ? <Chip tone="info">{titleCase(scenario.draft.planning_mode)}</Chip> : null}
          <RevisionChip phase={scenario.phase} revisionId={scenario.active?.revisionId ?? null} />
          {sel.runId ? (
            <Chip tone="ink" title={`Displayed run ${sel.runId}`}>
              Run {shortId(sel.runId)}
            </Chip>
          ) : null}
        </div>
      ) : null}

      <div className="ml-auto flex items-center gap-1.5">
        <ConnectionState compact={compact} />
        {!compact ? (
          <>
            <Tooltip content="Command menu · Ctrl K">
              <IconButton label="Open command menu" onClick={() => set({ commandOpen: true })}>
                <Command size={17} />
              </IconButton>
            </Tooltip>
            <ThemeMenu theme={theme} onChange={(t) => set({ theme: t })} />
            <Tooltip content={presentation ? "Exit presentation mode" : "Presentation mode"}>
              <IconButton label={presentation ? "Exit presentation mode" : "Enter presentation mode"} pressed={presentation} onClick={() => set({ presentation: !presentation })}>
                <Presentation size={17} />
              </IconButton>
            </Tooltip>
          </>
        ) : null}
        <Button
          variant="primary"
          size={compact ? "sm" : "md"}
          icon={cta.icon}
          busy={cta.busy}
          disabled={cta.disabled}
          onClick={cta.onClick}
          trailing={cta.testid === "cta-compare" ? <ArrowRight size={14} /> : undefined}
          data-testid="primary-cta"
          data-cta={cta.testid}
          className="present-lg"
        >
          {cta.label}
        </Button>
      </div>
    </header>
  );
}

function RevisionChip({ phase, revisionId }: { phase: string; revisionId: string | null }) {
  if (phase === "dirty")
    return (
      <Chip tone="warning" title="Inputs differ from the last run revision">
        Draft · inputs changed
      </Chip>
    );
  if (phase === "draft") return <Chip tone="neutral">Draft · not yet run</Chip>;
  if (phase === "running") return <Chip tone="water">Revision {shortId(revisionId)} · solving</Chip>;
  if (revisionId) return <Chip tone="info" title={revisionId}>Revision {shortId(revisionId)}</Chip>;
  return null;
}

function ThemeMenu({ theme, onChange }: { theme: string; onChange: (t: "system" | "light" | "dark") => void }) {
  const opts = [
    { v: "system" as const, label: "System", icon: <Monitor size={14} /> },
    { v: "light" as const, label: "Light", icon: <Sun size={14} /> },
    { v: "dark" as const, label: "Dark", icon: <Moon size={14} /> },
  ];
  const cur = opts.find((o) => o.v === theme) ?? opts[0];
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <IconButton label={`Theme: ${cur.label}`}>{theme === "dark" ? <Moon size={17} /> : theme === "light" ? <Sun size={17} /> : <Monitor size={17} />}</IconButton>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content sideOffset={6} align="end" className="z-[70] min-w-[160px] rounded-[12px] border border-border bg-surface p-1 shadow-3">
          {opts.map((o) => (
            <DropdownMenu.Item
              key={o.v}
              onSelect={() => onChange(o.v)}
              className="flex cursor-pointer items-center gap-2 rounded-[8px] px-2.5 py-2 text-[13px] text-ink outline-none data-[highlighted]:bg-surface-muted"
            >
              {o.icon}
              {o.label}
              {o.v === theme ? <Check size={14} className="ml-auto text-water" aria-hidden /> : null}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
