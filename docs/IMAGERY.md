# High-resolution map imagery: plan and integration guide

Status: **decided 2026-10-10**. Development now targets this setup.

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

### Already implemented (web thread, 2026-10-10, uncommitted)

| File | What |
|---|---|
| `web/vite.config.ts` | `envDir` points at the repo root, so the dev server reads `VITE_*` from `.env`. |
| `web/src/components/map/hdImagery.ts` | `HD_IMAGERY_KEY`, `HD_IMAGERY_ATTRIBUTION`, `hdImageryTiles(key)`. This is the only place the URL lives. |
| `web/src/components/map/engine.ts` | Adds the `imagery-hd` raster source and layer when a key is set. `setHdImageryVisible()`. Visible only when both "imagery" and "HD" are on. |
| `web/src/app/store.ts` | Persisted `showHdImagery: true`. |
| `web/src/components/map/MapBinder.tsx`, `SecondaryMap.tsx` | Push the toggle into the engines. |
| `web/src/components/map/MapSlot.tsx` | Layers menu switch "High-res imagery (Esri)". It is disabled with the hint "Add VITE_ARCGIS_KEY to .env" when there is no key. |
| `web/src/features/workspace/WorkspaceScreen.tsx` | The credit chip shows the Esri attribution plus "analysis: Sentinel-2 …" when HD is on. |

This was verified with Playwright, using mocked tiles intercepted on `ibasemaps-api.arcgis.com`:
- 31 tile requests carried the token.
- The layer renders under the fields.
- The toggle switches back to Sentinel-2 and the credit updates.
- tsc is clean and vitest passes 49/49.

### Remaining work (for the integrating agent)

1. **`.env.example`**: add a commented `# VITE_ARCGIS_KEY=` line explaining that it is optional and display-only, and link to this doc.
2. **Frozen demo build (`make demo`)**: `.env` is in `.dockerignore`, so the `web-build` stage never sees the key.
   - In `Dockerfile`'s `web-build` stage, add `ARG VITE_ARCGIS_KEY=` and `ENV VITE_ARCGIS_KEY=$VITE_ARCGIS_KEY` before `npm run build`.
   - In `compose.yaml`, give the `demo` service build `args: { VITE_ARCGIS_KEY: "${VITE_ARCGIS_KEY:-}" }`. Compose interpolates from `.env` automatically.
   - Empty is fine: the app falls back to Sentinel-2.
3. **Attribution on every surface**:
   - The compare view's secondary map has `attributionControl: false`. When HD is on, show the Esri credit in the compare screen instead (one shared chip is enough).
   - Check presentation mode, where `present-hide` hides the workspace credit chip. The MapLibre compact attribution control must stay visible there.
   - Check Replay and Explore map screens too.
4. **Onboarding AOI map (`web/src/features/onboarding/AoiDrawMap.tsx`)**: when a key is set, use the same Esri tiles (via `hdImageryTiles`) as the background, so drawing the AOI is easier. Drawing an AOI is user input, not derived data, so this is allowed. Fall back to the current background without a key.
5. **Reports and exports**: find every place that snapshots the map canvas (report screen, PNG/PDF export, share). Hide `imagery-hd` during the snapshot and restore it afterwards, so exports contain only Sentinel-2.
6. **Failure handling**:
   - If tiles return 401/403 (bad or expired key), stop requesting them for the session: remove the layer, and switch the layers-menu hint to "Esri key rejected, showing Sentinel-2".
   - When offline (network error), do nothing special; Sentinel-2 underneath already shows.
   - Never surface a toast storm.
7. **Styling pass**:
   - Esri imagery is far sharper and greener than Sentinel-2. Retune the `imagery-hd` paint values (saturation, brightness-max) so server-coloured fields and canals still read first, in both light and dark themes.
   - Consider lowering `parcels-line` opacity slightly when HD is on.
8. **E2E tests (`tests/e2e/`)**: add a Playwright spec that runs the dev server with `VITE_ARCGIS_KEY=testkey`. Intercept `**/ibasemaps-api.arcgis.com/**` with a fixture PNG and assert:
   - (a) tile requests are made and carry the token;
   - (b) the layers switch toggles them off and on;
   - (c) the credit text shows the Esri attribution;
   - (d) with the route aborted, the map still renders and there are no page errors;
   - (e) without the key, the switch is disabled.
   Never hit the real Esri API in CI.
9. **Docs**: mention the optional key in the README quick start and add a line to `docs/STATUS.md`. The lead thread owns STATUS.md and commits.

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
