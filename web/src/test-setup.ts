import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// jsdom has no WebGL: replace MapLibre with an inert, labelled test double so screens render.
vi.mock("maplibre-gl", () => {
  class FakeMap {
    private handlers = new Map<string, ((...a: unknown[]) => void)[]>();
    private canvas = document.createElement("canvas");
    constructor(opts: { container: HTMLElement }) {
      opts.container.appendChild(this.canvas);
    }
    on(ev: string, fn: (...a: unknown[]) => void) {
      this.handlers.set(ev, [...(this.handlers.get(ev) ?? []), fn]);
      return this;
    }
    once(ev: string, fn: () => void) {
      if (ev === "load") setTimeout(fn, 0);
      return this;
    }
    off() {
      return this;
    }
    getCanvas() {
      return this.canvas;
    }
    getContainer() {
      return this.canvas.parentElement!;
    }
    getStyle() {
      return { layers: [], sources: {} };
    }
    isStyleLoaded() {
      return true;
    }
    addSource() {}
    addLayer() {}
    getLayer() {
      return undefined;
    }
    getSource() {
      return undefined;
    }
    removeLayer() {}
    removeSource() {}
    setPaintProperty() {}
    setLayoutProperty() {}
    setFilter() {}
    setFeatureState() {}
    setTerrain() {}
    getTerrain() {
      return null;
    }
    setSky() {}
    resize() {}
    remove() {}
    jumpTo() {}
    easeTo() {}
    flyTo() {}
    fitBounds() {}
    cameraForBounds() {
      return { center: [0, 0], zoom: 12 };
    }
    getPitch() {
      return 0;
    }
    getBearing() {
      return 0;
    }
    setBearing() {}
    getZoom() {
      return 12;
    }
    getCenter() {
      return { lng: 0, lat: 0 };
    }
    project() {
      return { x: 0, y: 0 };
    }
    queryRenderedFeatures() {
      return [];
    }
  }
  class FakeMarker {
    setLngLat() {
      return this;
    }
    addTo() {
      return this;
    }
    remove() {}
  }
  const mod = { Map: FakeMap, Marker: FakeMarker, addProtocol: () => {} };
  return { default: mod, ...mod };
});
vi.mock("maplibre-gl/dist/maplibre-gl.css", () => ({}));

if (!window.matchMedia) {
  window.matchMedia = (q: string) =>
    ({
      matches: false,
      media: q,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}
if (!("ResizeObserver" in window)) {
  (window as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};
