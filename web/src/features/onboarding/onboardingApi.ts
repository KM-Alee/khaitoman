/**
 * Onboarding API client (PRD §5.3, T2.6, T9.1, T9.3). Request bodies use the generated
 * OpenAPI types; the routes return `dict[str, Any]`, so response shapes below mirror
 * `api/aabflow/services/onboarding/intake.py` and `ingestion/onboarding/layers.py` and were
 * checked against live responses. Analytical values (area, counts, blockers) come from the
 * API only; this module never derives them.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api/client";
import type { components } from "@/generated/api";
import type { JobState } from "@/lib/api/types";

type Schemas = components["schemas"];
export type IntakeCreateBody = Schemas["IntakeCreate"];
export type ReviewBody = Schemas["ReviewRequest"];
export type FieldEdit = Schemas["FieldEdit"];
export type PublishBody = Schemas["PublishRequest"];
export type AoiCheckBody = Schemas["AoiCheckRequest"];

export type IntakeState =
  | "created"
  | "queued"
  | "acquired_raw"
  | "processed"
  | "awaiting_inference"
  | "needs_review"
  | "reviewed"
  | "validated"
  | "published"
  | "failed"
  | "cancelled";

export interface AoiCheck {
  area_m2: number;
  bbox: [number, number, number, number];
  centroid: [number, number];
  metric_crs: string;
  estimated_pixels: number;
  warnings: string[];
  blockers: string[];
  source_availability?: { online: string; raw_bundle_count: number; note: string };
}

export interface RawPackage {
  bundle_id: string;
  pilot_id: string | null;
  bundle_ref: string;
  created_at: string | null;
  manifest_sha256: string;
  intake_kind: "raw_source_bundle";
  /** The bundle AOI. A raw-package intake must use exactly this polygon. */
  aoi?: GeoJSON.Polygon | null;
}

export interface ReviewSummary {
  accuracy_metrics?: string;
  config?: Record<string, number>;
  eligible?: number;
  manual_edits?: number;
  overlap_pairs_resolved?: number;
  raw_polygons?: number;
  rejected?: number;
  rules_version?: string;
  selected?: number;
  selected_corrected?: number;
  selected_correction_rate?: number;
  selection_method?: string;
  review_started_at?: string;
  review_finished_at?: string;
}

export interface Inference {
  inference_completed: boolean;
  cache_hit: boolean;
  device: string | null;
  inference_key: string | null;
  gpkg_sha256: string | null;
  input_sha256: string | null;
  run_record: string | null;
  command: string | null;
  cache_hits: string[];
  blockers: string[];
  warnings: string[];
  review_summary: ReviewSummary | null;
  parent_canal_feature_id: string | null;
}

export interface NetworkReview {
  direction: "downstream";
  source_feature_id: string;
  capacity_m3_s: number;
  roster_basis: "declared_cca" | "selected_area";
  outlet: "reach_group";
  acknowledged: boolean;
}

export interface AppliedReview {
  version: number;
  field_edits: FieldEdit[];
  reviewer: string | null;
  review_config: Record<string, number>;
  network: NetworkReview | null;
  parent_canal_feature_id: string | null;
  applied_at: string | null;
}

export interface IntakeError {
  code?: string;
  detail?: string;
}

export interface IntakeView {
  onboarding_id: string;
  intake_id: string;
  name: string | null;
  state: IntakeState | string;
  stage: string;
  review_version: number;
  source_mode: "online" | "raw_package" | null;
  bundle_ref: string | null;
  pilot_id: string | null;
  pilot_version: string | null;
  aoi_check: AoiCheck | null;
  blockers: string[];
  warnings: string[];
  validation: { blockers: string[]; warnings: string[]; publish_blockers?: string[] };
  job_id: string | null;
  job_state: JobState | null;
  progress: number | null;
  job_stage: string | null;
  error: IntakeError | null;
  inference: Inference | null;
  cache_hit: boolean;
  review_summary: ReviewSummary | null;
  /** Present on builds that report the applied review (null before processing writes it). */
  review?: AppliedReview | null;
  created_at: string;
  updated_at: string;
}

export interface ProcessAccepted {
  onboarding_id: string;
  job_id: string;
  job: { job_id: string; operation: string; state: JobState; stage: string | null; progress: number | null };
}

export interface ReviewResult {
  onboarding_id: string;
  review_version: number;
  state: string;
  blockers: string[];
  warnings: string[];
}

export interface PublishResult {
  onboarding_id: string;
  pilot_id: string;
  pilot_version: string;
  state: string;
  immutable: boolean;
  libraries: Record<string, unknown>[];
  readiness: { baseline: unknown; candidates: unknown; reused_as_current: boolean };
  jobs: { job_id: string; operation: string; state: JobState; ready: boolean; reason: string | null }[];
}

export type LayerId = "aoi" | "imagery" | "canals" | "fields-raw" | "fields-proposed" | "terrain" | "weather";

export interface LayerList {
  onboarding_id: string;
  state: string;
  available: LayerId[];
  unavailable: { id: LayerId; reason: string }[];
}

export interface ImageryScene {
  scene_id: string;
  label?: string;
  collection: string;
  acquired_at: string;
  resolution_m: number;
  aoi_valid_fraction?: number;
  scene_cloud_cover?: number;
  assets?: Record<string, { key: string; gsd?: number }>;
  width?: number;
  height?: number;
}

