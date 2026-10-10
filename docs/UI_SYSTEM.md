# AabFlow UI system: "Furrow & Flow"

How the web app (`web/src`) looks, talks and behaves, and how to build on it. It covers the
information architecture, design tokens, components, patterns, motion, the guided tour, and
the contract for the assistant ("Ask AabFlow") slot.

Visitors are often first-time and non-expert (committee members, judges). Every screen
answers one plain question first and keeps the precise, traceable detail one click away.

## 1. Principles

1. **The server owns every number.** Components render `MetricValue`s, comparison-service
   deltas and analysis results. They never add, subtract, average, or ratio analytical
   values (T10.1). Unit display conversions (`fraction → %`, `kg → t`) live in
   `lib/formatting`. Allowed client-side operations are presentational only: sorting,
   counting IDs, and set differences of selected instance IDs.
2. **Plain first, precise behind.** Show the plain label (`Today's routine`) and keep the
   precise term (`B0 · fixed-roster baseline`) and its meaning behind `<Term>`.
   IDs stay visible but quiet: run, settings version, analysis.
3. **One question per screen, one next step.** Each screen opens with a `PageHeader`
   (the question) and ends with a `NextStep` (the next question).
4. **Honest states.** Empty, busy, ready, stale/changed, saved, feasible, infeasible,
   unknown and error are visibly different, and each names the next action
   (`StatePanel`, `ResultPanel`).
5. **Calm, then precise.** Use generous space and few colours: water teal is for action
   and identity, and wheat gold marks the recommended or focus item only. Dense tables are
   reserved for "All the numbers" sections.

## 2. Information architecture

Five destinations form a numbered journey (`app/journey.tsx`). Route ids are the PRD's,
so shared links and the copilot's `navigate_view` intents keep working.

| Step | Nav label | Route (`/p/:pilot/:version/…`) | Question | PRD name |
|---|---|---|---|---|
| 1 | Plan | `workspace` | What's the best plan for this watercourse? | Workspace |
| 2 | Compare | `compare`, `replay` | How much better is it than today? | Compare |
| 3 | What if | `explore?tab=frontier\|stress\|why-not\|sensitivity\|surrogate` | What if money or water is short? | Explore |
| 4 | Impact | `impact?tab=water\|economics\|equity\|sdg`, `report` | What does it cost, and who benefits? | Impact |
| 5 | Trust | `evidence` | Can I trust these numbers? | Evidence |

- `/` is the landing page (`features/landing`). It holds the tour entry, the published
  watercourses (real imagery with AI field outlines) and the five questions.
- `/onboarding/:intakeId?` is "Add a new region" (unchanged flow, restyled by the shared
  primitives).
- **URL selections** (`app/selection.ts`): `run`, `field`, `date`, `runs`, `analysis`,
  `tab`, `ev`, `q`. `run`, `field`, `date` and `runs` carry across screens. Stable
  selections live only in the URL; Zustand (`app/store.ts`) holds UI state only.
- **Shell** (`components/layout/AppShell.tsx`), on wide screens:
  `TopBar 64px` / `[Plan settings 312px] [screen] [Inspector 372px | Assistant 420px]`.
  - The Plan settings panel docks only on Plan.
  - The inspector docks on Plan (tabs Result · Field · Sources). On other screens it
    opens when a field is selected.
  - At ≤1179 px both become sheets. At ≤767 px there is a bottom nav and full-height
    sheets.
- **Top bar** (`ContextBar.tsx` → `TopBar`): wordmark · pilot + season switcher ·
  journey nav · connection · **Tour** · **Ask AabFlow** · contextual primary action
  (Find the best plan → Compare results → Action plan) · menu (Jump to Ctrl K, Add a
  region, presentation mode, theme, reduce motion).
