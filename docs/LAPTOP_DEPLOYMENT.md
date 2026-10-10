# Vercel frontend and laptop backend

Activated on 10 October 2026. Production source is latest `main` at
`3cc65e3`, fast-forwarded onto `codex/laptop-serving`, plus the report contract
fix at `03f5ecc`. The independent laptop backend runs schema 4. No PR was
merged by this deployment session.

Frontend: https://app.khmanan.site
Backend login/health: https://api.khmanan.site/api/v2/health

The deployed configuration and executed checks are recorded below. Local
validation logs, account screenshots and backups remain in the ignored `.laptop/`
directory; the sanitized public activation record is under `evidence/commands/`.

## Topology

```text
Browser -> app.khmanan.site (static React build hosted on Vercel)
        -> api.khmanan.site (Cloudflare Access + named Tunnel, HTTPS)
                            -> backend:8000 in Docker on this laptop
                               -> SQLite, data files and CPU job dispatcher
                               -> separate vision container when needed
```

The browser connects directly to the backend for JSON, SSE, imagery, GeoJSON,
terrain and report files. Vercel only serves the frontend. This avoids routing
long-lived streams through Vercel's external proxy, whose documented request
timeout is 120 seconds. A Quick Tunnel is unsuitable: Cloudflare documents
changing hostnames, no uptime guarantee and no SSE support.
[Vercel limits](https://vercel.com/docs/limits),
[Cloudflare Quick Tunnel limits](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

The custom frontend domain and backend domain should be HTTPS subdomains of the
same site. This allows browser cookies for Cloudflare Access without depending
on third-party cookies on a `vercel.app` preview origin. Local development still
uses the existing Vite proxy unless `VITE_BACKEND_ORIGIN` is set.

## What is running on this laptop

- Checkout: `/home/kali/.codex/worktrees/laptop-serving/khaitoman`, branch
  `codex/laptop-serving`. Keep this checkout: the running data and guard service
  refer to it. Development remains in `/home/kali/Projects/khaitoman`.
- Docker project: `aabflow-laptop`, defined by `compose.laptop.yaml`.
- Backend health: `http://127.0.0.1:8010/api/v2/health`. Loopback only.
- Frozen backend image: `aabflow-laptop-backend:local`. One Uvicorn process owns
  SQLite and the dispatcher; CPU jobs run in its process pool. No source mount or reload.
- Real data copied into `.laptop/data`, independently writable from development.
  The full data tree includes libraries, models, raw packages, completed runs and
  demo session. Paths inside the container remain `/app/data`, preserving stored references.
- Vision cache copied into `.laptop/vision/{runs,batches}`. API and vision share
  only these stores and the laptop data. Vision code/configs are frozen separately
  in `aabflow-laptop-vision:local`; its parent is the existing `aabflow-vision:local`.
  The current vision environment is CPU-only: its Torch CUDA check returned false.
- Optional local preview: `http://127.0.0.1:5180`, container
  `aabflow-laptop-preview`. This serves a production build pointed at port 8010
  to verify the split before Vercel. It is temporary and need not run for deployment.
- `.laptop/settings` contains nonsecret Compose settings. The backend obtains
  provider configuration through Compose's optional runtime environment file;
  this laptop points it to `/home/kali/Projects/khaitoman/.env`. No secret was read
  or copied into source, the frontend or an image. Changing that file affects
  the serving container only when it is recreated.

This setup is for your single-user or trusted demonstration. Cloudflare Access
must protect the complete backend hostname before enabling the Tunnel. CORS is
an origin allowlist, not authentication. Organization/pilot authorization and
storage separation for independent tenants remain outside this personal setup
(implementation contract T14); don't treat it as a multi-tenant service.

## Power, startup and recovery

Docker was already enabled at boot. The backend and named Tunnel use
`restart: unless-stopped`, bounded logs and an init process. Backend health checks
verify SQLite and the running dispatcher every 30 seconds. Docker restarts a
crashed container; it does not restart one solely because it is unhealthy.

`aabflow-laptop-guard.service` supplies that recovery: it restarts this backend
after Docker marks it unhealthy following three failed checks. The guard holds
a `systemd-inhibit` block on sleep, idle and lid handling. It is enabled as a user
service, and `loginctl enable-linger kali` was executed successfully, allowing it
to start without an interactive login. These settings don't change the existing
development services.

Keep the charger plugged in, ventilation clear and Wi-Fi/Ethernet connected.
The inhibitor cannot prevent battery exhaustion, forced suspension, power loss
or router outages. There is no second machine to serve during laptop/network
downtime. A manually stopped service stays stopped, including after reboot.

```bash
cd /home/kali/.codex/worktrees/laptop-serving/khaitoman
./scripts/laptop.sh status
./scripts/laptop.sh check
./scripts/laptop.sh logs
systemctl --user status aabflow-laptop-guard.service
systemd-inhibit --list
loginctl show-user kali -p Linger
```

## Recreating the local setup

Only Docker and existing host utilities are used. Project Python/Node dependencies
remain inside their images. The API and vision base images must already exist
from the project's setup; no project packages are installed on the host.

```bash
cd /path/to/deployment/checkout
# Set this before the first invocation if using an external runtime env file.
export AABFLOW_RUNTIME_ENV_FILE=/path/to/development/checkout/.env
# Quiesce source writers and wait for jobs/chat turns to finish before seeding.
./scripts/laptop.sh seed /path/to/development/checkout/data
./scripts/laptop.sh build
./scripts/laptop.sh up
./scripts/laptop.sh awake
loginctl enable-linger "$USER"
```

`seed` never overwrites an existing destination. It uses SQLite's online backup
API through a read-only SQL connection and checks `PRAGMA integrity_check`, then
copies the real data and inference cache. The source mount permits SQLite's WAL
locking/shared-memory side files; application records are not modified. Avoid
new writes until the copy finishes: SQLite backup alone cannot provide an atomic
snapshot of independently changing artifact files. Active jobs/turns are rejected.
A failed copy is retained as `.partial`; move it aside before retrying.

Use `.laptop/settings` to set your runtime environment file, UID/GID, loopback
port and exact allowed browser origins. The data directory is fixed at
`.laptop/data` so the backup/update commands operate on the same store.
Never commit `.laptop/` or a Tunnel token. Docker build context excludes
`.env`, `.env.*`, `.laptop`, worker scratch and other worktrees.

## Saved Cloudflare configuration

- Cloudflare account: `632f75dd46f2ae7d046c1a236e88f409`; Zero Trust team `khmanan`.
- DNS: `app` CNAME `cname.vercel-dns.com`, DNS only, TTL Auto. This is Vercel's
  exact recommended record from the domain-configuration tool; Vercel verified
  domain ownership. `api` is a proxied tunnel CNAME to
  `92f3c888-5097-48a7-8726-06ce5b485dc1.cfargotunnel.com`, created by the route.
- Remotely managed tunnel `aabflow-laptop`, ID
  `92f3c888-5097-48a7-8726-06ce5b485dc1`; published route `api.khmanan.site`, all
  paths, service `http://backend:8000`, catch-all HTTP 404. Dashboard status Healthy.
- Access app `AabFlow laptop API`, ID `06429ebd-2d6e-4ad5-9b96-5517f9114a6d`,
  covers the whole API hostname. `AabFlow owner only` Allow policy
  `df134ae8-8de6-4fc2-9666-8fad09dc5232` includes only
  `Kali.bscs24seecs@seecs.edu.pk`; no testers. Session 24 hours, HTTP Only cookie.
- Access bypasses OPTIONS to the origin; actual requests require login. API CORS
  permits `https://app.khmanan.site` and the two local preview origins.
- Active cache rule `AabFlow backend bypass cache`, ID
  `9573d3a3665a4c92ad4f87576acc0121`, expression
  `(http.host eq "api.khmanan.site")`; cache and browser-TTL bypass.
- Connector token is only `.laptop/cloudflared-token`, user-owned mode 600 and
  ignored by Git. Docker reads the mounted secret file. Never print or commit it.
  `.laptop/access-ready` records that the account policy was configured.

After a stopped stack, restart with:

```bash
cd /home/kali/.codex/worktrees/laptop-serving/khaitoman
./scripts/laptop.sh up
./scripts/laptop.sh tunnel-up
systemctl --user start aabflow-laptop-guard.service
./scripts/laptop.sh check
```

The following steps describe how to re-provision the current arrangement.

## Public HTTPS configuration and re-provisioning

1. Use the two hostnames in the Cloudflare-managed `khmanan.site` zone.
   Preserve every unrelated DNS record.
2. Create a Cloudflare Access self-hosted application protecting **all paths**
   on `api.khmanan.site`. Allow only your email or explicit trusted testers.
   Set a session lifetime that covers your demonstration. Do not create a
   permanent bypass policy. Configure Access to bypass **OPTIONS preflights**
   to the origin, allowing the API to enforce its CORS allowlist. GET/POST and
   other actual requests must still require authentication.
   [Access CORS setup](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/cors/).
3. Create a remotely managed named Tunnel in Cloudflare and route
   `api.khmanan.site` to **HTTP `backend:8000`**, not `localhost:8000`.
   The connector lives in Docker and shares the backend's network. Localhost
   inside that connector would refer to the connector itself.
   [Named Tunnel setup](https://developers.cloudflare.com/tunnel/get-started/).
4. Paste only the connector token into `.laptop/cloudflared-token` using a
   local editor. Restrict it to your user (`chmod 600`). Do not paste it in chat,
   shell arguments, Git or a `VITE_*` variable. The pinned connector reads it
   through a mounted secret file with `--token-file`.
   [Cloudflare token-file option](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/).
5. Change `AABFLOW_CORS_ORIGINS` in `.laptop/settings` to
   `https://app.khmanan.site` (comma-separated exact origins only if needed).
   Run `./scripts/laptop.sh up` to recreate the backend with that setting.
   Add a Cloudflare cache bypass rule covering this backend hostname, especially
   API responses and SSE. Apply rate limits for expensive mutation endpoints
   to match your demo audience; do not challenge or cache event streams.
6. Once those policies are configured, create the local readiness marker and
   start the connector:

   ```bash
   touch .laptop/access-ready
   ./scripts/laptop.sh tunnel-up
   ```

   The marker records your manual Access setup; it does not verify the account
   policy. The command waits for backend health and a live connector connection.
   Test the public URL before declaring it available.
7. Open `https://api.khmanan.site/api/v2/health` in your browser and sign in to
   Access. Then open the frontend in the same browser. Each tester must
   establish the API hostname's authorization cookie this way. The frontend
   sends credentials for API, SSE, imagery and map requests. Expired sessions
   require signing in again; there is no integrated Access login screen yet.

An unauthenticated request must be denied or redirected by Access. Verify an
allowed browser's health, a rejected origin's preflight, imagery, terrain,
report downloads and a job SSE stream. Do not expose the bare unauthenticated
FastAPI service just to make a `vercel.app` preview work.

## Saved Vercel configuration

Project `khaitoman` (`prj_wS9TQ4dmPKL6Cn786kAN51tcrRGB`) belongs to
`khmanans-projects` (`team_74W0csQAeV4Xw6lkyMLsvXrM`). Actual default-scope
connector access and the signed-in dashboard were verified. The production Git
branch is `codex/laptop-serving`, with custom-domain auto-assignment enabled.
Build settings were saved through the connector and independently checked in
the dashboard:

| Setting | Value |
| --- | --- |
| Root directory | `web` |
| Framework | Vite |
| Node version | 24.x |
| Install | `npm ci` |
| Build | `npm run build` |
| Output | `dist` |
| Public frontend domain | `app.khmanan.site` |
| `VITE_BACKEND_ORIGIN` | `https://api.khmanan.site` (origin only; no `/api/v2`) |
| Production Git branch | `codex/laptop-serving` |

`web/vercel.json` supplies build settings and the SPA history fallback. API and
`/assets` links resolve to the configured backend; Vite's bundled assets live
under `/static`. JSON requests, both job/onboarding streams and copilot streams,
map images/GeoJSON/DEM and report links all use that backend consistently.

Never put `OPENAI_API_KEY`, Tunnel tokens or Access service tokens in Vercel's
frontend variables. Every `VITE_*` value is public in the browser bundle.
`VITE_BACKEND_ORIGIN` is a build-time setting, so changing it requires rebuilding
the frontend. Stable Tunnel DNS avoids rebuilds after a laptop reconnect.

## Continuing development, updating and restoring

Edit/test the development checkout normally. Its `make down`, reloads, branch
switches and data changes don't affect the separately named serving project.
The running backend changes only when explicitly rebuilt/recreated.

```bash
# In the serving checkout, after putting reviewed source changes on its branch:
./scripts/laptop.sh update
# Inspect readiness and logs after each update.
./scripts/laptop.sh check
./scripts/laptop.sh status
```

Update builds both images first, retains the previous backend and vision images, stops the
backend, and makes a full data backup plus a matching `.vision` cache and `.image`
record before recreating it. This has a short outage; it is not zero-downtime.
If the backup fails, it starts the existing container and reports failure.
Wait for active jobs to finish before updating. Existing queued/running jobs are
not cloned into a second dispatcher.

`./scripts/laptop.sh backup` performs the same stopped-service backup without
changing the image. Store an additional copy off this laptop before relying on
it against disk loss. Each full backup currently uses about 6.6 GB; monitor disk
space and deliberately archive old copies. Nothing deletes backups automatically.

`./scripts/laptop.sh rollback` selects the retained previous backend and vision images. This
only rolls back code. If a new version migrated the database or modified stores,
stop the guard and both services, retain the current directories under new names,
copy the matching `backup-<timestamp>` to `.laptop/data`, and the matching
`backup-<timestamp>.vision` to `.laptop/vision`, then restart the matching images.
Do not restore while either API/vision is writing. Backups omit secrets. Schema
migration plus full rollback has not been exercised by this deployment task.

## ArcGIS HD imagery

The owner-provided replacement is configured as encrypted Vercel Production
variable `VITE_ARCGIS_KEY`. It was included by a fresh production build and the
Esri HD layer rendered in the authenticated frontend: enabled switch, Esri
attribution, 19 observed tile assets and no browser console errors. Screenshot:
`evidence/screenshots/laptop-public-hd-20261010.png`. The key itself is not in Git,
a runtime environment file, screenshots or validation logs.

This is a browser display key: Vite includes it in its public bundle. Account-side
referrer restrictions were not independently inspected; limit permitted referrers
to `app.khmanan.site` in the ArcGIS account. HD tiles are online display only;
analysis remains on the locally stored Sentinel-2 scene. Local imagery, GeoJSON
and terrain remain available without this optional basemap.

## Vision and remaining development limits

Existing published pilots and inference caches are ready locally. For a new
intake that reports inference pending, execute the separate environment:

```bash
./scripts/laptop.sh vision ONBOARDING_ID
# Then resume the process step from the frontend.
```

This is the existing project's manual inference handoff, preserved in the frozen
stack. The backend has no Docker socket. New online acquisition still requires
network access. New uncached vision inference was not executed in this deployment
task. CPU-only Torch was detected; no GPU inference or training is claimed.

This work does not advance feature/acceptance rows to complete. Features still
under development retain their existing capabilities and limitations. An actual machine reboot, deliberate unhealthy-container recovery, full
database rollback, session-expiry behavior and new uncached vision inference
remain unverified. Container recreation and schema migration to 4 were executed
and returned healthy; the tunnel also recovered after a connector restart.

To repeat the local browser smoke with the preview on 5180 and backend on 8010:

```bash
docker run --rm --network host --user "$(id -u):$(id -g)" \
  -v "$PWD:/app" -v /app/web/node_modules -w /app/web \
  aabflow-e2e:local node /app/scripts/check_laptop_split.mjs
```

It uses the real seeded demo and verifies browser API/preflight requests, native
EventSource, map assets and the rendered workspace. It writes
`evidence/screenshots/laptop-split-origin.png` and fails on unexpected request failures.

## Executed public validation

Latest `main` at `3cc65e3` was fast-forwarded into the serving branch. The report
export contract fix `03f5ecc` is deployed as production Vercel deployment
`dpl_FwyQERRpR2vWazzaKqNn3p1UTfHD` (Ready, build after ArcGIS replacement), with `app.khmanan.site` assigned.
The public bundle includes `https://api.khmanan.site`.

- Docker `make test DC='docker compose -p aabflow-serving-validation'`: 634 passed.
- Docker `make web-test web-build` with the same isolated project: 18 files,
  115 tests passed, TypeScript and Vite production build passed.
- Public allowed OPTIONS: HTTP 200, exact frontend origin and credential support;
  unapproved origin: HTTP 400. API health, report files, assets and SSE paths
  without authentication redirect to Access (HTTP 302).
- Owner email OTP login was executed. The frontend reports Backend API online;
  real pilot-a workspace displays satellite imagery, 30 fields and canals.
  Origin logs record HTTP 200 for GeoJSON, imagery and terrain requests through
  the tunnel. No browser console errors were observed in these tested views.
- Public UI created report `rpt_84f5b4b695644d38a3d2110d87b1dccc` from real saved
  run `run_5f2a5629def1436c8f8181f34188d783`; POST returned 202, the authenticated
  job SSE connection returned 200, and the UI reached succeeded. Downloaded
  report HTML: 150,622 bytes, includes the real run ID. Schedule CSV: 22,288
  bytes, 395 irrigation events. Long-lived SSE reconnect/session expiry is untested.
- A real new planner investigation `turn_afc2c16f135542f2923560621c2bef0c`
  completed in 90,748 ms / five rounds, was added to the serving demo manifest,
  and rendered publicly with 12 recorded tool steps and its actual recommendation.
  Existing seeded base runs were preserved. No development data was overwritten.
- `./scripts/laptop.sh update` built both frozen images, made full backup
  `.laptop/backup-20261010T175626Z` with `.vision` and `.image`, migrated SQLite
  to schema 4 and returned healthy. The previous images remain tagged `previous`.
- Backend and tunnel are running with `unless-stopped`; Docker is enabled at boot.
  Guard service is enabled/active, Linger=yes, and AabFlow's sleep/idle/lid
  inhibitor is active. The named connector's `/ready` check passed and Cloudflare
  shows Healthy. These are executed configuration checks, not a physical reboot test.

The initial report export failed HTTP 422 because the UI sent `action_plan` and
expected `downloads`, while the canonical API accepts `one_page_plan`/`full_report`
and returns `download_url`. The frontend now uses generated request/response
schemas and the canonical values. A regression test rejects unsupported report
kinds and checks the rendered server download link. No backend validation was
weakened. Earlier Vercel build failure from missing generated report schemas was
also repaired and is present in main.

## Stop serving

```bash
./scripts/laptop.sh stop
# Stop the optional preview if still running:
docker stop aabflow-laptop-preview
```

To prevent the guard starting again at login/boot, run
`systemctl --user disable --now aabflow-laptop-guard.service`. If no other user
services require linger, you can later undo it with `loginctl disable-linger "$USER"`.
Stopping does not delete images, data or backups.