export interface CanalProps {
  source_feature_id: string;
  provider: string;
  waterway?: string | null;
  name?: string | null;
  observed?: boolean;
  license?: string;
}
export interface RawFieldProps {
  model_id: string;
  area?: number;
}
export interface ProposedFieldProps {
  field_id: string;
  label: string;
  area_m2: number;
  source_model_ids: string[];
  actions: string[];
}

export type LayerPayload =
  | { layer_id: "aoi"; geojson: GeoJSON.Geometry; source: string }
  | { layer_id: "imagery"; scenes: ImageryScene[] }
  | { layer_id: "canals"; geojson: GeoJSON.FeatureCollection<GeoJSON.Geometry, CanalProps> }
  | { layer_id: "fields-raw"; geojson: GeoJSON.FeatureCollection<GeoJSON.Geometry, RawFieldProps> & { properties?: Record<string, unknown> } }
  | { layer_id: "fields-proposed"; geojson: GeoJSON.FeatureCollection<GeoJSON.Geometry, ProposedFieldProps> }
  | { layer_id: "terrain"; metadata: Record<string, unknown> }
  | { layer_id: "weather"; weather: Record<string, unknown> };

export type LayerOf<K extends LayerId> = Extract<LayerPayload, { layer_id: K }>;

const enc = encodeURIComponent;
const ACTIVE_JOB: (JobState | null)[] = ["queued", "running", "cancel_requested"];
export const isJobActive = (s: JobState | null | undefined) => ACTIVE_JOB.includes(s ?? null) && s != null;
const noRetry4xx = (n: number, e: unknown) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;

/** Query keys: the intake id plus the review version, so a new review never reuses stale layers. */
export const onbKeys = {
  all: ["onboarding"] as const,
  rawPackages: ["onboarding", "raw-packages"] as const,
  intake: (id: string) => ["onboarding", id] as const,
  layers: (id: string, state: string, version: number) => ["onboarding", id, "layers", state, version] as const,
  layer: (id: string, layer: LayerId, state: string, version: number) => ["onboarding", id, "layer", layer, state, version] as const,
};

export function useRawPackages() {
  return useQuery({
    queryKey: onbKeys.rawPackages,
    queryFn: ({ signal }) => api.get<{ intake_kind: string; packages: RawPackage[] }>("/onboarding/raw-packages", signal),
    staleTime: 60_000,
    retry: noRetry4xx,
  });
}

export function useIntake(id: string | undefined) {
  return useQuery({
    queryKey: onbKeys.intake(id ?? ""),
    enabled: !!id,
    queryFn: ({ signal }) => api.get<IntakeView>(`/onboarding/${enc(id!)}`, signal),
    // Poll only while the server says a job is active; otherwise the record changes only on our mutations.
    refetchInterval: (q) => (isJobActive(q.state.data?.job_state) ? 1500 : false),
    staleTime: 0,
    retry: noRetry4xx,
  });
}

export function useIntakeLayers(view: IntakeView | undefined) {
  return useQuery({
    queryKey: onbKeys.layers(view?.onboarding_id ?? "", view?.state ?? "", view?.review_version ?? 0),
    enabled: !!view,
    queryFn: ({ signal }) => api.get<LayerList>(`/onboarding/${enc(view!.onboarding_id)}/layers`, signal),
    staleTime: Infinity,
    retry: noRetry4xx,
  });
}

export function useIntakeLayer<K extends LayerId>(view: IntakeView | undefined, layer: K, available: boolean) {
  return useQuery({
    queryKey: onbKeys.layer(view?.onboarding_id ?? "", layer, view?.state ?? "", view?.review_version ?? 0),
    enabled: !!view && available,
    queryFn: ({ signal }) => api.get<LayerOf<K>>(`/onboarding/${enc(view!.onboarding_id)}/layers/${layer}`, signal),
    staleTime: Infinity,
    retry: noRetry4xx,
  });
}

export function useAoiCheck() {
  return useMutation({
    mutationFn: (aoi: GeoJSON.Polygon) => {
      const body: AoiCheckBody = { contract_version: "2.0.0", aoi: aoi as unknown as AoiCheckBody["aoi"] };
      return api.post<AoiCheck>("/onboarding/aoi-check", body);
    },
  });
}

export function useCreateAndProcess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: IntakeCreateBody) => {
      const created = await api.post<IntakeView>("/onboarding", body, { idempotent: true });
      qc.setQueryData(onbKeys.intake(created.onboarding_id), created);
      try {
        const processing = await api.post<ProcessAccepted>(
          `/onboarding/${enc(created.onboarding_id)}/process`,
          { contract_version: "2.0.0" },
          { idempotent: true },
        );
        return { created, processing, processError: null as unknown };
      } catch (processError) {
        // The intake record exists; the screen shows it with the process error and a retry.
        return { created, processing: null, processError };
      }
    },
  });
}

export function useProcess(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<ProcessAccepted>(`/onboarding/${enc(id)}/process`, { contract_version: "2.0.0" }, { idempotent: true }),
    onSettled: () => qc.invalidateQueries({ queryKey: onbKeys.intake(id) }),
  });
}

export function useReview(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: ReviewBody; key: string }) =>
      api.patch<ReviewResult>(`/onboarding/${enc(id)}/review`, body, { idempotencyKey: key }),
    onSuccess: () => qc.invalidateQueries({ queryKey: onbKeys.intake(id) }),
  });
}

export function usePublish(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: PublishBody; key: string }) =>
      api.post<PublishResult>(`/onboarding/${enc(id)}/publish`, body, { idempotencyKey: key }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: onbKeys.intake(id) });
      void qc.invalidateQueries({ queryKey: ["pilots"] });
    },
  });
}