- **Keyboard**:
  - `1`–`5` switch screens; `Ctrl K` opens the command menu; `/` opens field search;
    `Shift P` toggles presentation mode.
  - `[` `]` step through fields on a map; `Esc` closes a panel or clears the selection.
  - Shortcuts never fire while typing or while a dialog or the tour is open.

## 3. Tokens (`web/src/app/index.css`)

All tokens are CSS custom properties on `:root`, redefined under `:root[data-theme="dark"]`.
The `system` theme is resolved in JS (`app/environment.ts`). Tailwind utilities resolve to
the live tokens through `@theme inline` (`bg-surface`, `text-ink-secondary`,
`border-border`, `bg-water-grad`, …). Charts read them through `chartTokens()`
(`components/charts/EChart.tsx`) and map legends through `cssVar()`
(`components/map/palette.ts`). A theme switch therefore restyles charts and legends too.

### Colour

| Token | Light | Dark | Role |
|---|---|---|---|
| `canvas` / `canvas-deep` | `#F4F1E8` / `#EBE5D6` | `#0B1514` / `#081010` | App ground (warm silt) |
| `surface` / `surface-raised` | `#FFFEFB` / `#FFFFFF` | `#111E1D` / `#152523` | Cards, panels / popovers, inputs |
| `surface-muted` / `surface-sunken` | `#EEF0E9` / `#E5E7DE` | `#172826` / `#0A1312` | Quiet groups / tracks, skeletons |
| `ink` / `ink-secondary` / `ink-tertiary` | `#13292A` / `#445D5B` / `#536966` | `#E8EFEB` / `#A9BCB8` / `#93A8A4` | Text (tertiary ≥4.5:1 on surface, canvas, muted) |
| `water` / `water-deep` / `water-soft` / `water-glow` | `#087F8C` / `#065D67` / `#D5ECEA` / `#2FB6C1` | `#3FB3BF` / `#5CC3CE` / `#123A3D` / `#6FD6DF` | Primary action, identity, selection |
| `wheat` / `wheat-ink` / `wheat-soft` | `#B07D1C` / `#6F4F0D` / `#F5E8C7` | `#E0B154` / `#F0CF86` / `#362A10` | "Recommended", "Saved result", focus field; never a status |
| `vegetation` (+`-soft`) | `#386A4B` | `#86B996` | Crop identity, verified/OK chips |
| `warning` (+`-soft`) | `#975306` | `#E3A453` | Assumed, changed, infeasible |
| `danger` (+`-soft`) | `#A63E32` | `#EC8A7C` | Errors, explicit reductions |
| `border` / `border-strong` | `#D9DBD1` / `#7A908B` | `#253836` / `#5F7975` | Separation / non-text ≥3:1 |
| `focus` | `#245FBD` | `#86ADF5` | Focus ring (2 px, offset 2) |
| `plan-b0/b1/p/r` | `#7A6F5C` `#3E8A97` `#087F8C` `#6B4EA0` | lighter | One colour per plan everywhere (cards, dots, map tags) |

Data palettes are shared by charts and map legends:

- `--seq-0…5`: harvest (sequential).
- `--svc-0…5`: fair share (sequential).
- `--div-neg-2 … --div-pos-2`: change, with a visible zero.
- `--series-1…6`: categorical series.

Status never relies on colour alone: chips always carry an icon and a word.

### Type

- **Inter** (UI and data, `font-sans`) and **Fraunces** (`.display` for questions and
  titles, `.display-num` for headline numbers with lining tabular figures).
- **Noto Naskh Arabic** for Urdu (`[lang=ur]`, `.urdu`).
- All fonts are local in `web/public/fonts` (OFL; no CDN).
- Scale tokens: `--text-2xs 11` · `xs 12` · `sm 13` · `base 14` · `md 16` · `lg 18` ·
  `xl 22` · `2xl 28` · `3xl 36` · `4xl 48` · `5xl 64`.
- Labels are ≥12 px in the app and ≥16 px in presentation mode. Use `.num` for any number
  column. `.eyebrow` is 11 px uppercase with 0.1em tracking.

