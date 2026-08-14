"use client";

import Link from "next/link";

import { ApiErrorPanel } from "@/components/api-error";
import { SeverityChip } from "@/components/chips";
import { CopyButton } from "@/components/copy-button";
import {
  urlForGetDivergenceRepro,
  useGetDivergence,
  useGetDivergenceRepro,
  useGetTarget,
} from "@/generated/hooks";
import { divergenceClassNote } from "@/lib/verdict";

export function DivergenceDetailView({ divergenceId }: { divergenceId: number }) {
  const divergence = useGetDivergence(divergenceId);

  if (divergence.isPending) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-8">
        <p className="border border-panel-line bg-panel-raised p-4 text-sm text-ink-dim">
          loading divergence #{divergenceId}…
        </p>
      </main>
    );
  }
  if (divergence.isError) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-8">
        <ApiErrorPanel error={divergence.error} context={`divergence #${divergenceId}`} />
      </main>
    );
  }

  const d = divergence.data;

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <nav aria-label="Breadcrumb" className="text-xs text-ink-dim">
        <Link href="/" className="underline-offset-2 hover:text-ink hover:underline">
          runs
        </Link>{" "}
        /{" "}
        <Link href={`/runs/${d.run_id}`} className="underline-offset-2 hover:text-ink hover:underline">
          #{d.run_id}
        </Link>{" "}
        / <TargetCrumb targetId={d.target_id} /> / divergence #{d.id}
      </nav>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-2">
        <h1 className="text-lg font-bold tracking-tight">divergence #{d.id}</h1>
        <span
          className="inline-block whitespace-nowrap border border-divergent px-1.5 py-px text-[10px] uppercase tracking-widest text-divergent"
          title={divergenceClassNote(d.divergence_class)}
        >
          {d.divergence_class}
        </span>
        <SeverityChip severity={d.severity} />
      </div>
      <p className="mt-1 text-sm text-ink">{d.detail}</p>
      <p className="mt-0.5 text-xs text-ink-dim">{divergenceClassNote(d.divergence_class)}</p>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <section aria-label="Minimized input" className="border border-panel-line bg-panel-raised">
          <header className="flex items-baseline justify-between border-b border-panel-line px-3 py-2">
            <h2 className="text-xs uppercase tracking-widest text-ink-dim">minimized input</h2>
            <span className="text-[10px] text-ink-dim">
              smallest input still producing this divergence
            </span>
          </header>
          <div className="space-y-3 p-3">
            <LiteralRow label="args" value={d.minimized_args} />
            <LiteralRow label="kwargs" value={d.minimized_kwargs} />
          </div>
        </section>

        <section aria-label="Observed behavior" className="border border-panel-line bg-panel-raised">
          <header className="border-b border-panel-line px-3 py-2">
            <h2 className="text-xs uppercase tracking-widest text-ink-dim">
              observed behavior, identical conditions
            </h2>
          </header>
          <div className="grid gap-3 p-3 sm:grid-cols-2">
            <div>
              <h3 className="text-[10px] uppercase tracking-widest text-ink-dim">base</h3>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap border border-panel-line bg-panel p-2 text-xs leading-relaxed text-ink">
                {d.base_summary}
              </pre>
            </div>
            <div>
              <h3 className="text-[10px] uppercase tracking-widest text-divergent">head</h3>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap border border-panel-line bg-panel p-2 text-xs leading-relaxed text-ink">
                {d.head_summary}
              </pre>
            </div>
          </div>
        </section>
      </div>

      <ReproSection divergenceId={d.id} filename={d.repro_filename} />

      <details className="mt-4 border border-panel-line bg-panel-raised">
        <summary className="cursor-pointer px-3 py-2 text-xs uppercase tracking-widest text-ink-dim hover:text-ink">
          original input + shrink path
        </summary>
        <div className="space-y-3 border-t border-panel-line p-3">
          <LiteralRow label="original args" value={d.args_literal} />
          <LiteralRow label="original kwargs" value={d.kwargs_literal} />
          <div>
            <h3 className="text-[10px] uppercase tracking-widest text-ink-dim">
              shrink path — accepted reduction steps
            </h3>
            {d.shrink_path.length === 0 ? (
              <p className="mt-1 text-xs text-ink-dim">
                already minimal — no reduction step was accepted
              </p>
            ) : (
              <ol className="mt-1 list-decimal space-y-1 pl-6 text-xs text-ink">
                {d.shrink_path.map((step, i) => (
                  <li key={i}>
                    <code className="whitespace-pre-wrap">{step}</code>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      </details>
    </main>
  );
}

function LiteralRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-[10px] uppercase tracking-widest text-ink-dim">{label}</h3>
        <CopyButton text={value} />
      </div>
      <pre className="mt-1 overflow-x-auto border border-panel-line bg-panel p-2 text-xs leading-relaxed text-ink">
        {value}
      </pre>
    </div>
  );
}

/** Fetched separately so the crumb can name the function; falls back to the bare id. */
function TargetCrumb({ targetId }: { targetId: number }) {
  const target = useGetTarget(targetId);
  return (
    <Link
      href={`/targets/${targetId}`}
      className="underline-offset-2 hover:text-ink hover:underline"
    >
      {target.isSuccess ? target.data.qualname : `target #${targetId}`}
    </Link>
  );
}

function ReproSection({ divergenceId, filename }: { divergenceId: number; filename: string }) {
  const repro = useGetDivergenceRepro(divergenceId);
  return (
    <section aria-label="Reproduction script" className="mt-4 border border-panel-line bg-panel-raised">
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-panel-line px-3 py-2">
        <h2 className="text-xs uppercase tracking-widest text-ink-dim">
          reproduction script <span className="normal-case tracking-normal">· {filename}</span>
        </h2>
        <span className="flex items-center gap-2">
          {repro.isSuccess && <CopyButton text={repro.data} />}
          <a
            href={urlForGetDivergenceRepro(divergenceId)}
            download={filename}
            className="border border-panel-line px-2 py-0.5 text-[10px] uppercase tracking-widest text-ink-dim hover:border-ink-dim hover:text-ink"
          >
            download
          </a>
        </span>
      </header>
      {repro.isPending ? (
        <p className="p-3 text-xs text-ink-dim">fetching repro script…</p>
      ) : repro.isError ? (
        <div className="p-3">
          <ApiErrorPanel error={repro.error} context="repro script" />
        </div>
      ) : (
        <pre className="max-h-[30rem] overflow-auto p-3 text-xs leading-relaxed text-ink">
          {repro.data}
        </pre>
      )}
      <footer className="border-t border-panel-line px-3 py-2 text-[10px] text-ink-dim">
        standalone — run it yourself; a divergence you cannot re-run is worthless (L7)
      </footer>
    </section>
  );
}
