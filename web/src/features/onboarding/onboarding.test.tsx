/**
 * Onboarding wizard against a mocked fetch that replays labelled fixtures shaped from real
 * API responses (src/test/onboardingFixtures.ts). Publish is exercised only here, never
 * against the live data directory.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router";
import { useUI } from "@/app/store";
import { ApiError } from "@/lib/api/client";
import { TooltipProvider } from "@/components/ui/primitives";
import * as fx from "@/test/onboardingFixtures";
import { OnboardingScreen } from "./OnboardingScreen";
import { buildReviewBody, draftFromView, nextPilotVersion, parsePolygon, reviewConflict, stepStatus } from "./wizard";
import type { IntakeView } from "./onboardingApi";

const ID = fx.viewNeedsReview.onboarding_id;
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const view = (v: unknown) => clone(v) as IntakeView;

/** TEST FIXTURE: /pilots rows (pilot-b has reviewed-v1 and reviewed-v2 published). */
const PILOTS_FIXTURE = {
  pilots: [
    { pilot_id: "pilot-b", pilot_version: "reviewed-v1", name: "Lower Chenab representative pilot B", aoi_bbox: [72.234, 30.657, 72.256, 30.677], versions: ["reviewed-v1", "reviewed-v2"] },
    { pilot_id: "pilot-b", pilot_version: "reviewed-v2", name: "Lower Chenab representative pilot B", aoi_bbox: [72.234, 30.657, 72.256, 30.677], versions: ["reviewed-v1", "reviewed-v2"] },
  ],
};

interface Call {
  method: string;
  path: string;
  body: unknown;
  headers: Record<string, string>;
}
type Handler = (call: Call) => Response | Promise<Response>;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let calls: Call[] = [];
let routes: Record<string, Handler> = {};

function serve(extra: Record<string, Handler> = {}) {
  routes = {
    "GET /api/v2/pilots": () => json(PILOTS_FIXTURE),
    "GET /api/v2/onboarding/raw-packages": () => json(fx.rawPackages),
    [`GET /api/v2/onboarding/${ID}/layers`]: () => json(fx.layersReady),
    [`GET /api/v2/onboarding/${ID}/layers/aoi`]: () => json(fx.layerAoi),
    [`GET /api/v2/onboarding/${ID}/layers/imagery`]: () => json(fx.layerImagery),
    [`GET /api/v2/onboarding/${ID}/layers/canals`]: () => json(fx.layerCanals),
    [`GET /api/v2/onboarding/${ID}/layers/fields-proposed`]: () => json(fx.layerProposed),
    [`GET /api/v2/onboarding/${ID}/layers/fields-raw`]: () => json(fx.layerRaw),
    [`GET /api/v2/onboarding/${ID}/layers/weather`]: () => json(fx.layerWeather),
    [`GET /api/v2/onboarding/${ID}/layers/terrain`]: () => json(fx.layerTerrain),
    ...extra,
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://test");
    const method = init?.method ?? "GET";
    const call: Call = {
      method,
      path: url.pathname,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      headers: (init?.headers ?? {}) as Record<string, string>,
    };
    calls.push(call);
    const exact = routes[`${method} ${url.pathname}`];
    if (exact) return exact(call);
    if (method === "GET" && url.pathname.startsWith("/api/v2/jobs/")) {
      return json({ ...fx.processAccepted.job, state: "succeeded", stage: "process:inference", progress: 0.6 });
    }
    return json({ code: "NOT_FOUND", detail: `no fixture for ${method} ${url.pathname}` }, 404);
  }) as typeof fetch;
}