### Space, shape, depth

- Spacing: 4/8/12/16/24/32 (`--space-*`).
- Radius: 8 (controls), 10–12 (inputs, chips), 14–18 (cards), 20–22 (hero cards, tour
  card, sheets).
- Elevation: `shadow-1` rests, `shadow-2` lifts (hover, floating chrome), `shadow-3` for
  popovers, sheets and the tour card, `shadow-glow` for the recommended card or primary
  hero button.
- Textures: `.bg-dawn` (soft water/wheat light), `.bg-furrows` (field-row lines),
  `.bg-water-grad`, `.glass` (translucent surfaces over the map).

### Motion

- Durations: `--dur-control 150ms`, `--dur-panel 220ms`, `--dur-camera 400ms`,
  `--dur-story 600ms`.
- Easings: `--ease-out`, `--ease-inout`, `--ease-spring`.
- Utilities: `animate-rise` (content entering), `animate-fadein`, `animate-pop`
  (cards, popovers), `sheet-r/l/b` keyframes (sheets), `.flow-line` (canal flow
  dashes), `ring-pulse` (first-visit tour hint).
- **Reduced motion**: OS `prefers-reduced-motion` or the in-app "Reduce motion" setting
  (`data-motion="reduced"`) collapses every animation and transition to ~0 ms. The map
  uses 2D jumps instead of flights, and count-ups show the final value. Never animate
  analytical values between two computed results. The only number animation is the
  tour's entrance count-up (below).

## 4. Components (`web/src/components`)

| Component | File | Use |
|---|---|---|
| `Button`, `IconButton`, `buttonClass` | `ui/Button.tsx` | Variants `primary`, `hero` (one per page), `secondary`, `ghost`, `subtle`, `danger`, `inverse`; sizes `sm/md/lg/xl`; `busy` shows a spinner and disables. `IconButton` always needs `label`. |
| `Card`, `CardHeader`, `CardBody`, `CardFooter` | `ui/Card.tsx` | Grouped surface. `tone="hero"` for the one decisive answer, `quiet` for secondary groups, `accent` (wheat) sparingly. |
| `MetricTile`, `DeltaChip`, `CountUpValue`, `useStoryMode` | `ui/MetricTile.tsx` | One server `MetricValue` with a plain label, optional `Term`, optional server delta (`{value, unit, goodWhen, against}`) and hint. Sizes `sm/md` (Inter) and `lg/hero` (Fraunces). Non-available statuses render via `MetricValueView`. |
| `Term`, `TermHint`, `TermCard`, `Explain` | `ui/Term.tsx` | `Term id` renders the plain label with the precise term and meaning on hover, focus or tap. `TermHint` is a "?" button for next to form labels (keeps input names clean). `Explain` is a "What this means" disclosure. Vocabulary lives in `lib/glossary.ts`. |
| `PageHeader`, `NextStep`, `Stepper` | `ui/PageHeader.tsx` | Screen header (step eyebrow, question in display type, lead, actions, provenance `meta`). `NextStep` links to the next journey question. `Stepper` is the dot progress used by the tour. |
| `BrandMark`, `Wordmark`, `WatercourseArt`, `SpotArt` | `ui/Art.tsx` | Decorative SVG (aria-hidden) coloured by tokens. `SpotArt kind` is used in states: `plan`, `compare`, `chart`, `error`, `infeasible`, `search`, `trust`, `busy`. |
| `Tabs*`, `Segmented`, `Tooltip`, `Popover*`, `Dialog`/`DialogContent` (`side="right\|left\|bottom"` = sheet), `Switch`, `Select` (`help`), `SliderField` (`help`, direct numeric entry, commit on release), `Section`, `Eyebrow`, `Kbd`, `DL` | `ui/primitives.tsx` | Radix-based primitives. Signatures are stable (the copilot imports several). |
| `Chip`, `SolverBadge`, `JobBadge`, `EstimateBadge`, `ReviewFlagChips`, `TrustSummary`, `Provenance`, `MetricValueView`, `StatePanel`, `Skeleton`, `Progress`, `SOLVER_COPY`, `FLAG_PLAIN` | `status/index.tsx` | Status vocabulary. `SOLVER_COPY[status]` has `label` (precise), `plain` and `friendly`. `Provenance run saved?` is the quiet "run … · computed … · Best plan proven · water books balance" line. `StatePanel state` covers empty, busy, error, unknown, infeasible and blocked, with an `art` override and an `action`. `Progress` never fakes a percentage. |
| `SubTabs`, `CompareTabs` | `features/compare/CompareTabs.tsx` | Pill rails for `?tab=` and for Compare/Replay routes; scroll horizontally on phones. |
| `ChartPanel`, `EChart`, `DataTable`, `baseOption`, `chartTokens` | `charts/EChart.tsx` | Every chart has a table twin (the "Table" toggle), units in labels, gaps for missing data, and shared scales across comparisons. |
| `MapSlot`, `MetricSwitcher`, `MapLegend`, `SecondaryMap` | `map/*` | One persistent MapLibre instance re-parented between slots. `highlightFieldIds` emphasises fields. Local assets only. |
| `AssistantPanel`, `AssistantHeader` | `layout/AssistantPanel.tsx` | The "Ask AabFlow" slot (section 7). |
| `PilotPortrait` | `features/landing/PilotPortrait.tsx` | Still image of a pilot: Sentinel-2 display image with canals and reviewed field outlines (SVG, local). |

