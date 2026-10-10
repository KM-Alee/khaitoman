/**
 * Guided tour host (docs/UI_SYSTEM.md › Guided tour). Mounted once at the app root.
 *
 * It drives the real application: each step navigates to an ordinary route carrying saved
 * run/analysis IDs from GET /demo/session, spotlights a real element, and explains it with
 * server numbers. Nothing is locked: the visitor can leave at any step ("Try it yourself",
 * Esc, ×) and keep using every live feature. If the manifest is missing or refers to
 * records this database lacks, the tour says so and how to create it; it never shows a
 * canned result. Keyboard: → next, ← back, Esc exit. Reduced motion: no fly/glide.
 */
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { ArrowLeft, ArrowRight, Compass, History, Map as MapIcon, MessageCircle, Pause, Play, PlusCircle, RefreshCw, Sparkles, Terminal, X } from "lucide-react";
import { useUI } from "@/app/store";
import { BREAKPOINTS, useMediaQuery, useReducedMotion } from "@/app/environment";
import { api, describeError } from "@/lib/api/client";
import { readRevisionView, useAnalysis, usePilots, useRun } from "@/lib/api/queries";
import { formatDateTime, shortId } from "@/lib/formatting";
import { getEngine } from "@/components/map/runtime";
import { Button, IconButton } from "@/components/ui/Button";
import { Stepper } from "@/components/ui/PageHeader";
import { SpotArt } from "@/components/ui/Art";
import { Chip } from "@/components/status";
import { draftFromRequest } from "@/features/workspace/useScenario";
import { cn } from "@/lib/cn";
import { useDemoSession, type DemoSession } from "./api";
import { useTour } from "./store";
import { TOUR_STEPS, type TourCtx } from "./steps";

/** Focus the first visible match of `selector` once it renders (≤ 8 s), scrolling it into view. */
export function focusWhenReady(selector: string, timeout = 8000) {
  const t0 = performance.now();
  const tick = () => {
    const el = [...document.querySelectorAll<HTMLElement>(selector)].find((e) => e.getClientRects().length > 0);
    if (el) {
      el.scrollIntoView({ block: "center", inline: "nearest" });
      if (!el.matches("button,a,input,select,textarea,[tabindex]")) el.setAttribute("tabindex", "-1");
      el.focus({ preventScroll: true });
      return;
    }
    if (performance.now() - t0 < timeout) setTimeout(tick, 120);
  };
  tick();
}

export function TourHost() {
  const active = useTour((s) => s.active);
  return active ? <TourRunner /> : null;
}

