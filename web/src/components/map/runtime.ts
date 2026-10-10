/**
 * One persistent MapLibre instance for the whole app (T10.3). Its container is a detached
 * DOM node that each screen's <MapSlot> adopts; moving the node keeps the GL context,
 * sources and camera, so changing screens never rebuilds the map.
 */
import { create } from "zustand";
import { MapEngine, type MapMode } from "./engine";

let container: HTMLDivElement | null = null;
let parking: HTMLDivElement | null = null;
let engine: MapEngine | null = null;
let ro: ResizeObserver | null = null;

interface MapRuntimeState {
  ready: boolean;
  attachedTo: string | null;
  set: (p: Partial<MapRuntimeState>) => void;
}
export const useMapRuntime = create<MapRuntimeState>((set) => ({ ready: false, attachedTo: null, set: (p) => set(p) }));

function ensureContainer() {
  if (!container) {
    container = document.createElement("div");
    container.className = "aab-map absolute inset-0";
    container.style.position = "absolute";
    container.style.inset = "0";
    container.dataset.testid = "pilot-map";
    container.setAttribute("data-testid", "pilot-map");
    parking = document.createElement("div");
    parking.style.cssText = "position:fixed;left:-10000px;top:0;width:800px;height:600px;visibility:hidden;pointer-events:none";
    parking.setAttribute("aria-hidden", "true");
    document.body.appendChild(parking);
    parking.appendChild(container);
  }
  return container;
}

export function getEngine(): MapEngine | null {
  return engine;
}

export function ensureEngine(opts: { mode: MapMode; reducedMotion: boolean }): MapEngine {
  const c = ensureContainer();
  if (!engine) {
    engine = new MapEngine(c, { ...opts });
    (window as unknown as { __aabMap?: MapEngine }).__aabMap = engine;
    engine.whenReady().then(() => useMapRuntime.getState().set({ ready: true }));
    ro = new ResizeObserver(() => engine?.resize());
    ro.observe(c);
  }
  return engine;
}

export function attachMap(slot: HTMLElement, slotId: string) {
  const c = ensureContainer();
  if (c.parentElement !== slot) slot.appendChild(c);
  useMapRuntime.getState().set({ attachedTo: slotId });
  requestAnimationFrame(() => engine?.resize());
}

export function detachMap(slotId: string) {
  if (useMapRuntime.getState().attachedTo !== slotId) return;
  if (container && parking && container.parentElement !== parking) parking.appendChild(container);
  useMapRuntime.getState().set({ attachedTo: null });
}

/** Test-only teardown. */
export function __resetMapRuntime() {
  ro?.disconnect();
  engine?.destroy();
  engine = null;
  container?.remove();
  parking?.remove();
  container = parking = null;
  useMapRuntime.setState({ ready: false, attachedTo: null });
}