## 5. Patterns

**Page anatomy.** Each screen follows the same order:

```
<SubTabs …/>                        // optional
<div className="mx-auto max-w-[1400px] flex flex-col gap-5 p-4 md:p-8">
  <PageHeader title? lead? actions? meta={<Provenance run={run} />} />
  …answer first (cards, MetricTiles), detail after (tables, charts)…
  <NextStep />
</div>
```

**States.** Every data region handles all of these:

| State | Treatment |
|---|---|
| empty | `StatePanel state="empty"` naming what is missing, plus the action that fixes it |
| busy | Layout-only `Skeleton`, or measured or indeterminate `Progress` with the real job stage |
| ready | The data |
| changed | Draft differs from the last solve: warning banner, "Run again", "Undo changes" |
| saved | Result from a link, the tour or an older solve: wheat "Saved result" chip with computed time, and "Use these settings" |
| infeasible / unknown | Plain sentence, then the suggestion, then the technical detail behind `Explain` |
| error | `StatePanel state="error" error={e}`; independent sections stay usable |

**Language.**

- Write the question, then the answer in a sentence, then the number.
- Prefer verbs a farmer would use ("grows", "spends", "goes short").
- Name the comparison ("vs today's routine").
- Keep the precise term reachable (`Term`, tooltips, the "All the numbers" tables).
- Never round away a sign or a missing value: `Not estimated`, `Blocked` and
  `Unavailable` are distinct.

**Numbers.**

- Big numbers use `MetricTile` (server value + server delta).
- Lists and tables use `MetricValueView` or `formatWithUnit`.
- Deltas come only from `POST /comparisons` (`comparisonDeltas`, `deltaFor`) or from an
  analysis' own fields (`incremental`, `cells`).
- Ratios display as % and their deltas as percentage points.

**Saved vs live.** A stored run opens like any other run. `useRunContext(runId)`
reports `saved` when the run's settings version is not the visitor's active one.
`useScenario().adopt(request)` copies its settings into the editable draft; the next
solve creates a new scenario. Nothing is ever locked to a saved run.

**Responsive.**

- 1920×1200: everything docked.
- 1366×768: settings collapsible; the inspector stays; journey labels compact.
- 390×844: top bar (mark, pilot, Ask, menu), bottom nav, map then answer, sheets for
  settings, details and the assistant.
