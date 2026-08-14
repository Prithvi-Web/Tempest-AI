"use client";

import Link from "next/link";

import { ApiErrorPanel } from "@/components/api-error";
import { VerdictChip } from "@/components/chips";
import { useGetHealth, useListRuns } from "@/generated/hooks";
import { apiBaseUrl } from "@/lib/api-client";
import { formatUtc, shortSha } from "@/lib/format";
import { ALL_VERDICTS, runStatusLabel, type Verdict } from "@/lib/verdict";

export function RunsListView({ verdict, cursor }: { verdict?: Verdict; cursor?: string }) {
  const runs = useListRuns({ verdict, cursor });

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-lg font-bold tracking-tight">RUNS</h1>
        <HealthStrip />
      </div>

      <nav aria-label="Verdict filter" className="mt-4 flex flex-wrap items-baseline gap-2 text-xs">
        <span className="uppercase tracking-widest text-ink-dim">verdict:</span>
        <FilterLink href="/" active={verdict === undefined} label="all" />
        {ALL_VERDICTS.map((v) => (
          <FilterLink key={v} href={`/?verdict=${v}`} active={verdict === v} label={v} />
        ))}
      </nav>

      <section aria-label="Run list" className="mt-4">
        {runs.isPending ? (
          <p className="border border-panel-line bg-panel-raised p-4 text-sm text-ink-dim">
            loading runs…
          </p>
        ) : runs.isError ? (
          <ApiErrorPanel error={runs.error} context="run list" />
        ) : runs.data.items.length === 0 ? (
          <EmptyState verdict={verdict} filtered={verdict !== undefined || cursor !== undefined} />
        ) : (
          <>
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">Runs, newest first</caption>
              <thead>
                <tr className="border-b border-panel-line text-left text-[10px] uppercase tracking-widest text-ink-dim">
                  <th scope="col" className="py-2 pr-4 font-normal">run</th>
                  <th scope="col" className="py-2 pr-4 font-normal">repo</th>
                  <th scope="col" className="py-2 pr-4 font-normal">base → head</th>
                  <th scope="col" className="py-2 pr-4 font-normal">status</th>
                  <th scope="col" className="py-2 pr-4 font-normal">verdict</th>
                  <th scope="col" className="py-2 pr-4 text-right font-normal">targets</th>
                  <th scope="col" className="py-2 pr-4 text-right font-normal">divergences</th>
                  <th scope="col" className="py-2 font-normal">created (utc)</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((run) => (
                  <tr key={run.id} className="border-b border-panel-line hover:bg-panel-raised">
                    <td className="py-1.5 pr-4">
                      <Link
                        href={`/runs/${run.id}`}
                        className="text-ink underline-offset-2 hover:underline"
                      >
                        #{run.id}
                      </Link>
                    </td>
                    <td className="max-w-56 truncate py-1.5 pr-4" title={run.repo}>
                      {run.repo}
                    </td>
                    <td className="py-1.5 pr-4 text-ink-dim" title={`${run.base_sha} → ${run.head_sha}`}>
                      {shortSha(run.base_sha)} → {shortSha(run.head_sha)}
                    </td>
                    <td className="py-1.5 pr-4 text-ink-dim" title={runStatusLabel(run.status)}>
                      {run.status.toLowerCase()}
                    </td>
                    <td className="py-1.5 pr-4">
                      {run.verdict !== null ? (
                        <VerdictChip verdict={run.verdict} />
                      ) : (
                        <span className="text-ink-dim" title="no bundle ingested yet">—</span>
                      )}
                    </td>
                    <td className="py-1.5 pr-4 text-right tabular-nums">{run.target_count}</td>
                    <td
                      className={`py-1.5 pr-4 text-right tabular-nums ${
                        run.divergence_count > 0 ? "text-divergent" : "text-ink-dim"
                      }`}
                    >
                      {run.divergence_count}
                    </td>
                    <td className="py-1.5 tabular-nums text-ink-dim">{formatUtc(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex items-baseline gap-4 text-xs">
              {cursor !== undefined && (
                <Link
                  href={verdict !== undefined ? `/?verdict=${verdict}` : "/"}
                  className="text-ink-dim underline-offset-2 hover:text-ink hover:underline"
                >
                  ↩ newest
                </Link>
              )}
              {runs.data.next_cursor !== null && (
                <Link
                  href={`/?${new URLSearchParams({
                    ...(verdict !== undefined ? { verdict } : {}),
                    cursor: runs.data.next_cursor,
                  }).toString()}`}
                  className="text-ink-dim underline-offset-2 hover:text-ink hover:underline"
                >
                  older →
                </Link>
              )}
            </div>
          </>
        )}
      </section>
    </main>
  );
}

function FilterLink({ href, active, label }: { href: string; active: boolean; label: string }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`border px-1.5 py-px uppercase tracking-widest ${
        active
          ? "border-ink-dim bg-panel-raised text-ink"
          : "border-panel-line text-ink-dim hover:border-ink-dim hover:text-ink"
      }`}
    >
      {label}
    </Link>
  );
}

/** Honest empty states: no fake charts, no cheerleading — the exact commands that create data. */
function EmptyState({ verdict, filtered }: { verdict?: Verdict; filtered: boolean }) {
  if (filtered) {
    return (
      <div className="border border-panel-line bg-panel-raised p-4 text-sm">
        <p className="text-ink-dim">
          no runs{verdict !== undefined ? ` with verdict ${verdict}` : ""} on this page.
        </p>
        <p className="mt-2 text-xs">
          <Link href="/" className="text-ink underline-offset-2 hover:underline">
            clear filter ↩
          </Link>
        </p>
      </div>
    );
  }
  return (
    <div className="border border-panel-line bg-panel-raised p-4 text-sm">
      <p className="text-xs uppercase tracking-widest text-ink-dim">no runs recorded</p>
      <p className="mt-2 text-ink">
        This dashboard renders CLI-produced run bundles verbatim — it never re-derives verdicts.
        Produce evidence in your repo:
      </p>
      <pre className="mt-3 overflow-x-auto border border-panel-line bg-panel p-3 text-xs leading-relaxed text-ink">
        {`$ tempest prove --base main --head HEAD
    # runs base and head side by side under identical conditions,
    # writes <run>.tempest.zip, exits 1 on DIVERGENT`}
      </pre>
      <p className="mt-3 text-ink">then register the run and upload its bundle:</p>
      <pre className="mt-2 overflow-x-auto border border-panel-line bg-panel p-3 text-xs leading-relaxed text-ink">
        {`$ curl -sX POST ${apiBaseUrl}/v1/runs \\
    -H 'content-type: application/json' \\
    -d '{"repo":"<name>","base_sha":"<40-hex>","head_sha":"<40-hex>"}'   # → {"run_id": N}
$ curl -sX POST ${apiBaseUrl}/v1/runs/<run_id>/bundle -F file=@<run>.tempest.zip`}
      </pre>
    </div>
  );
}

function HealthStrip() {
  const health = useGetHealth();
  return (
    <p aria-label="API status" className="text-xs">
      <span className="text-ink-dim">api </span>
      {health.isPending ? (
        <span className="text-ink-dim">checking…</span>
      ) : health.isError ? (
        <span className="text-unproven">
          unreachable — run `docker compose up` (see docker/)
        </span>
      ) : (
        <span className="text-equivalent">
          ok · engine {health.data.engine_version} · bundle schema v{health.data.schema_version}
        </span>
      )}
    </p>
  );
}
