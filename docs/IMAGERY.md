# High-resolution map imagery: plan and integration guide

Status: **decided and implemented 2026-10-10**. Development now targets this setup.

## Decision

The map's display imagery switches from Sentinel-2 alone to **Esri World Imagery**, which is sub-metre in most of Punjab. It is served through the **ArcGIS Location Platform** (free tier: 2M basemap tiles a month).

- **Esri World Imagery** is the default background when a key is configured.
- **Sentinel-2 L2A (10 m, package imagery)** stays in the pilot package. It always renders underneath and is the fallback when there is no key, the network is down, or a tile fails.
- **All analysis stays on Sentinel-2 and the package data.** This covers field delineation (Delineate Anything), vegetation indices, AquaCrop and the optimizer. Esri imagery is display-only.

## Hard rules (Esri terms + project rules)

1. **Display only.** Never use Esri tiles as model input. Never derive field boundaries, NDVI or anything else from them. Never trace parcels on them for the package.
2. **No caching or storing of tiles.** No service worker, no IndexedDB tile cache, no copying tiles into `data/` or the pilot package. Never bake tiles into exported reports or PDFs; exports use Sentinel-2.
3. **Attribution always visible** wherever the Esri layer is visible: "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community". This includes the compare view, presentation mode and screenshots used in the demo.
4. **The key is a secret-ish config value.** It lives only in the repo-root `.env` as `VITE_ARCGIS_KEY` and is never committed. Agents never read `.env`. Because `VITE_` vars are compiled into the browser bundle, the key should be restricted to the Basemaps privilege and, where possible, to the `localhost` referrer in the ArcGIS dashboard.
5. **Offline must still work.** With no key or no network the app looks exactly as it did before: Sentinel-2, display-sharpened.

## Getting the key (pablo, one time)

1. Sign up at https://location.arcgis.com (ArcGIS Location Platform, free tier, no card needed).
2. Go to Content → New item → Developer credentials → **API key credentials**.
3. Under privileges, tick only **Location services → Basemaps**. Optionally add `http://localhost:5173` and `http://localhost:8000` as referrers.
4. Set the longest expiry, create the key, and copy it (it starts with `AAPT…` and is shown once).
5. Add `VITE_ARCGIS_KEY=AAPT…` to the repo-root `.env`, then `make up`.

## Technical design

Tile endpoint (XYZ, 256 px, z ≤ 19):

```
https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?token=<VITE_ARCGIS_KEY>
```

Layer order in the MapLibre style: `bg` → `imagery` (Sentinel-2 canvas) → **`imagery-hd`** (Esri raster) → `hillshade` → `aoi-mask` → parcels, canals, fields, assets. The Esri source is bounded to the package scene's bbox plus about 1 km, so we don't fetch tiles nobody sees. Terrain (raster-dem) drapes both imagery layers.

### Implemented (web thread, 2026-10-10, uncommitted)

The key is in the repo-root `.env`, added at pablo's request.

| File | What |
|---|---|
| `web/vite.config.ts` | `envDir` points at the repo root, so the dev server reads `VITE_*` from `.env`. |
| `web/src/components/map/hdImagery.ts` | The tile URL, attribution and key. Session-wide key health (`ok` / `rejected` / `off`) with `useHdStatus()`. |
| `web/src/components/map/engine.ts` | `imagery-hd` raster above Sentinel-2. Bounds are the scene bbox plus about 4 km, so the dimmed surroundings look real. Theme-aware muting (`hdPaint`). The parcel outlines quieten when HD is visible. Field fly-to goes closer (z17 instead of z16.2) when sharp imagery is on. A 401/403/498/499 from Esri drops the layer on every map. The compare view's secondary map keeps its attribution when HD is active. |
| `web/src/app/store.ts`, `MapBinder.tsx`, `SecondaryMap.tsx` | Persisted `showHdImagery` toggle, pushed into both engines. |
| `web/src/components/map/MapSlot.tsx` | Layers switch "High-res imagery (Esri)", with hints for no key and for a rejected key. |
| `web/src/features/workspace/WorkspaceScreen.tsx` | The credit chip shows the Esri attribution plus "analysis: Sentinel-2 …". |
| `web/src/features/onboarding/AoiDrawMap.tsx` | Esri basemap under the AOI drawing map. The graticule fades when it's on. Rejection is handled. |
| `Dockerfile`, `compose.yaml` | The `web-build` stage takes `ARG VITE_ARCGIS_KEY`. The `demo` service passes it from `.env`, so `make demo` and `make ui-checks` get it. |
| `.env.example` | Documents the optional key. |
| `tests/e2e/offline-imagery.spec.ts` (+ `fixtures/hd-tile.png`) | Mocked tiles: token present, switch toggles the layer, attribution contains Esri, network failure keeps Sentinel-2 with no page errors, and a 498 response drops the layer and disables the switch. Without a key, it asserts the switch is disabled. |

Report and export: nothing in the app snapshots the map canvas today, so there is nothing for Esri tiles to leak into. **Any future export feature must hide `imagery-hd` first.**

Presentation mode hides the credit chip, but MapLibre's attribution control, which carries the Esri credit, stays visible.

### Remaining

- Check real imagery in a browser on the laptop. The build sandboxes can't reach `ibasemaps-api.arcgis.com`, so only mocked tiles were tested.
- Add a line to `docs/STATUS.md` and the README quick start. The lead thread owns these.

### Out of scope

- AI super-resolution of Sentinel-2. It could come later and must be labelled "AI-upscaled".
- Google, Bing or Mapbox imagery: their terms forbid this use, or they need billing.
- Using Esri imagery for delineation.

## Checks

```
make web-test      # vitest
make web-build     # tsc --noEmit && vite build
make ui-checks     # Playwright + axe (frozen demo image)
make up            # then open http://localhost:5173 and toggle Layers → High-res imagery (Esri)
```