- No horizontal page scroll. Rails scroll inside themselves.

## 6. Building a new panel

```tsx
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { MetricTile } from "@/components/ui/MetricTile";
import { StatePanel, Skeleton, Provenance } from "@/components/status";
import { Explain } from "@/components/ui/Term";
import { useRun } from "@/lib/api/queries";
import { findMetric, runMetrics } from "@/lib/api/adapters";

export function PumpingPanel({ runId }: { runId: string | null }) {
  const run = useRun(runId);
  if (!runId) return <StatePanel state="empty" title="No plan yet" action={{ label: "Find the best plan", onClick: … }} />;
  if (run.isLoading) return <Skeleton className="h-40" />;
  if (run.error || !run.data) return <StatePanel state="error" error={run.error} title="Run unavailable" />;
  const gw = findMetric(runMetrics(run.data), "groundwater_m3");   // a server metric, never computed here
  return (
    <Card>
      <CardHeader eyebrow="Water" title="How much is pumped?" description="Groundwater from existing wells, within each pump's seasonal cap." />
      <CardBody className="flex flex-col gap-3">
        <MetricTile size="lg" label="Groundwater pumped" term="groundwater" metric={gw} />
        <Explain>Pumped water is finite and costs money; its quality is not verified.</Explain>
        <Provenance run={run.data} />
      </CardBody>
    </Card>
  );
}
```

Checklist:

- [ ] Query keys include pilot version, revision, run or analysis (`lib/api/queries.ts`).
- [ ] All states are handled.
- [ ] Units appear in labels.
- [ ] Charts have a table twin.
- [ ] Plain label plus `Term` for every expert word.
- [ ] Keyboard reachable, visible focus, `aria-label` on icon buttons.
- [ ] Works at 390 px.
- [ ] Add `data-tour="…"` if the tour should point at it.

## 7. Assistant slot ("Ask AabFlow")

**Where it renders.** The top-bar button toggles `useUI().assistantOpen`.

- At ≥1180 px, `AssistantPanel` docks on the right at **420 px** (`--copilot-w`), full
  height under the top bar. It replaces the inspector and never covers Plan settings or
  "Find the best plan" (PRD §9.3).
- Below 1180 px it opens as a right sheet (tablet) or a 90 dvh bottom sheet (phone).
- The slot renders a 56 px header (`AssistantHeader`), then the copilot's root
  component, `features/copilot/CopilotPanel`, which fills the remaining height (`h-full`,
  scroll inside).

**Mount point.** The slot is `components/layout/AssistantPanel.tsx`. It imports
`CopilotPanel` from `@/features/copilot/CopilotPanel` today. If the copilot feature adds
`web/src/features/copilot/index.ts` exporting its root component, the slot switches to
that import. The slot owns the frame (header, border, width, sheet); the copilot owns
everything inside it.

**Context available.** `CopilotPanel` takes no props. It reads:

- `useSelection()`: `pilotId`, `version`, `pilotKey`, `screen`, `runId`, `fieldId`,
  `date`, `compareRunIds`, `analysisId`, `tab`.
