import { useEffect, useState } from "react";

type Health = { status: string; contract_version: string };

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v2/health")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <main className="p-6 font-sans">
      <h1 className="text-2xl font-semibold">AabFlow</h1>
      <p data-testid="health">
        {error ? `API unavailable: ${error}` : health ? `API ${health.status} (contract ${health.contract_version})` : "Checking API…"}
      </p>
    </main>
  );
}
