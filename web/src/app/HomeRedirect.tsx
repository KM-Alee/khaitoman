import { usePilots } from "@/lib/api/queries";
import { Landing } from "@/features/landing/Landing";

/**
 * `/` always shows the landing page: what AabFlow is, the guided tour and the published
 * watercourses (each card opens its Plan step). Unknown paths land here with a notice.
 */
export function HomeRedirect({ notFound }: { notFound?: boolean }) {
  const pilots = usePilots();
  return <Landing pilots={pilots} notFound={notFound} />;
}