- `usePilotData()`: `fieldIndex` and the pilot record.
- `useRun(runId)`: the run on screen, including `scenario_revision_id`.
- `useUI()`: UI state, including `active[pilotKey]` (the visitor's settings version).
- `useRunContext(runId)`: the run's settings `request` and whether it is a `saved`
  result.

**Asking the app to act.** `useAppActions()` (`app/actions.ts`) provides verbs that
change navigation or UI state only:

| Action | Effect |
|---|---|
| `openScreen(screen, params?)` | `screen` is `workspace`, `compare`, `replay`, `explore`, `impact`, `report` or `evidence` |
| `openRun(runId, screen?)` | Shows a stored run |
| `openAnalysis(analysisId, tab?)` | Opens "What if" on that analysis |
| `selectField(fieldId)` | The map flies there and the inspector opens it |
| `setDate(iso)` | Moves the replay cursor |
| `highlightFields(ids \| null)` | Emphasises fields on the Plan map (`assistantHighlight`) |
| `overview()` | Frames the whole watercourse |
| `openAssistant()` / `closeAssistant()` | Opens or closes the slot |

The copilot's existing `nav.ts` (`useCopilotNav`) maps server view intents and citation
clicks onto the same URL selections. Either path is fine.

To open Plan settings, bump `useUI().settingsRequest`. To solve the current draft, set
`useUI().pendingRun = true` (it runs once when Plan is ready) or call
`useScenario().run()` from inside a pilot route. Branch creation, solving and comparison
numbers still come from the copilot's server tools, never from client code.

**How chat cards should look.** Build them from the shared components:

- An answer is a `Card` (`tone="default"`) with a short plain sentence first.
- Metrics use `MetricTile size="sm"` or `MetricValueView`; deltas use `DeltaChip` only
  with server deltas.
- Every card shows its source with `Provenance run={…}` or a citation chip (run,
  analysis or evidence id in `font-mono`, shortened with `shortId`).
- Actions are `Button size="sm" variant="secondary"` (`Open run`, `Show on map`,
  `Compare`) wired to `useAppActions`.
- Statuses use `Chip` and `SolverBadge` (icon plus word).
- Loading and errors use `Skeleton`, `Progress` and `StatePanel compact`.
- Keep line length near 60–70 characters inside the 420 px panel (`text-[13.5px]
  leading-relaxed`). Urdu uses `lang="ur"`.

## 8. Guided tour

**Code.** The tour lives in `features/tour`:

- `TourHost` is mounted once in `App`.
- `steps.tsx` holds the story.
- `api.ts` reads the manifest.
- `store.ts` holds the step index and autoplay state.

**Data.** `make demo-seed` (`scripts/seed_demo_session.py`) executes the real pipeline
through the running API and writes `data/demo/session.json` (gitignored):

- a pilot-a wheat-rabi-2027-28 capital-planning scenario on the published library;
- B0/B1/P/R solves;
- a budget-change child revision (B0/B1/P);
- a frontier and a stress analysis;
- a focus tail field and a decisive date, both chosen from server data.

`GET /api/v2/demo/session` serves the manifest and adds `available`, `missing_ids` and
`complete`, checked against this database. A 404 or incomplete manifest makes the tour
explain `make demo-seed` instead of starting. It is fetched only when the tour starts, so
no 404 is logged on normal pages.

**Behaviour.**

- Each step navigates to an ordinary route carrying the saved IDs (`?run=`,
  `?analysis=`, `?field=`, `?date=`).
- It spotlights a real element (`[data-tour]` or `[data-testid]`). The spotlight is a
  glowing rounded hole; the highlighted element stays clickable and the rest is paused.
- It explains the element with server numbers read through the normal hooks.
- Every step shows "Saved result · run … · computed <server time>".
- **Controls**: Back, Next, progress dots (jump), Auto-play (pauses on hover or focus and
  when the tab is hidden), × or `Esc` to leave, `←`/`→` to move.
- **Try it**: leaves the tour and focuses the matching live control, for example the
  budget input with the saved settings adopted.
- **Re-run live**: solves the same settings again as a new scenario. A failed live solve
  shows its real error; it is never replaced by the saved result.
- The finish card offers four ways out: plan it yourself, the other watercourse, ask
  AabFlow, or add a region.
- **Story mode**: while the tour runs, `MetricTile` values that have already arrived ease
  up from zero once (1.1 s). Screen readers get the final value immediately. Reduced
  motion disables it.

**Adding a step.** Append to `TOUR_STEPS`:

- `route(s)` and `target` selector are required.
- `Body` reads data with hooks.
- Optional: `saved(s)`, `tryIt`, `rerun`, `seconds`.

Then extend `tests/e2e/journey-tour.spec.ts`.