function Workspace() {
  const { pilotId, version } = useParams();
  return <div data-testid="workspace-route">{`${pilotId}/${version}`}</div>;
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/onboarding/:intakeId?" element={<OnboardingScreen />} />
            <Route path="/p/:pilotId/:version/workspace" element={<Workspace />} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const callsTo = (method: string, path: string) => calls.filter((c) => c.method === method && c.path === path);

beforeEach(() => {
  calls = [];
  useUI.setState({ jobs: [] });
  serve();
});

describe("wizard helpers", () => {
  it("prefills the next reviewed version and parses imported polygons", () => {
    expect(nextPilotVersion(["reviewed-v1", "reviewed-v2"])).toBe("reviewed-v3");
    expect(nextPilotVersion([])).toBe("reviewed-v1");
    expect(nextPilotVersion(["draft", "reviewed-v9", "reviewed-v10"])).toBe("reviewed-v11");
    const ring = parsePolygon(JSON.stringify({ type: "FeatureCollection", features: [{ type: "Feature", geometry: fx.layerAoi.geojson }] }));
    expect(ring).toHaveLength(4);
    expect(ring[0]).toEqual([72.256, 30.657]);
    expect(() => parsePolygon("{nope")).toThrow("Not valid JSON");
    expect(() => parsePolygon(JSON.stringify({ type: "Polygon", coordinates: [[[72, 30], [72.2, 30]]] }))).toThrow("three distinct vertices");
    expect(() => parsePolygon(JSON.stringify({ type: "MultiPolygon", coordinates: [] }))).toThrow("single GeoJSON Polygon");
  });

  it("derives the stepper from the server state only", () => {
    expect(stepStatus(undefined, { closed: false }).current).toBe("aoi");
    expect(stepStatus(undefined, { closed: true }).current).toBe("sources");
    expect(stepStatus(view(fx.viewCreated), { closed: false }).current).toBe("fields");
    expect(stepStatus(view(fx.viewNeedsReview), { closed: false }).current).toBe("fields");
    const reviewed = stepStatus(view(fx.viewReviewed), { closed: false });
    expect(reviewed.current).toBe("publish");
    expect([...reviewed.done]).toEqual(expect.arrayContaining(["fields", "graph", "validation"]));
    const published = view(fx.viewReviewed);
    published.state = "published";
    expect(stepStatus(published, { closed: false }).done.has("publish")).toBe(true);
  });

  it("sends the full edit set, the explicit network and only changed rules", () => {
    const v = view(fx.viewReviewed);
    const draft = draftFromView(v);
    expect(draft.fieldEdits).toHaveLength(1);
    expect(draft.sourceCanal).toBe("osm:way/488499235");
    expect(draft.capacity).toBe("0.1");
    expect(draft.rules.min_area_m2).toBe("5000");
    draft.rules.min_width_m = "40";
    const body = buildReviewBody(draft, v.review_version, v);
    expect(body.expected_version).toBe(1);
    expect(body.field_edits).toEqual(v.review!.field_edits);
    expect(body.reviewer).toBe("p07 wizard capture");
    expect(body.review_config).toEqual({
      min_width_m: 40,
      network: { direction: "downstream", source_feature_id: "osm:way/488499235", capacity_m3_s: 0.1, roster_basis: "declared_cca", outlet: "reach_group", acknowledged: true },
    });
    const conflict = reviewConflict(new ApiError(409, fx.reviewConflict as never, "Conflict"));
    expect(conflict).toEqual({ serverVersion: 1, expectedVersion: 0, detail: "review version 1 != expected 0" });
    expect(reviewConflict(new ApiError(422, fx.reviewInvalid as never, "Unprocessable"))).toBeNull();
  });
});

describe("new intake (AOI and sources)", () => {
  it("lists raw packages, checks the package AOI with the server and starts a tracked process job", async () => {
    serve({
      "POST /api/v2/onboarding/aoi-check": () => json(fx.aoiCheck),
      "POST /api/v2/onboarding": () => json(fx.viewCreated, 201),
      [`POST /api/v2/onboarding/${ID}/process`]: () => json(fx.processAccepted, 202),
      [`GET /api/v2/onboarding/${ID}`]: () => json({ ...fx.viewCreated, job_id: fx.processAccepted.job_id, job_state: "queued" }),
      [`GET /api/v2/onboarding/${ID}/layers`]: () => json(fx.layersCreated),
    });
    renderAt("/onboarding");
    const select = (await screen.findByLabelText("Raw source package")) as HTMLSelectElement;
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options.some((o) => o?.includes("20261010T003841Z-798d10d2"))).toBe(true);
    expect(screen.getByTestId("start-onboarding")).toBeDisabled();

    fireEvent.change(select, { target: { value: "data/raw/bundles/pilot-b/20261010T003841Z-798d10d2" } });
    const check = await screen.findByTestId("aoi-check");
    await within(check).findByText("467.9 ha (4.68 km²)");
    expect(within(check).getByText("EPSG:32643")).toBeInTheDocument();
    expect(callsTo("POST", "/api/v2/onboarding/aoi-check")[0].body).toEqual({ contract_version: "2.0.0", aoi: fx.rawPackages.packages[1].aoi });

    fireEvent.change(screen.getByLabelText("Region name (optional)"), { target: { value: "Wizard capture pilot-b" } });
    const start = screen.getByTestId("start-onboarding");
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);

    await screen.findByTestId("intake");
    const created = callsTo("POST", "/api/v2/onboarding")[0];
    expect(created.body).toEqual({
      contract_version: "2.0.0",
      aoi: fx.rawPackages.packages[1].aoi,
      source_mode: "raw_package",
      name: "Wizard capture pilot-b",
      raw_package_id: "data/raw/bundles/pilot-b/20261010T003841Z-798d10d2",
    });
    expect(created.headers["Idempotency-Key"]).toBeTruthy();
    const processCall = callsTo("POST", `/api/v2/onboarding/${ID}/process`)[0];
    expect(processCall.headers["Idempotency-Key"]).toBeTruthy();
    const tracked = useUI.getState().jobs.find((j) => j.jobId === fx.processAccepted.job_id);
    expect(tracked?.pilotKey).toBe(`onboarding:${ID}`);
    expect(screen.getByTestId("processing")).toBeInTheDocument();
  });

  it("shows server AOI blockers and keeps the start button disabled", async () => {
    serve({ "POST /api/v2/onboarding/aoi-check": () => json(fx.aoiCheckTooBig) });
    renderAt("/onboarding");
    fireEvent.change(screen.getByLabelText("AOI GeoJSON"), {
      target: { value: JSON.stringify({ type: "Polygon", coordinates: [[[72, 30], [72.2, 30], [72.2, 30.2], [72, 30.2], [72, 30]]] }) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use GeoJSON" }));
    await screen.findByText("AOI 427.89 km² exceeds the 25 km² limit");
    expect(screen.getByTestId("start-onboarding")).toBeDisabled();
    expect(screen.getByTestId("start-hint")).toHaveTextContent("Resolve the AOI blockers first.");
  });

  it("rejects malformed GeoJSON before calling the server and shows a server 422", async () => {
    serve({ "POST /api/v2/onboarding/aoi-check": () => json({ code: "INVALID_INPUT", detail: "AOI polygon invalid: Self-intersection", fields: { aoi: "AOI polygon invalid: Self-intersection" } }, 422) });
    renderAt("/onboarding");
    fireEvent.change(screen.getByLabelText("AOI GeoJSON"), { target: { value: "{not json" } });
    fireEvent.click(screen.getByRole("button", { name: "Use GeoJSON" }));
    expect(await screen.findByText("GeoJSON not usable: Not valid JSON.")).toBeInTheDocument();
    expect(callsTo("POST", "/api/v2/onboarding/aoi-check")).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("AOI GeoJSON"), {
      target: { value: JSON.stringify({ type: "Polygon", coordinates: [[[72, 30], [72.1, 30.1], [72.1, 30], [72, 30.1], [72, 30]]] }) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use GeoJSON" }));
    expect(await screen.findByText("AOI rejected by the server")).toBeInTheDocument();
    expect(screen.getByText("aoi: AOI polygon invalid: Self-intersection")).toBeInTheDocument();
  });

  it("explains an empty raw package store", async () => {
    serve({ "GET /api/v2/onboarding/raw-packages": () => json({ intake_kind: "raw_source_bundle", packages: [] }) });
    renderAt("/onboarding");
    expect(await screen.findByText("No raw source packages")).toBeInTheDocument();
  });
});

describe("intake processing states", () => {
  it("shows a failed job honestly and re-queues processing on request", async () => {
    const failed = { ...clone(fx.viewCreated), state: "failed", stage: "failed", job_id: "job_failed", job_state: "failed", error: { code: "JOB_FAILED", detail: "BundleError: sentinel2 window missing" } };
    serve({
      [`GET /api/v2/onboarding/${ID}`]: () => json(failed),
      [`GET /api/v2/onboarding/${ID}/layers`]: () => json(fx.layersCreated),
      [`POST /api/v2/onboarding/${ID}/process`]: () => json(fx.processAccepted, 202),
    });
    renderAt(`/onboarding/${ID}`);
    const alert = await screen.findByTestId("process-failed");
    expect(alert).toHaveTextContent("Processing failed");
    expect(alert).toHaveTextContent("BundleError: sentinel2 window missing");
    expect(alert).toHaveTextContent("JOB_FAILED");
    fireEvent.click(within(alert).getByRole("button", { name: "Run processing again" }));
    await waitFor(() => expect(callsTo("POST", `/api/v2/onboarding/${ID}/process`)).toHaveLength(1));
    await waitFor(() => expect(useUI.getState().jobs.some((j) => j.jobId === fx.processAccepted.job_id)).toBe(true));
  });

  it("labels an interrupted job and a cache miss without inventing progress", async () => {
    const interrupted = { ...clone(fx.viewCreated), state: "acquired_raw", job_id: "job_x", job_state: "interrupted" };
    serve({ [`GET /api/v2/onboarding/${ID}`]: () => json(interrupted), [`GET /api/v2/onboarding/${ID}/layers`]: () => json(fx.layersCreated) });
    const { unmount } = renderAt(`/onboarding/${ID}`);
    expect(await screen.findByText("Processing was interrupted (the service restarted)")).toBeInTheDocument();
    unmount();

    const awaiting = { ...clone(fx.viewCreated), state: "awaiting_inference", job_id: "job_y", job_state: "succeeded", inference: { ...clone(fx.viewNeedsReview.inference), inference_completed: false, cache_hit: false } };
    serve({ [`GET /api/v2/onboarding/${ID}`]: () => json(awaiting), [`GET /api/v2/onboarding/${ID}/layers`]: () => json(fx.layersCreated) });
    renderAt(`/onboarding/${ID}`);
    const panel = await screen.findByTestId("awaiting-inference");
    expect(panel).toHaveTextContent("does not start vision inference from the UI");
    expect(panel).toHaveTextContent("vision/run_batch.py");
  });

  it("shows a missing intake as an error with a way out", async () => {
    serve({ "GET /api/v2/onboarding/onb_missing": () => json({ code: "NOT_FOUND", detail: "onboarding_id onb_missing not found" }, 404) });
    renderAt("/onboarding/onb_missing");
    expect(await screen.findByText("Intake record unavailable")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a new intake" })).toHaveAttribute("href", "/onboarding");
  });
});

describe("review", () => {
  it("renders API layers, lists blockers from the view and sends a version-checked review", async () => {
    serve({
      [`GET /api/v2/onboarding/${ID}`]: () => json(fx.viewNeedsReview),
      [`PATCH /api/v2/onboarding/${ID}/review`]: () => json(fx.reviewOk),
    });
    renderAt(`/onboarding/${ID}`);
    const table = await screen.findByTestId("field-table");
    const first = fx.layerProposed.geojson.features[0].properties;
    expect(within(table).getByRole("button", { name: first.label })).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(fx.layerProposed.geojson.features.length + 1);
    expect(await screen.findByTestId("imagery-table")).toHaveTextContent("S2B_43RBP_20241210_0_L2A");

    const validation = screen.getByTestId("validation");
    expect(validation).toHaveTextContent("structural: direction, source, outlet, capacity and roster are not reviewed");
    expect(validation).toHaveTextContent("published offset NOT applied");
    expect(screen.getByTestId("publish-button")).toBeDisabled();
    expect(screen.getByTestId("publish-hint")).toHaveTextContent("Apply a review first.");

    fireEvent.click(within(table).getByRole("button", { name: first.label }));
    const composer = screen.getByTestId("edit-composer");
    fireEvent.click(within(composer).getByTestId("add-edit"));
    expect(within(composer).getByRole("alert")).toHaveTextContent("A reason is required");
    fireEvent.change(within(composer).getByTestId("edit-reason"), { target: { value: "bright bare/built-up yard; no cropped parcel boundary visible" } });
    fireEvent.click(within(composer).getByTestId("add-edit"));
    expect(screen.getByTestId("staged-edits")).toHaveTextContent(first.source_model_ids[0]);

    const canal = (await screen.findByTestId("source-canal")) as HTMLSelectElement;
    expect(canal.value).toBe("osm:way/488499235");
    fireEvent.change(screen.getByTestId("capacity"), { target: { value: "0.1" } });
    fireEvent.click(screen.getByTestId("acknowledge"));
    fireEvent.change(screen.getByLabelText("Reviewer (logged with this version)"), { target: { value: "p07 wizard capture" } });
    fireEvent.click(screen.getByTestId("apply-review"));

    await waitFor(() => expect(callsTo("PATCH", `/api/v2/onboarding/${ID}/review`)).toHaveLength(1));
    const patch = callsTo("PATCH", `/api/v2/onboarding/${ID}/review`)[0];
    expect(patch.headers["Idempotency-Key"]).toMatch(/^review-/);
    expect(patch.body).toEqual({
      contract_version: "2.0.0",
      expected_version: 0,
      reviewer: "p07 wizard capture",
      field_edits: [{ model_id: first.source_model_ids[0], action: "reject", reason: "bright bare/built-up yard; no cropped parcel boundary visible" }],
      review_config: {
        network: { direction: "downstream", source_feature_id: "osm:way/488499235", capacity_m3_s: 0.1, roster_basis: "declared_cca", outlet: "reach_group", acknowledged: true },
      },
    });
    // The intake is refetched after a successful review.
    await waitFor(() => expect(callsTo("GET", `/api/v2/onboarding/${ID}`).length).toBeGreaterThan(1));
  });

  it("shows a stale review version (409) and reloads the server's version", async () => {
    let current: unknown = fx.viewNeedsReview;
    serve({
      [`GET /api/v2/onboarding/${ID}`]: () => json(current),
      [`PATCH /api/v2/onboarding/${ID}/review`]: () => json(fx.reviewConflict, 409),
    });
    renderAt(`/onboarding/${ID}`);
    fireEvent.click(await screen.findByTestId("apply-review"));
    const alert = await screen.findByTestId("review-conflict");
    expect(alert).toHaveTextContent("You edited review v0; the server is at v1. Nothing was written.");
    expect(screen.getByTestId("apply-review")).toBeDisabled();
    current = fx.viewReviewed;
    fireEvent.click(within(alert).getByRole("button", { name: "Reload the current review" }));
    await waitFor(() => expect(screen.getByTestId("apply-review")).toHaveTextContent("Apply review (v1 → v2)"));
    expect(screen.queryByTestId("review-conflict")).not.toBeInTheDocument();
    expect(screen.getByTestId("staged-edits")).toHaveTextContent("da:50ca220c256bbf74:237");
  });

  it("shows a rejected review (422) with the server's reason", async () => {
    serve({
      [`GET /api/v2/onboarding/${ID}`]: () => json(fx.viewNeedsReview),
      [`PATCH /api/v2/onboarding/${ID}/review`]: () => json(fx.reviewInvalid, 422),
    });
    renderAt(`/onboarding/${ID}`);
    fireEvent.click(await screen.findByTestId("apply-review"));
    const alert = await screen.findByTestId("review-error");
    expect(alert).toHaveTextContent("Review rejected; the version did not change");
    expect(alert).toHaveTextContent("needs a reason");
  });
});

describe("publish", () => {
  it("prefills the next version, publishes with an idempotency key and opens the workspace", async () => {
    const published = {
      onboarding_id: ID,
      pilot_id: "pilot-b",
      pilot_version: "reviewed-v3",
      state: "published",
      immutable: true,
      libraries: [],
      readiness: { baseline: { ready: false }, candidates: { ready: false }, reused_as_current: false },
      jobs: [
        { job_id: "job_base", operation: "onboarding.baseline", state: "queued", ready: false, reason: "no library for reviewed-v3" },
        { job_id: "job_cand", operation: "onboarding.candidates", state: "queued", ready: false, reason: "no library for reviewed-v3" },
      ],
    };
    serve({
      [`GET /api/v2/onboarding/${ID}`]: () => json(fx.viewReviewed),
      [`POST /api/v2/onboarding/${ID}/publish`]: () => json(published, 201),
    });
    renderAt(`/onboarding/${ID}`);
    const version = (await screen.findByTestId("publish-version")) as HTMLInputElement;
    await waitFor(() => expect(version.value).toBe("reviewed-v3"));
    expect(screen.getByLabelText("Pilot id")).toHaveValue("pilot-b");
    expect(screen.getByTestId("validation")).toHaveTextContent("No structural blockers reported by the server");
    fireEvent.click(screen.getByTestId("publish-button"));
    expect(await screen.findByTestId("workspace-route")).toHaveTextContent("pilot-b/reviewed-v3");
    const call = callsTo("POST", `/api/v2/onboarding/${ID}/publish`)[0];
    expect(call.body).toEqual({ contract_version: "2.0.0", pilot_id: "pilot-b", pilot_version: "reviewed-v3" });
    expect(call.headers["Idempotency-Key"]).toMatch(/^publish-/);
    const readiness = useUI.getState().jobs.filter((j) => j.pilotKey === "pilot-b@reviewed-v3").map((j) => j.jobId);
    expect(readiness.sort()).toEqual(["job_base", "job_cand"]);
  });

  it("shows the server refusing an existing version and a missing version", async () => {
    let reply = () => json(fx.publishExists, 409);
    serve({
      [`GET /api/v2/onboarding/${ID}`]: () => json(fx.viewReviewed),
      [`POST /api/v2/onboarding/${ID}/publish`]: () => reply(),
    });
    renderAt(`/onboarding/${ID}`);
    const version = (await screen.findByTestId("publish-version")) as HTMLInputElement;
    fireEvent.change(version, { target: { value: "reviewed-v1" } });
    fireEvent.click(screen.getByTestId("publish-button"));
    const err = await screen.findByTestId("publish-error");
    expect(err).toHaveTextContent("That version already exists");
    expect(err).toHaveTextContent("pilot-b/reviewed-v1 is already published and cannot be replaced");
    expect(screen.queryByTestId("workspace-route")).not.toBeInTheDocument();

    reply = () => json(fx.publishNoVersion, 422);
    fireEvent.change(version, { target: { value: "reviewed-v9" } });
    fireEvent.click(screen.getByTestId("publish-button"));
    await waitFor(() => expect(screen.getByTestId("publish-error")).toHaveTextContent("pilot_version: required"));
    const keys = callsTo("POST", `/api/v2/onboarding/${ID}/publish`).map((c) => c.headers["Idempotency-Key"]);
    expect(new Set(keys).size).toBe(2);
  });

  it("links a published intake to its workspace", async () => {
    serve({ [`GET /api/v2/onboarding/${ID}`]: () => json({ ...clone(fx.viewReviewed), state: "published", pilot_version: "reviewed-v3", validation: { blockers: [], warnings: [], publish_blockers: [] } }) });
    renderAt(`/onboarding/${ID}`);
    expect(await screen.findByText("Published pilot-b / reviewed-v3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the workspace/ })).toHaveAttribute("href", "/p/pilot-b/reviewed-v3/workspace");
  });
});
