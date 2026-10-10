import { useQueryClient } from "@tanstack/react-query";
import { useHealth } from "@/lib/api/queries";
import { BACKEND_ORIGIN } from "@/lib/api/urls";
import { Button, buttonClass } from "@/components/ui/Button";

/** Edge login redirects cannot be completed by a cross-origin fetch. */
export function BackendConnection() {
  const health = useHealth();
  const client = useQueryClient();
  if (!BACKEND_ORIGIN || health.isLoading || (!health.error && health.data?.status === "ok")) return null;
  const login = `${BACKEND_ORIGIN}/api/v2/access/ready?${new URLSearchParams({ return_to: window.location.href })}`;
  return (
    <section role="alert" aria-label="Backend connection" className="relative z-40 flex flex-wrap items-center justify-center gap-3 border-b border-border bg-surface px-4 py-3">
      <div className="max-w-[64ch] text-sm text-ink-secondary">
        <p className="font-semibold text-ink">Connect to the laptop backend</p>
        <p>Sign in with your approved email to load maps and saved results. If you already signed in, retry the connection. The serving laptop must be awake and online.</p>
      </div>
      <a href={login} className={buttonClass("primary", "sm")}>Sign in to backend</a>
      <Button size="sm" onClick={() => void client.invalidateQueries()}>Retry connection</Button>
    </section>
  );
}
