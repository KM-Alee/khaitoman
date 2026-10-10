/**
 * Guided-tour UI state (Zustand: UI state only). The tour never stores analytical values;
 * it holds the step index and display preferences, and reads saved run/analysis IDs from
 * the server's demo-session manifest.
 */
import { create } from "zustand";
import { useStoryMode } from "@/components/ui/MetricTile";

interface TourState {
  active: boolean;
  step: number;
  autoplay: boolean;
  /** Set when the visitor pauses autoplay by hovering/focusing the coach card. */
  held: boolean;
  start: (step?: number) => void;
  stop: () => void;
  go: (step: number) => void;
  setAutoplay: (v: boolean) => void;
  setHeld: (v: boolean) => void;
}

export const useTour = create<TourState>((set) => ({
  active: false,
  step: 0,
  autoplay: false,
  held: false,
  start: (step = 0) => {
    useStoryMode.getState().set(true);
    set({ active: true, step, held: false });
  },
  stop: () => {
    useStoryMode.getState().set(false);
    set({ active: false, held: false });
  },
  go: (step) => set({ step, held: false }),
  setAutoplay: (autoplay) => set({ autoplay }),
  setHeld: (held) => set({ held }),
}));
