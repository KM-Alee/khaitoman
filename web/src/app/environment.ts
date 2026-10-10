import { useEffect, useState } from "react";
import { useUI } from "./store";

function mq(q: string): MediaQueryList | null {
  return typeof window !== "undefined" && window.matchMedia ? window.matchMedia(q) : null;
}

export function useMediaQuery(q: string): boolean {
  const [v, setV] = useState(() => mq(q)?.matches ?? false);
  useEffect(() => {
    const m = mq(q);
    if (!m) return;
    const on = () => setV(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [q]);
  return v;
}

/** Reduced motion: user override or OS preference. Map falls back to flat 2D. */
export function useReducedMotion(): boolean {
  const pref = useUI((s) => s.motion);
  const os = useMediaQuery("(prefers-reduced-motion: reduce)");
  return pref === "reduced" || (pref === "system" && os);
}

export function useResolvedTheme(): "light" | "dark" {
  const pref = useUI((s) => s.theme);
  const osDark = useMediaQuery("(prefers-color-scheme: dark)");
  return pref === "system" ? (osDark ? "dark" : "light") : pref;
}

/** Applies theme / presentation / motion flags to <html>. */
export function useDocumentFlags() {
  const theme = useResolvedTheme();
  const presentation = useUI((s) => s.presentation);
  const reduced = useReducedMotion();
  useEffect(() => {
    const el = document.documentElement;
    el.dataset.theme = theme;
    el.style.colorScheme = theme;
    el.dataset.presentation = presentation ? "on" : "off";
    el.dataset.motion = reduced ? "reduced" : "full";
  }, [theme, presentation, reduced]);
  return { theme, presentation, reduced };
}

export const BREAKPOINTS = {
  mobile: "(max-width: 767px)",
  tablet: "(max-width: 1179px)",
  compact: "(max-width: 1439px)",
};
