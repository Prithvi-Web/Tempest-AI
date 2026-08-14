"use client";

import Link from "next/link";

import { ApiErrorPanel } from "@/components/api-error";
import { LangBadge, SeverityChip, VerdictChip } from "@/components/chips";
import { CoverageBar } from "@/components/coverage-bar";
import { useGetTarget } from "@/generated/hooks";
import { truncate } from "@/lib/format";
import { classificationNote, divergenceClassNote, reasonCodeHint } from "@/lib/verdict";

export function TargetDetailView({ targetId }: { targetId: number }) {
  const target = useGetTarget(targetId);

  if (target.isPending) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-8">
        <p className="border border-panel-line bg-panel-raised p-4 text-sm text-ink-dim">
          loading target #{targetId}…
        </p>
      </main>
    );
  }
  if (target.isError) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-8">
        <ApiErrorPanel error={target.error} context={`target #${targetId}`} />
      </main>
    );
  }

  const t = target.data;

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <nav aria-label="Breadcrumb" className="text-xs text-ink-dim">
        <Link href="/" className="underline-offset-2 hover:text-ink hover:underline">
          runs
        </Link>{" "}
        /{" "}
        <Link href={`/runs/${t.run_id}`} className="underline-offset-2 hover:text-ink hover:underline">
          #{t.run_id}
        </Link>{" "}
        / target #{t.id}
      </nav>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-2">
        <h1 className="text-lg font-bold tracking-tight">{t.qualname}</h1>
        <LangBadge lang={t.lang} />
        <VerdictChip verdict={t.verdict} />
      </div>
      <p className="mt-1 text-xs text-ink-dim">
        {t.file_path} · module {t.module}
      </p>
      <p className="mt-0.5 text-xs text-ink-dim">
        {t.classification} — {classificationNote(t.classification)}
      </p>

      {t.verdict === "UNPROVEN" && (
        <section aria-label="Not proven" className="mt-5 border-2 border-unproven bg-unproven/10 p-4">
          <h2 className="text-base font-bold uppercase tracking-widest text-unproven">
            NOT PROVEN{t.reason_code !== null ? ` — ${t.reason_code}` : ""}
          </h2>
          <p className="mt-2 text-sm text-ink">
            {t.reason_detail ?? "no reason detail recorded"}
          </p>
          {t.reason_code !== null && (
            <p className="mt-1 text-xs text-ink-dim">{reasonCodeHint(t.reason_code)}</p>
          )}
        </section>
      )}

      {t.verdict === "ERROR" && (
        <section aria-label="Tempest error" className="mt-5 border border-error bg-panel-raised p-4">
          <h2 className="text-sm font-bold uppercase tracking-widest text-error">TEMPEST ERROR</h2>
          <p className="mt-2 text-sm text-ink">
            {t.reason_detail ?? "Tempest itself failed on this target — see the run bundle trace"}
          </p>
        </section>
      )}

      <section aria-label="Evidence" className="mt-6 border border-panel-line bg-panel-raised p-4">
        <h2 className="text-xs uppercase tracking-widest text-ink-dim">what was exercised</h2>
        <div className="mt-2">
          <CoverageBar fraction={t.changed_line_coverage} wide />
          <p className="mt-1 text-[10px] text-ink-dim">
            changed-line coverage — the fraction of this symbol&apos;s changed lines actually
            executed; unexecuted lines prove nothing
          </p>
        </div>
        <p className="mt-3 text-sm tabular-nums">
          <span className="text-ink">{t.inputs_run} inputs run</span>
          <span className="text-ink-dim"> · </span>
          <span className="text-equivalent">{t.equivalent_inputs} equivalent</span>
          <span className="text-ink-dim"> · </span>
          <span className="text-divergent">{t.divergence_count} divergent</span>
          <span className="text-ink-dim"> · </span>
          <span className="text-unproven">{t.unprovable_inputs} unprovable</span>
        </p>
      </section>

      <section aria-label="Divergences" className="mt-6">
        <h2 className="text-xs uppercase tracking-widest text-ink-dim">
          divergences · {t.divergences.length}
        </h2>
        {t.divergences.length === 0 ? (
          <p className="mt-2 border border-panel-line bg-panel-raised p-4 text-sm text-ink-dim">
            {t.verdict === "EQUIVALENT_UNDER_BUDGET"
              ? `0 divergences across ${t.inputs_run} inputs — equivalent under this budget, which is not “correct” (L2)`
              : "no differential evidence — this target was not exercised to a comparison"}
          </p>
        ) : (
          <table className="mt-2 w-full border-collapse text-sm">
            <caption className="sr-only">Divergences for {t.qualname}</caption>
            <thead>
              <tr className="border-b border-panel-line text-left text-[10px] uppercase tracking-widest text-ink-dim">
                <th scope="col" className="py-2 pr-4 font-normal">id</th>
                <th scope="col" className="py-2 pr-4 font-normal">class</th>
                <th scope="col" className="py-2 pr-4 font-normal">severity</th>
                <th scope="col" className="py-2 pr-4 font-normal">minimized input</th>
                <th scope="col" className="py-2 font-normal">detail</th>
              </tr>
            </thead>
            <tbody>
              {t.divergences.map((d) => (
                <tr key={d.id} className="border-b border-panel-line hover:bg-panel-raised">
                  <td className="py-1.5 pr-4">
                    <Link
                      href={`/divergences/${d.id}`}
                      className="text-ink underline-offset-2 hover:underline"
                    >
                      #{d.id}
                    </Link>
                  </td>
                  <td className="py-1.5 pr-4">
                    <span
                      className="inline-block whitespace-nowrap border border-divergent px-1.5 py-px text-[10px] uppercase tracking-widest text-divergent"
                      title={divergenceClassNote(d.divergence_class)}
                    >
                      {d.divergence_class}
                    </span>
                  </td>
                  <td className="py-1.5 pr-4">
                    <SeverityChip severity={d.severity} />
                  </td>
                  <td
                    className="max-w-56 truncate py-1.5 pr-4 text-ink"
                    title={`args=${d.minimized_args} kwargs=${d.minimized_kwargs}`}
                  >
                    <code>{truncate(`${d.minimized_args} ${d.minimized_kwargs}`, 60)}</code>
                  </td>
                  <td className="max-w-80 truncate py-1.5 text-ink-dim" title={d.detail}>
                    {truncate(d.detail, 100)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