function TourRunner() {
  const { step, go, stop, autoplay, setAutoplay, held, setHeld } = useTour();
  const state = useDemoSession(true);
  const navigate = useNavigate();
  const set = useUI((s) => s.set);
  const mobile = useMediaQuery(BREAKPOINTS.mobile);
  const reduced = useReducedMotion();
  const session = state.kind === "ready" ? state.session : null;
  const steps = TOUR_STEPS;
  const i = Math.max(0, Math.min(step, steps.length - 1));
  const cur = steps[i];
  const last = i === steps.length - 1;

  const exit = useCallback(() => {
    set({ assistantHighlight: null });
    stop();
  }, [set, stop]);

  const ctx = useMemo<TourCtx | null>(() => {
    if (!session) return null;
    const pilotKey = `${session.pilot_id}@${session.pilot_version}`;
    const planHref = (runId?: string | null) => `/p/${encodeURIComponent(session.pilot_id)}/${encodeURIComponent(session.pilot_version)}/workspace${runId ? `?run=${encodeURIComponent(runId)}` : ""}`;
    return {
      session,
      exit,
      navigate,
      focus: (selector) => {
        exit();
        focusWhenReady(selector);
      },
      highlight: (ids) => set({ assistantHighlight: ids }),
      setMapMetric: (m) => set({ mapMetric: m }),
      overview: () => setTimeout(() => getEngine()?.fitAOI(!reduced), 500),
      openAssistant: () => {
        exit();
        set({ assistantOpen: true });
      },
      adoptRevision: (revisionId, then = "focus-run") => {
        exit();
        void (async () => {
          try {
            const view = readRevisionView(await api.get<unknown>(`/scenario-revisions/${encodeURIComponent(revisionId)}`));
            const st = useUI.getState();
            st.setDraft(pilotKey, draftFromRequest(view.revision.request));
            st.setActive(pilotKey, null);
            const runId = then === "run" ? null : Object.values(view.runs).find((r) => r.plan_kind === "P")?.run_id ?? null;
            navigate(planHref(runId));
            if (then === "run") set({ pendingRun: true });
            else {
              set({ settingsRequest: useUI.getState().settingsRequest + 1, scenarioOpen: true });
              focusWhenReady(then === "focus-budget" ? '[data-tour="capital-budget"] input' : '[data-testid="run-plan"]');
            }
          } catch (e) {
            const d = describeError(e);
            const { toast } = await import("@/components/ui/Toast");
            toast({ tone: "danger", title: `Could not load those settings: ${d.title}`, description: d.detail });
          }
        })();
      },
    };
  }, [session, exit, navigate, set, reduced]);

  // Navigate to the step's route, then run its entry effect.
  useEffect(() => {
    if (!session || !ctx) return;
    const to = cur.route(session);
    navigate(to);
    const t = setTimeout(() => cur.onEnter?.(ctx), 350);
    return () => clearTimeout(t);
  }, [i, session]); // eslint-disable-line react-hooks/exhaustive-deps

  const next = useCallback(() => (last ? exit() : go(i + 1)), [last, exit, go, i]);
  const back = useCallback(() => go(Math.max(0, i - 1)), [go, i]);

  // Keyboard: → next, ← back, Esc exit (never while typing).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target;
      if (t instanceof Element && t.closest("input,textarea,select,[contenteditable=true]")) return;
      if (e.key === "Escape") {
        e.preventDefault();
        exit();
      } else if (e.key === "ArrowRight" && session) {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft" && session) {
        e.preventDefault();
        back();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [exit, next, back, session]);

  // Autoplay: advance after the step's time unless the card is hovered/focused or the tab is hidden.
  const seconds = cur.seconds ?? 12;
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => setElapsed(0), [i]);
  useEffect(() => {
    if (!autoplay || !session || held || last) return;
    const t = setInterval(() => {
      if (document.hidden) return;
      setElapsed((e) => {
        if (e + 0.1 >= seconds) {
          next();
          return 0;
        }
        return e + 0.1;
      });
    }, 100);
    return () => clearInterval(t);
  }, [autoplay, session, held, last, seconds, next]);

  const target = session && cur.placement !== "center" ? cur.target : undefined;
  const { rect, missing } = useTargetRect(target, `${i}`);

  return (
    <div data-tour-active="" className="no-print">
      <Spotlight rect={session ? rect : null} onBackdrop={() => setAutoplay(false)} />
      {state.kind === "ready" && ctx ? (
        <CoachCard
          key={i}
          rect={cur.placement === "center" ? null : rect}
          mobile={mobile}
          center={cur.placement === "center" || !target}
          waiting={!!target && !rect && !missing}
          onHold={setHeld}
        >
          <CardChrome
            chapter={cur.chapter}
            index={i}
            total={steps.length}
            title={cur.title}
            onClose={exit}
            progress={autoplay && !last ? elapsed / seconds : null}
          >
            {/* Only the story scrolls on short screens; the controls below stay visible. */}
            <div className="-mr-3 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-3" data-testid="tour-body">
            <div className="flex flex-col gap-2.5 text-[14px] leading-relaxed text-ink-secondary">
              <cur.Body s={state.session} />
            </div>
            {cur.saved ? (
              <SavedLabel {...cur.saved(state.session)} />
            ) : cur.placement !== "center" ? (
              <p className="text-[12px] text-ink-tertiary" data-testid="tour-live">
                <span className="rounded-full bg-water-soft px-2 py-0.5 font-medium text-water-deep">Live</span> computed on the server as you watch, not saved
              </p>
            ) : null}
            {missing ? <p className="text-[12px] text-warning">This part of the page did not appear; the step text still applies. Use Next to continue.</p> : null}
            </div>
            {last ? (
              <FinishActions ctx={ctx} />
            ) : (
              <>
                <div className="mt-1 flex shrink-0 items-center gap-2">
                  <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} />} onClick={back} disabled={i === 0} aria-label="Previous step" className="-ml-2 shrink-0">
                    Back
                  </Button>
                  <Stepper compact className="mx-auto min-w-0 flex-1 justify-center overflow-hidden" steps={steps.map((st) => ({ id: st.id, label: st.title }))} current={i} onSelect={go} label="Tour progress" />
                  <Button variant="primary" size="sm" trailing={<ArrowRight size={14} />} onClick={next} data-testid="tour-next" className="shrink-0">
                    Next
                  </Button>
                </div>
                <div className="-mx-5 -mb-5 flex shrink-0 flex-wrap items-center gap-x-1 gap-y-1 rounded-b-[22px] border-t border-border bg-surface-muted/60 px-3 py-2">
                  {cur.tryIt ? (
                    <Button variant="ghost" size="sm" icon={<Sparkles size={14} className="text-water" />} onClick={() => cur.tryIt!.run(ctx)} data-testid="tour-try" className="text-ink" title="Leave the tour and do this yourself">
                      Try it: {cur.tryIt.label}
                    </Button>
                  ) : null}
                  <span className="ml-auto flex items-center">
                    {cur.rerun ? (
                      <Button variant="ghost" size="sm" icon={<RefreshCw size={13} />} onClick={() => ctx.adoptRevision(cur.rerun!(state.session), "run")} data-testid="tour-rerun" title="Solve these same settings again now, as a new live scenario">
                        Re-run live
                      </Button>
                    ) : null}
                    <IconButton label={autoplay ? "Pause auto-play" : "Auto-play the tour"} size="sm" pressed={autoplay} onClick={() => setAutoplay(!autoplay)} data-testid="tour-autoplay">
                      {autoplay ? <Pause size={14} /> : <Play size={14} />}
                    </IconButton>
                  </span>
                </div>
              </>
            )}
          </CardChrome>
        </CoachCard>
      ) : (
        <CoachCard rect={null} mobile={mobile} center onHold={setHeld}>
          <SessionProblem state={state} onClose={exit} />
        </CoachCard>
      )}
      <div className="sr-only" aria-live="polite">
        {session ? `Tour step ${i + 1} of ${steps.length}: ${cur.title}` : state.kind === "loading" ? "Opening the saved session" : "The guided tour cannot start"}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ target tracking */
