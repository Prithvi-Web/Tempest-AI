"use client";

import { useGetHealth } from "@/generated/hooks";

export default function Home() {
  const health = useGetHealth();

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-2xl font-bold tracking-tight">TEMPEST</h1>
      <p className="mt-1 text-sm text-ink-dim">
        Behavioral proof agent. Evidence, not opinion.
      </p>

      <section
        aria-label="API status"
        className="mt-10 border border-panel-line bg-panel-raised p-4 text-sm"
      >
        <div className="flex items-center justify-between">
          <span className="text-ink-dim">api</span>
          {health.isPending ? (
            <span className="text-ink-dim">checking…</span>
          ) : health.isError ? (
            <span className="text-unproven">unreachable — run `docker compose up` (see docker/)</span>
          ) : (
            <span className="text-equivalent">
              ok · engine {health.data.engine_version} · bundle schema v{health.data.schema_version}
            </span>
          )}
        </div>
      </section>

      <p className="mt-10 text-xs text-ink-dim">
        Run history appears here once the dashboard lands (Phase 5 — docs/PLAN.md). Until then, the
        CLI is the product: <code className="text-ink">tempest prove --base main --head HEAD</code>
      </p>
    </main>
  );
}
