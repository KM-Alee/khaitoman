/**
 * Top bar (PRD §4.2 persistent context, docs/UI_SYSTEM.md › Shell): brand, pilot + season
 * switcher, the five-step journey, and the global actions: guided tour, "Ask AabFlow"
 * (assistant slot), a contextual primary action and a settings menu.
 */
import { useState } from "react";
import { NavLink, useNavigate } from "react-router";
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
  MoreHorizontal,
  PlayCircle,
  PlusCircle,
  Presentation,
  Sparkles,
  SlidersHorizontal,
  Sun,
  Wand2,
  Wifi,
  WifiOff,
  Zap,
} from "lucide-react";
import { usePilotData } from "@/app/pilotData";
import { useUI } from "@/app/store";
import { useHealth } from "@/lib/api/queries";
import { formatDate, titleCase } from "@/lib/formatting";
import { Button, IconButton } from "@/components/ui/Button";
import { Dialog, DialogContent, Tooltip } from "@/components/ui/primitives";
import { AiStackStrip } from "./AiStackStrip";
import { Wordmark, BrandMark } from "@/components/ui/Art";
import { useScenario } from "@/features/workspace/useScenario";
import { useRunContext } from "@/features/workspace/useRunContext";
import { useTour } from "@/features/tour/store";
import { cn } from "@/lib/cn";
import { BACKEND_ORIGIN } from "@/lib/api/urls";
import { JourneyNav } from "./NavigationRail";

export function ConnectionState({ compact }: { compact?: boolean }) {
  const health = useHealth();
  const ok = health.data?.status === "ok";
  const location = BACKEND_ORIGIN ? "Backend" : "Local";
  const label = health.isLoading ? "Connecting" : ok ? `${location} API online` : `${location} API unreachable`;
  return (
    <Tooltip content={health.data ? `${label} · contract ${health.data.contract_version} · schema ${health.data.schema_version ?? "—"}` : label}>
      <span
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-full px-2 text-[12px] font-medium",
          ok ? "text-vegetation" : health.isLoading ? "text-ink-tertiary" : "bg-danger-soft text-danger",
        )}
        role="status"
        aria-label={label}
        data-testid="connection-state"
      >
        {ok || health.isLoading ? <Wifi size={14} aria-hidden /> : <WifiOff size={14} aria-hidden />}
        {compact ? null : <span>{ok ? location : health.isLoading ? "…" : "Offline"}</span>}
      </span>
    </Tooltip>
  );
}