function useTargetRect(selector: string | undefined, key: string) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    setRect(null);
    setMissing(false);
    if (!selector) return;
    let raf = 0;
    let scrolled = false;
    const t0 = performance.now();
    const loop = () => {
      const el = [...document.querySelectorAll<HTMLElement>(selector)].find((e) => e.getClientRects().length > 0) ?? null;
      if (el) {
        // Give the page a moment to lay out (lazy screens, data) before scrolling to it.
        if (!scrolled && performance.now() - t0 > 250) {
          el.scrollIntoView({ block: "nearest", inline: "nearest" });
          scrolled = true;
        }
        const r = el.getBoundingClientRect();
        setRect((p) => (p && Math.abs(p.x - r.x) < 0.5 && Math.abs(p.y - r.y) < 0.5 && Math.abs(p.width - r.width) < 0.5 && Math.abs(p.height - r.height) < 0.5 ? p : r));
        setMissing(false);
      } else if (performance.now() - t0 > 15000) setMissing(true);
    };
    // 10 Hz is plenty: the spotlight glides between positions with a CSS transition.
    loop();
    raf = window.setInterval(loop, 100);
    const onMove = () => loop();
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    return () => {
      window.clearInterval(raf);
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
  }, [selector, key]);
  return { rect, missing };
}

