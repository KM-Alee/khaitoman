import { lazy, Suspense, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router";
import { TooltipProvider } from "@/components/ui/primitives";
import { ToastRegion } from "@/components/ui/Toast";
import { AppShell } from "@/components/layout/AppShell";
import { Skeleton } from "@/components/status";
import { useDocumentFlags } from "./environment";
import { HomeRedirect } from "./HomeRedirect";
import { WorkspaceScreen } from "@/features/workspace/WorkspaceScreen";
import { SCREENS, type Screen } from "./selection";
import { TourHost } from "@/features/tour/TourHost";
import { BackendConnection } from "@/components/layout/BackendConnection";

const CompareScreen = lazy(() => import("@/features/compare/CompareScreen").then((m) => ({ default: m.CompareScreen })));
const ReplayScreen = lazy(() => import("@/features/compare/ReplayScreen").then((m) => ({ default: m.ReplayScreen })));
const ExploreScreen = lazy(() => import("@/features/explore/ExploreScreen").then((m) => ({ default: m.ExploreScreen })));
const ImpactScreen = lazy(() => import("@/features/impact/ImpactScreen").then((m) => ({ default: m.ImpactScreen })));
const ReportScreen = lazy(() => import("@/features/impact/ReportScreen").then((m) => ({ default: m.ReportScreen })));
const EvidenceScreen = lazy(() => import("@/features/evidence/EvidenceScreen").then((m) => ({ default: m.EvidenceScreen })));
const PlanSeasonScreen = lazy(() => import("@/features/planner/PlanSeasonScreen").then((m) => ({ default: m.PlanSeasonScreen })));
const OnboardingScreen = lazy(() => import("@/features/onboarding/OnboardingScreen").then((m) => ({ default: m.OnboardingScreen })));

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 15_000 } },
  });
}

function ScreenFallback() {
  return (
    <div className="flex flex-1 flex-col gap-3 p-4" aria-busy>
      <Skeleton className="h-10 w-1/3" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function PilotRoute() {
  const { screen } = useParams();
  const s = (SCREENS.includes(screen as Screen) ? screen : null) as Screen | null;
  if (!s) return <Navigate to="../workspace" relative="path" replace />;
  return (
    <AppShell>
      <Suspense fallback={<ScreenFallback />}>
        {s === "workspace" ? <WorkspaceScreen /> : null}
        {s === "compare" ? <CompareScreen /> : null}
        {s === "replay" ? <ReplayScreen /> : null}
        {s === "explore" ? <ExploreScreen /> : null}
        {s === "impact" ? <ImpactScreen /> : null}
        {s === "report" ? <ReportScreen /> : null}
        {s === "evidence" ? <EvidenceScreen /> : null}
      </Suspense>
    </AppShell>
  );
}

function Flags() {
  useDocumentFlags();
  return null;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<HomeRedirect />} />
      <Route path="/p/:pilotId/:version" element={<Navigate to="workspace" replace />} />
      <Route
        path="/p/:pilotId/:version/plan-season"
        element={
          <Suspense fallback={<ScreenFallback />}>
            <PlanSeasonScreen />
          </Suspense>
        }
      />
      <Route path="/p/:pilotId/:version/:screen" element={<PilotRoute />} />
      <Route
        path="/onboarding/:intakeId?"
        element={
          <Suspense fallback={<ScreenFallback />}>
            <OnboardingScreen />
          </Suspense>
        }
      />
      <Route path="*" element={<HomeRedirect notFound />} />
    </Routes>
  );
}

export function App({ client }: { client?: QueryClient }) {
  const [qc] = useState(() => client ?? makeQueryClient());
  return (
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={250}>
        <BrowserRouter>
          <Flags />
          <BackendConnection />
          <AppRoutes />
          <TourHost />
        </BrowserRouter>
        <ToastRegion />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