/** Pilot + season switcher: which watercourse and which crop season you are looking at. */
function PilotSwitcher({ compact }: { compact?: boolean }) {
  const { sel, pilots, pilot } = usePilotData();
  const scenario = useScenario();
  const navigate = useNavigate();
  // The season of the result on screen (a saved or shared run may differ from the draft).
  const shown = useRunContext(sel.runId);
  const season = scenario.catalog.seasons.data?.find((s) => s.season_id === (shown.request?.season_id ?? scenario.draft?.season_id));
  const p = pilot.data?.pilot;
  const pilotList = pilots.data ?? [];
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="group flex min-w-0 items-center gap-2 rounded-[12px] px-2 py-1 text-left transition-colors hover:bg-surface-muted"
          aria-label={`Pilot: ${p?.name ?? sel.pilotId ?? "none"}. Change pilot`}
          data-testid="pilot-switcher"
        >
          <div className="min-w-0">
            <div className="truncate text-[14px] font-semibold leading-tight tracking-[-0.01em] text-ink present-lg">{shortPilotName(p?.name ?? sel.pilotId ?? "")}</div>
            {!compact ? (
              <div className="truncate text-[11.5px] leading-tight text-ink-tertiary">
                {season ? `${titleCase(season.crop)} · ${season.label ?? season.season_id}` : sel.version}
              </div>
            ) : null}
          </div>
          <ChevronDown size={14} className="shrink-0 text-ink-tertiary transition-transform group-data-[state=open]:rotate-180" aria-hidden />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content sideOffset={6} align="start" className="z-[70] min-w-[300px] animate-pop rounded-[16px] border border-border bg-surface-raised p-1.5 shadow-3">
          <DropdownMenu.Label className="eyebrow px-2.5 py-1.5">Watercourses</DropdownMenu.Label>
          {pilotList.map((x) => (
            <DropdownMenu.Item
              key={`${x.pilot_id}@${x.pilot_version}`}
              onSelect={() => navigate(`/p/${encodeURIComponent(x.pilot_id)}/${encodeURIComponent(x.pilot_version)}/${sel.screen}`)}
              className="flex cursor-pointer items-center justify-between gap-3 rounded-[10px] px-2.5 py-2 text-[13px] text-ink outline-none data-[highlighted]:bg-surface-muted"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{x.name}</span>
                <span className="block text-[11.5px] text-ink-tertiary">
                  {x.field_count ?? "—"} fields · {x.pilot_version}
                </span>
              </span>
              {x.pilot_id === sel.pilotId && x.pilot_version === sel.version ? <Check size={15} aria-hidden className="text-water" /> : null}
            </DropdownMenu.Item>
          ))}
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item
            onSelect={() => navigate("/onboarding")}
            className="flex cursor-pointer items-center gap-2 rounded-[10px] px-2.5 py-2 text-[13px] font-medium text-water-deep outline-none data-[highlighted]:bg-surface-muted"
          >
            <PlusCircle size={15} aria-hidden /> Add a new region…
          </DropdownMenu.Item>
          {season ? (
            <p className="px-2.5 pb-1.5 pt-1 text-[11.5px] text-ink-tertiary">
              Season {formatDate(season.start)} – {formatDate(season.end)}. Change crop and season in Plan settings.
            </p>
          ) : null}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function shortPilotName(name: string) {
  return name.replace(/\brepresentative\s+/i, "");
}

/** The contextual next action (PRD §4.2): Review inputs → Run plan → Compare → Export. */
function usePrimaryCta(onOpenScenario?: () => void) {
  const { sel } = usePilotData();
  const scenario = useScenario();
  const onLater = sel.screen === "compare" || sel.screen === "replay" || sel.screen === "explore" || sel.screen === "impact" || sel.screen === "report" || sel.screen === "evidence";
  if (scenario.phase === "loading" || scenario.phase === "unavailable")
    return { label: "Review inputs", icon: <SlidersHorizontal size={15} />, onClick: () => { sel.go("workspace"); onOpenScenario?.(); }, testid: "cta-review" };
  if (scenario.phase === "running") return { label: "Finding the best plan…", icon: null, onClick: () => {}, disabled: true, busy: true, testid: "cta-running" };
  if (!sel.runId || ((scenario.phase === "draft" || scenario.phase === "dirty") && sel.screen === "workspace"))
    return { label: scenario.phase === "dirty" ? "Run again" : "Find the best plan", icon: <Zap size={15} />, onClick: () => void scenario.run(), busy: scenario.busy, testid: "cta-run" };
  if (!onLater) return { label: "Compare results", icon: <GitCompareArrows size={15} />, onClick: () => sel.go("compare"), testid: "cta-compare", trailing: <ArrowRight size={14} /> };
  return { label: "Action plan", icon: <FileDown size={15} />, onClick: () => sel.go("report"), testid: "cta-export" };
}

export function TopBar({ compact, onOpenScenario }: { compact?: boolean; onOpenScenario?: () => void }) {
  const set = useUI((s) => s.set);
  const assistantOpen = useUI((s) => s.assistantOpen);
  const tourSeen = useUI((s) => s.tourSeen);
  const startTour = useTour((s) => s.start);
  const cta = usePrimaryCta(onOpenScenario);
  return (
    <header className="no-print relative z-30 flex h-[var(--header-h)] shrink-0 items-center gap-2 border-b border-border bg-surface/92 px-3 backdrop-blur md:gap-3 md:px-4" data-testid="context-bar">
      <NavLink to="/" aria-label="AabFlow home" className="shrink-0 rounded-[10px]">
        {compact ? <BrandMark className="h-8 w-8" /> : <Wordmark className="hidden xl:inline-flex" />}
        {!compact ? <BrandMark className="h-8 w-8 xl:hidden" /> : null}
      </NavLink>
      <span className="hidden h-7 w-px shrink-0 bg-border md:block" aria-hidden />
      <PilotSwitcher compact={compact} />

      {!compact ? <JourneyNav className="mx-auto hidden min-w-0 lg:block" compact /> : <span className="flex-1" />}

      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {!compact ? <ConnectionState compact /> : null}
        <Tooltip content="A 3-minute guided walk through a real, saved result">
          <Button
            variant="ghost"
            size="md"
            icon={<PlayCircle size={16} />}
            onClick={() => {
              set({ tourSeen: true });
              startTour(0);
            }}
            className={cn("px-2.5", !tourSeen && "text-water-deep [animation:ring-pulse_2.2s_ease-out_3]")}
            data-testid="start-tour"
            aria-label="Take the guided tour"
          >
            <span className="hidden 2xl:inline">Tour</span>
          </Button>
        </Tooltip>
        <Button
          variant={assistantOpen ? "subtle" : "secondary"}
          size="md"
          icon={<Sparkles size={15} className="text-water" />}
          onClick={() => set({ assistantOpen: !assistantOpen })}
          aria-pressed={assistantOpen}
          data-testid="ask-aabflow"
          data-tour="ask"
          className={compact ? "px-2.5" : ""}
          aria-label={compact ? "Ask AabFlow" : undefined}
        >
          {compact ? null : <span className="hidden lg:inline">Ask AabFlow</span>}
          {compact ? null : <span className="lg:hidden">Ask</span>}
        </Button>
        {!compact ? (
          <Button
            variant="primary"
            size="md"
            icon={cta.icon}
            busy={cta.busy}
            disabled={cta.disabled}
            onClick={cta.onClick}
            trailing={cta.trailing}
            data-testid="primary-cta"
            data-cta={cta.testid}
            className="present-lg hidden md:inline-flex"
          >
            {cta.label}
          </Button>
        ) : null}
        <MoreMenu />
      </div>
    </header>
  );
}

/** @deprecated name kept for imports; the top bar replaced the context bar. */
export const ContextBar = TopBar;

function MoreMenu() {
  const set = useUI((s) => s.set);
  const theme = useUI((s) => s.theme);
  const motion = useUI((s) => s.motion);
  const presentation = useUI((s) => s.presentation);
  const navigate = useNavigate();
  const [aiOpen, setAiOpen] = useState(false);
  const item = "flex cursor-pointer items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-[13px] text-ink outline-none data-[highlighted]:bg-surface-muted";
  return (
    <>
    <Dialog open={aiOpen} onOpenChange={setAiOpen}>
      <DialogContent title="How the AI works" description="Four engines, each with a fact read from stored evidence. Pick one to see its proof." wide>
        <AiStackStrip className="sm:grid-cols-2 lg:grid-cols-2" onPick={() => setAiOpen(false)} />
      </DialogContent>
    </Dialog>
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <IconButton label="More: theme, motion, presentation, commands">
          <MoreHorizontal size={18} />
        </IconButton>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content sideOffset={6} align="end" className="z-[70] min-w-[240px] animate-pop rounded-[16px] border border-border bg-surface-raised p-1.5 shadow-3">
          <DropdownMenu.Item className={item} onSelect={() => setAiOpen(true)} data-testid="menu-ai-stack">
            <Sparkles size={15} aria-hidden /> How the AI works
          </DropdownMenu.Item>
          <DropdownMenu.Item className={item} onSelect={() => set({ commandOpen: true })}>
            <Command size={15} aria-hidden /> Jump to… <span className="ml-auto text-[11px] text-ink-tertiary">Ctrl K</span>
          </DropdownMenu.Item>
          <DropdownMenu.Item className={item} onSelect={() => navigate("/onboarding")}>
            <PlusCircle size={15} aria-hidden /> Add a new region
          </DropdownMenu.Item>
          <DropdownMenu.Item className={item} onSelect={() => set({ presentation: !presentation })}>
            <Presentation size={15} aria-hidden /> {presentation ? "Exit presentation mode" : "Presentation mode"}
            <span className="ml-auto text-[11px] text-ink-tertiary">⇧P</span>
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Label className="eyebrow px-2.5 py-1">Theme</DropdownMenu.Label>
          {(
            [
              { v: "system", label: "Match my device", icon: <Monitor size={15} /> },
              { v: "light", label: "Light", icon: <Sun size={15} /> },
              { v: "dark", label: "Dark", icon: <Moon size={15} /> },
            ] as const
          ).map((o) => (
            <DropdownMenu.Item key={o.v} className={item} onSelect={() => set({ theme: o.v })}>
              {o.icon}
              {o.label}
              {theme === o.v ? <Check size={15} className="ml-auto text-water" aria-hidden /> : null}
            </DropdownMenu.Item>
          ))}
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item className={item} onSelect={() => set({ motion: motion === "reduced" ? "system" : "reduced" })}>
            <Wand2 size={15} aria-hidden /> {motion === "reduced" ? "Allow animation" : "Reduce motion"}
            {motion === "reduced" ? <Check size={15} className="ml-auto text-water" aria-hidden /> : null}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
    </>
  );
}