/* ------------------------------------------------------------------ spotlight */
const PAD = 8;
function Spotlight({ rect, onBackdrop }: { rect: DOMRect | null; onBackdrop: () => void }) {
  const vw = typeof window !== "undefined" ? window.innerWidth : 1920;
  const vh = typeof window !== "undefined" ? window.innerHeight : 1080;
  const r = rect
    ? {
        x: Math.max(4, rect.left - PAD),
        y: Math.max(4, rect.top - PAD),
        w: Math.min(vw - 8, rect.width + PAD * 2),
        h: Math.min(vh - 8, rect.height + PAD * 2),
      }
    : null;
  const box = r ? { left: r.x, top: r.y, width: Math.min(r.w, vw - r.x - 4), height: Math.min(r.h, vh - r.y - 4) } : null;
  const glide = "transition-[left,top,width,height,right,bottom] duration-500 ease-[var(--ease-inout)]";
  const dim = cn("fixed z-[90] bg-[var(--scrim)]", glide);
  // Four plain rectangles dim everything around the hole and pause clicks there; the
  // highlighted element stays usable. (Cheap to composite, unlike a huge box-shadow.)
  return (
    <>
      {box ? (
        <>
          <div className={dim} style={{ left: 0, top: 0, width: vw, height: box.top }} onClick={onBackdrop} aria-hidden />
          <div className={dim} style={{ left: 0, top: box.top + box.height, width: vw, height: Math.max(0, vh - box.top - box.height) }} onClick={onBackdrop} aria-hidden />
          <div className={dim} style={{ left: 0, top: box.top, width: box.left, height: box.height }} onClick={onBackdrop} aria-hidden />
          <div className={dim} style={{ left: box.left + box.width, top: box.top, width: Math.max(0, vw - box.left - box.width), height: box.height }} onClick={onBackdrop} aria-hidden />
          <div
            className={cn("pointer-events-none fixed z-[91] rounded-[10px] ring-2 ring-water-glow", glide)}
            style={{ ...box, boxShadow: "0 0 0 6px color-mix(in srgb, var(--water-glow) 22%, transparent)" }}
            data-testid="tour-spotlight"
            aria-hidden
          />
        </>
      ) : (
        <div className="fixed inset-0 z-[90] bg-[var(--scrim)]" onClick={onBackdrop} aria-hidden data-testid="tour-spotlight" />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ coach card */
function CoachCard({
  rect,
  mobile,
  center,
  waiting,
  children,
  onHold,
}: {
  rect: DOMRect | null;
  mobile: boolean;
  center?: boolean;
  waiting?: boolean;
  children: React.ReactNode;
  onHold: (v: boolean) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [h, setH] = useState(320);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setH(el.offsetHeight));
    ro.observe(el);
    setH(el.offsetHeight);
    return () => ro.disconnect();
  }, []);
  // Focus the card's heading on each step for screen readers and keyboard users.
  useEffect(() => {
    const t = setTimeout(() => ref.current?.querySelector<HTMLElement>("[data-tour-title]")?.focus({ preventScroll: true }), 60);
    return () => clearTimeout(t);
  }, []);
  const vw = typeof window !== "undefined" ? window.innerWidth : 1920;
  const vh = typeof window !== "undefined" ? window.innerHeight : 1080;
  const W = Math.min(400, vw - 32);
  const gap = 18;
  const m = 16;
  let style: React.CSSProperties;
  if (mobile) style = { left: 12, right: 12, bottom: 12, maxHeight: "56dvh" };
  else if (center || !rect) style = { left: (vw - Math.min(520, vw - 32)) / 2, top: Math.max(24, (vh - h) / 2), width: Math.min(520, vw - 32) };
  else {
    const clampY = (y: number) => Math.max(m, Math.min(vh - h - m, y));
    const clampX = (x: number) => Math.max(m, Math.min(vw - W - m, x));
    const cx = rect.left + rect.width / 2;
    const below = vh - rect.bottom - gap - m;
    const above = rect.top - gap - m;
    if (vw - rect.right >= W + gap * 2) style = { left: rect.right + gap, top: clampY(rect.top), width: W };
    else if (rect.left >= W + gap * 2) style = { left: rect.left - W - gap, top: clampY(rect.top), width: W };
    else if (Math.max(below, above) >= 260)
      style = below >= above ? { left: clampX(cx - W / 2), top: rect.bottom + gap, width: W, maxHeight: below } : { left: clampX(cx - W / 2), bottom: vh - rect.top + gap, width: W, maxHeight: above };
    else style = { right: 24, bottom: 24, width: W, maxHeight: vh * 0.62 };
  }
  return (
    <div
      ref={ref}
      role="dialog"
      aria-modal="false"
      aria-label="Guided tour"
      className={cn(
        "fixed z-[95] flex max-h-[calc(100dvh-24px)] flex-col overflow-hidden rounded-[22px] border border-border bg-surface-raised p-5 shadow-3 animate-[pop_320ms_var(--ease-out)_both]",
        mobile && "max-h-[58dvh] rounded-[20px] p-4",
      )}
      style={style}
      onMouseEnter={() => onHold(true)}
      onMouseLeave={() => onHold(false)}
      onFocus={() => onHold(true)}
      onBlur={() => onHold(false)}
      data-testid="tour-card"
      aria-busy={waiting || undefined}
    >
      {children}
    </div>
  );
}

function CardChrome({
  chapter,
  index,
  total,
  title,
  onClose,
  progress,
  children,
}: {
  chapter: string;
  index: number;
  total: number;
  title: string;
  onClose: () => void;
  progress: number | null;
  children: React.ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex min-h-0 flex-1 flex-col gap-3">
      {progress !== null ? (
        <div className="-mx-5 -mt-5 mb-1 h-1 overflow-hidden rounded-t-[22px] bg-surface-sunken" aria-hidden>
          <div className="h-full bg-water-grad" style={{ width: `${Math.min(100, progress * 100)}%` }} />
        </div>
      ) : null}
      <div className="flex items-start justify-between gap-3">
        <div className="eyebrow flex items-center gap-2 text-water-deep">
          <Compass size={13} aria-hidden />
          {chapter}
          <span className="num font-semibold text-ink-tertiary">
            {index + 1} / {total}
          </span>
        </div>
        <IconButton label="Leave the tour" size="sm" onClick={onClose} data-testid="tour-close" className="-mr-2 -mt-1.5">
          <X size={16} />
        </IconButton>
      </div>
      <h2 id={id} tabIndex={-1} data-tour-title className="display -mt-1 text-[23px] leading-tight text-ink outline-none focus:outline-none focus-visible:shadow-none focus-visible:outline-none" data-testid="tour-title">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** "Saved result · run … · computed <server time>": the honest label on every step. */
function SavedLabel({ runId, analysisId, turnId, turnAt }: { runId?: string | null; analysisId?: string | null; turnId?: string | null; turnAt?: string | null }) {
  const run = useRun(runId ?? null);
  const ana = useAnalysis(analysisId ?? null);
  if (turnId) {
    return (
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-tertiary" data-testid="tour-saved" data-id={turnId}>
        <Chip size="sm" tone="wheat" icon={<History size={11} aria-hidden />}>
          Saved investigation
        </Chip>
        <span className="font-mono" title={turnId}>
          turn {shortId(turnId)}
        </span>
        <span>· computed {turnAt ? formatDateTime(turnAt) : "…"}</span>
      </div>
    );
  }
  const id = runId ?? analysisId ?? null;
  const at = run.data?.created_at ?? (ana.data?.created_at as string | undefined) ?? null;
  if (!id) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-tertiary" data-testid="tour-saved" data-id={id}>
      <Chip size="sm" tone="wheat" icon={<History size={11} aria-hidden />}>
        {runId ? "Saved result" : "Saved analysis"}
      </Chip>
      <span className="font-mono" title={id}>
        {runId ? "run" : "analysis"} {shortId(id)}
      </span>
      <span>· computed {at ? formatDateTime(at) : "…"}</span>
      {run.error || ana.error ? <span className="text-danger">· could not be loaded</span> : null}
    </div>
  );
}

function FinishActions({ ctx }: { ctx: TourCtx }) {
  const pilots = usePilots();
  const other = (pilots.data ?? []).find((p) => p.pilot_id !== ctx.session.pilot_id);
  const item = "flex w-full items-start gap-3 rounded-[14px] border border-border bg-surface p-3 text-left transition-[border-color,box-shadow] hover:border-water/40 hover:shadow-2";
  return (
    <div className="flex flex-col gap-2" data-testid="tour-finish">
      <button
        type="button"
        className={item}
        onClick={() => {
          ctx.exit();
          ctx.navigate(`/p/${encodeURIComponent(ctx.session.pilot_id)}/${encodeURIComponent(ctx.session.pilot_version)}/workspace`);
          useUI.getState().set({ scenarioOpen: true, settingsRequest: useUI.getState().settingsRequest + 1 });
          focusWhenReady('[data-tour="capital-budget"] input');
        }}
        data-testid="tour-finish-plan"
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-water-grad text-on-water" aria-hidden>
          <Sparkles size={16} />
        </span>
        <span>
          <span className="block text-[14px] font-semibold text-ink">Plan it yourself</span>
          <span className="block text-[12.5px] text-ink-secondary">Change the water, money or fairness settings and find a new plan, live.</span>
        </span>
      </button>
      {other ? (
        <button
          type="button"
          className={item}
          onClick={() => {
            ctx.exit();
            ctx.navigate(`/p/${encodeURIComponent(other.pilot_id)}/${encodeURIComponent(other.pilot_version)}/workspace`);
          }}
        >
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-water-soft text-water-deep" aria-hidden>
            <MapIcon size={16} />
          </span>
          <span>
            <span className="block text-[14px] font-semibold text-ink">Try the other watercourse</span>
            <span className="block text-[12.5px] text-ink-secondary">{other.name}</span>
          </span>
        </button>
      ) : null}
      <button type="button" className={item} onClick={() => ctx.openAssistant()}>
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-water-soft text-water-deep" aria-hidden>
          <MessageCircle size={16} />
        </span>
        <span>
          <span className="block text-[14px] font-semibold text-ink">Ask AabFlow a question</span>
          <span className="block text-[12.5px] text-ink-secondary">“Why is this tail field worse off?” “What if we build the pond anyway?”</span>
        </span>
      </button>
      <button
        type="button"
        className={item}
        onClick={() => {
          ctx.exit();
          ctx.navigate("/onboarding");
        }}
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-water-soft text-water-deep" aria-hidden>
          <PlusCircle size={16} />
        </span>
        <span>
          <span className="block text-[14px] font-semibold text-ink">Add a new region</span>
          <span className="block text-[12.5px] text-ink-secondary">Draw an area, fetch imagery, let the AI draw fields, review and publish.</span>
        </span>
      </button>
    </div>
  );
}

function SessionProblem({ state, onClose }: { state: ReturnType<typeof useDemoSession>; onClose: () => void }) {
  const pilots = usePilots();
  const navigate = useNavigate();
  const loc = useLocation();
  const first = pilots.data?.[0];
  const explore = () => {
    onClose();
    if (first && !loc.pathname.startsWith("/p/")) navigate(`/p/${encodeURIComponent(first.pilot_id)}/${encodeURIComponent(first.pilot_version)}/workspace`);
  };
  if (state.kind === "loading")
    return (
      <div className="flex items-center gap-4" role="status" data-testid="tour-loading">
        <SpotArt kind="busy" />
        <div>
          <h2 className="display text-[21px] text-ink">Opening the saved session…</h2>
          <p className="text-[13px] text-ink-secondary">Loading the stored runs and analyses from the local API.</p>
        </div>
      </div>
    );
  const session = state.kind === "incomplete" ? (state.session as DemoSession) : null;
  return (
    <div className="flex flex-col gap-4" data-testid="tour-unavailable" data-kind={state.kind}>
      <div className="flex items-start justify-between gap-3">
        <SpotArt kind={state.kind === "error" ? "error" : "plan"} />
        <IconButton label="Close" size="sm" onClick={onClose}>
          <X size={16} />
        </IconButton>
      </div>
      <div>
        <h2 className="display text-[23px] leading-tight text-ink">
          {state.kind === "missing" ? "The tour needs a saved session first" : state.kind === "incomplete" ? "Some saved results are missing" : "The tour could not start"}
        </h2>
        <p className="mt-2 text-[14px] leading-relaxed text-ink-secondary">
          {state.kind === "missing" ? (
            <>
              The tour only shows results that were really computed and stored, and none are saved in this database yet. Create them once (about a minute): it runs the real solver for
              the three plans, a budget change, the spend-vs-harvest curve and the bad-year test.
            </>
          ) : state.kind === "incomplete" && session ? (
            <>
              The saved session from {formatDateTime(session.created_at)} names {session.missing_ids.length} record{session.missing_ids.length === 1 ? "" : "s"} this database does not have
              (for example a reset database). Re-create the session so every step opens a real result.
            </>
          ) : state.kind === "error" ? (
            <>
              {describeError(state.error).title}. {describeError(state.error).detail}
            </>
          ) : null}
        </p>
      </div>
      {state.kind !== "error" ? (
        <div className="flex items-center gap-2 rounded-[12px] bg-ink px-3.5 py-2.5 font-mono text-[13px] text-canvas">
          <Terminal size={14} aria-hidden /> make demo-seed
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={explore} trailing={<ArrowRight size={14} />}>
          Explore on my own
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}
