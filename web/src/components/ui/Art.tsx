/**
 * Illustration accents (docs/UI_SYSTEM.md › Illustration). Pure SVG, coloured by tokens,
 * decorative only (aria-hidden). Motion is a slow canal-flow dash that reduced-motion stops.
 */
import { cn } from "@/lib/cn";

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <defs>
        <linearGradient id="aab-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#14a9b6" />
          <stop offset="1" stopColor="#065d67" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#aab-g)" />
      <path d="M5.5 21c3.3 0 3.3-2.5 6.6-2.5s3.3 2.5 6.6 2.5 3.3-2.5 6.6-2.5" fill="none" stroke="#eafcfc" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M5.5 25.5c3.3 0 3.3-2.5 6.6-2.5s3.3 2.5 6.6 2.5 3.3-2.5 6.6-2.5" fill="none" stroke="#eafcfc" strokeOpacity=".5" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M16 5.5c2.7 3.5 4.1 6 4.1 7.8a4.1 4.1 0 0 1-8.2 0c0-1.8 1.4-4.3 4.1-7.8Z" fill="#f5e8c7" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <BrandMark className="h-8 w-8 shrink-0" />
      <span className="display text-[21px] leading-none text-ink">
        Aab<span className="text-water">Flow</span>
      </span>
    </span>
  );
}

/** A watercourse seen from above: parcels, a canal with flowing water, one highlighted tail field. */
export function WatercourseArt({ className, highlight = true }: { className?: string; highlight?: boolean }) {
  const parcels: [number, number, number, number, string][] = [
    [18, 22, 58, 40, "var(--seq-3)"],
    [84, 18, 64, 46, "var(--seq-4)"],
    [156, 26, 52, 36, "var(--seq-2)"],
    [24, 74, 48, 44, "var(--seq-2)"],
    [80, 76, 70, 38, "var(--seq-3)"],
    [160, 72, 58, 46, "var(--seq-1)"],
    [30, 128, 62, 38, "var(--seq-1)"],
    [100, 124, 50, 44, "var(--seq-2)"],
    [160, 128, 56, 40, "var(--seq-0)"],
  ];
  return (
    <svg viewBox="0 0 240 180" className={className} aria-hidden>
      <defs>
        <pattern id="furrow" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(-28)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="rgb(0 0 0 / 0.08)" strokeWidth="1.4" />
        </pattern>
      </defs>
      {parcels.map(([x, y, w, h, c], i) => (
        <g key={i}>
          <rect x={x} y={y} width={w} height={h} rx="6" fill={c} opacity="0.85" />
          <rect x={x} y={y} width={w} height={h} rx="6" fill="url(#furrow)" />
        </g>
      ))}
      {highlight ? <rect x="157" y="125" width="62" height="46" rx="8" fill="none" stroke="var(--wheat)" strokeWidth="2.5" strokeDasharray="5 4" /> : null}
      <path d="M2 64 C 60 66, 70 120, 128 118 S 206 116, 238 172" fill="none" stroke="var(--water)" strokeWidth="7" strokeLinecap="round" opacity="0.9" />
      <path d="M2 64 C 60 66, 70 120, 128 118 S 206 116, 238 172" fill="none" stroke="var(--water-soft)" strokeWidth="2" strokeLinecap="round" className="flow-line" />
    </svg>
  );
}

export type SpotKind = "plan" | "compare" | "chart" | "error" | "infeasible" | "search" | "trust" | "busy";

/** Small spot illustration for empty / error / infeasible states. */
export function SpotArt({ kind, className }: { kind: SpotKind; className?: string }) {
  const ring = "var(--water-soft)";
  return (
    <svg viewBox="0 0 64 64" className={cn("h-14 w-14", className)} aria-hidden>
      <circle cx="32" cy="32" r="30" fill={kind === "error" ? "var(--danger-soft)" : kind === "infeasible" ? "var(--warning-soft)" : ring} />
      {kind === "plan" ? (
        <>
          <rect x="16" y="20" width="14" height="11" rx="2.5" fill="var(--seq-3)" />
          <rect x="33" y="20" width="15" height="11" rx="2.5" fill="var(--seq-2)" />
          <rect x="16" y="34" width="14" height="11" rx="2.5" fill="var(--seq-1)" />
          <rect x="33" y="34" width="15" height="11" rx="2.5" fill="var(--wheat)" opacity=".75" />
          <path d="M10 46 C 24 44, 30 30, 54 24" stroke="var(--water)" strokeWidth="3" fill="none" strokeLinecap="round" />
        </>
      ) : kind === "compare" ? (
        <>
          <rect x="15" y="30" width="8" height="16" rx="2" fill="var(--plan-b0)" />
          <rect x="28" y="24" width="8" height="22" rx="2" fill="var(--plan-b1)" />
          <rect x="41" y="17" width="8" height="29" rx="2" fill="var(--plan-p)" />
        </>
      ) : kind === "chart" ? (
        <>
          <path d="M14 46 L 24 36 L 32 40 L 48 20" stroke="var(--water)" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="48" cy="20" r="3.5" fill="var(--wheat)" />
        </>
      ) : kind === "error" ? (
        <>
          <path d="M14 36 C 20 34, 24 34, 28 36" stroke="var(--danger)" strokeWidth="3.5" fill="none" strokeLinecap="round" />
          <path d="M36 36 C 40 38, 44 38, 50 36" stroke="var(--danger)" strokeWidth="3.5" fill="none" strokeLinecap="round" />
          <path d="M31 24 v 8 M31 38 v 0.5" stroke="var(--danger)" strokeWidth="3.5" strokeLinecap="round" />
        </>
      ) : kind === "infeasible" ? (
        <>
          <rect x="18" y="22" width="28" height="20" rx="4" fill="none" stroke="var(--warning)" strokeWidth="3" />
          <path d="M22 46 L 42 18" stroke="var(--warning)" strokeWidth="3" strokeLinecap="round" />
        </>
      ) : kind === "search" ? (
        <>
          <circle cx="29" cy="29" r="10" fill="none" stroke="var(--water)" strokeWidth="3.5" />
          <path d="M37 37 L 46 46" stroke="var(--water)" strokeWidth="3.5" strokeLinecap="round" />
        </>
      ) : kind === "trust" ? (
        <path d="M32 14 L 46 20 V 31 C 46 40, 40 46, 32 50 C 24 46, 18 40, 18 31 V 20 Z M25 32 L 30 37 L 40 27" stroke="var(--water)" strokeWidth="3" fill="none" strokeLinejoin="round" strokeLinecap="round" />
      ) : (
        <circle cx="32" cy="32" r="12" fill="none" stroke="var(--water)" strokeWidth="3.5" strokeDasharray="20 60" className="origin-center [animation:spin_1.2s_linear_infinite]" />
      )}
    </svg>
  );
}
