"use client";

import Link from "next/link";
import type { components } from "@tempest/shared-schema/types";

import { ApiErrorPanel } from "@/components/api-error";
import { LangBadge, VerdictChip } from "@/components/chips";
import { CoverageBar } from "@/components/coverage-bar";
import { useGetRun } from "@/generated/hooks";
import { formatUtc, shortSha } from "@/lib/format";
import {
  ALL_CLASSIFICATIONS,
  classificationNote,
  reasonCodeHint,
  runStatusLabel,
  type TargetClassification,
  type Verdict,
} from "@/lib/verdict";

type TargetSummary = components["schemas"]["TargetSummary"];

export function RunDetailView({ runId }: { runId: number }) {
  const run = useGetRun(runId);

  if (run.isPending) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-8">
        <p className="border border-panel-line bg-panel-raised p-4 text-sm text-ink-dim">
          loading run #{runId}…
        </p>
      </main>
    );
  }
  if (run.isError) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-8">
        <ApiErrorPanel error={run.error} context={`run #${runId}`} />
      </main>
    );
  }

  const data = run.data;
  const groups: Record<TargetClassification, TargetSummary[]> = {
    PURE_CANDIDATE: [],
    IMPURE_RECORDABLE: [],
    UNREACHABLE: [],
  };
  const verdictCounts: Record<Verdict, number> = {
    DIVERGENT: 0,
    EQUIVALENT_UNDER_BUDGET: 0,
    UNPROVEN: 0,
    ERROR: 0,
  };
  for (const target of data.targets) {
    groups[target.classification].push(target);
    verdictCounts[target.verdict] += 1;
  }
  const unproven = data.targets.filter((t) => t.verdict === "UNPROVEN");
  const errored = data.targets.filter((t) => t.verdict === "ERROR");
  const depsMismatch =
    data.base_deps !== null && data.head_deps !== null && data.base_deps !== data.head_deps;

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <nav aria-label="Breadcrumb" className="text-xs text-ink-dim">
        <Link href="/" className="underline-offset-2 hover:text-ink hover:underline">
          runs
        </Link>{" "}
        / #{data.id}
      </nav>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <h1 className="text-lg font-bold tracking-tight">
          run #{data.id} · {data.repo}
        </h1>
        {data.verdict !== null ? (
          <VerdictChip verdict={data.verdict} />
        ) : (
          <span className="text-xs text-ink-dim">no verdict — {runStatusLabel(data.status)}</span>
        )}
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-8 gap-y-1 text-xs sm:grid-cols-3 lg:grid-cols-4">
        <MetaRow label="base → head">
          <span title={`${data.base_sha} → ${data.head_sha}`}>
            {shortSha(data.base_sha)} → {shortSha(data.head_sha)}
          </span>
        </MetaRow>
        <MetaRow label="created (utc)">{formatUtc(data.created_at)}</MetaRow>
        <MetaRow label="engine">{data.engine_version ?? "—"}</MetaRow>
        <MetaRow label="bundle schema">
          {data.schema_version !== null ? `v${data.schema_version}` : "—"}
        </MetaRow>
        <MetaRow label="input budget / target">
          {data.budget_max_inputs !== null ? data.budget_max_inputs : "—"}
        </MetaRow>
        <MetaRow label="bundle created">
          {data.bundle_created_at !== null ? formatUtc(data.bundle_created_at) : "—"}
        </MetaRow>
      </dl>

      {depsMismatch ? (
        <p className="mt-3 border border-unproven bg-panel-raised p-3 text-xs text-unproven">
          DEPENDENCY FINGERPRINTS DIFFER — base {data.base_deps} · head {data.head_deps}.
          Divergence may be dependency-induced; that is a finding, not noise.
        </p>
      ) : data.base_deps !== null ? (
        <p className="mt-3 text-xs text-ink-dim">deps {data.base_deps}</p>
      ) : null}

      <p className="mt-4 text-sm tabular-nums">
        <span className="text-divergent">{verdictCounts.DIVERGENT} divergent</span>
        <span className="text-ink-dim"> · </span>
        <span className="text-equivalent">
          {verdictCounts.EQUIVALENT_UNDER_BUDGET} equivalent-under-budget
        </span>
        <span className="text-ink-dim"> · </span>
        <span className="text-unproven">{verdictCounts.UNPROVEN} unproven</span>
        <span className="text-ink-dim"> · </span>
        <span className="text-error">{verdictCounts.ERROR} error</span>
        <span className="text-ink-dim">
          {" "}
          — {data.divergence_count} divergence{data.divergence_count === 1 ? "" : "s"} across{" "}
          {data.target_count} target{data.target_count === 1 ? "" : "s"}
        </span>
      </p>

      {unproven.length > 0 && (
        <section
          aria-label="Not proven"
          className="mt-6 border-2 border-unproven bg-unproven/10 p-4"
        >
          <h2 className="text-base font-bold uppercase tracking-widest text-unproven">
            NOT PROVEN — {unproven.length} of {data.target_count} target
            {data.target_count === 1 ? "" : "s"} could not be exercised
          </h2>
          <p className="mt-1 text-xs text-ink-dim">
            A change Tempest could not run is never blessed. Each reason below is the blocker to
            fix; the target page carries the full detail.
          </p>
          <ul className="mt-3 space-y-3">
            {unproven.map((target) => (
              <li key={target.id} className="border border-panel-line bg-panel p-3 text-sm">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <Link
                    href={`/targets/${target.id}`}
                    className="font-bold text-ink underline-offset-2 hover:underline"
                  >
                    {target.qualname}
                  </Link>
                  <span className="text-xs text-ink-dim">{target.file_path}</span>
                  {target.reason_code !== null && (
                    <span className="border border-unproven px-1.5 py-px text-[10px] uppercase tracking-widest text-unproven">
                      {target.reason_code}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-ink-dim">
                  {target.reason_code !== null
                    ? reasonCodeHint(target.reason_code)
                    : "no reason code recorded"}
                  {" — "}
                  <Link
                    href={`/targets/${target.id}`}
                    className="text-ink underline-offset-2 hover:underline"
                  >
                    full reason detail →
                  </Link>
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {errored.length > 0 && (
        <section aria-label="Tempest errors" className="mt-4 border border-error bg-panel-raised p-4">
          <h2 className="text-sm font-bold uppercase tracking-widest text-error">
            TEMPEST ERROR — {errored.length} target{errored.length === 1 ? "" : "s"}
          </h2>
          <p className="mt-1 text-xs text-ink-dim">
            Tempest itself failed here; this says nothing about the change.
          </p>
          <ul className="mt-2 space-y-1 text-sm">
            {errored.map((target) => (
              <li key={target.id}>
                <Link
                  href={`/targets/${target.id}`}
                  className="text-ink underline-offset-2 hover:underline"
                >
                  {target.qualname}
                </Link>{" "}
                <span className="text-xs text-ink-dim">{target.file_path}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.targets.length === 0 ? (
        <div className="mt-6 border border-panel-line bg-panel-raised p-4 text-sm">
          <p className="text-xs uppercase tracking-widest text-ink-dim">no targets yet</p>
          <p className="mt-2 text-ink">
            {runStatusLabel(data.status)}. Upload the CLI bundle:{" "}
            <code className="text-ink-dim">
              curl -sX POST …/v1/runs/{data.id}/bundle -F file=@&lt;run&gt;.tempest.zip
            </code>
          </p>
        </div>
      ) : (
        ALL_CLASSIFICATIONS.map((classification) => {
          const targets = groups[classification];
          if (targets.length === 0) return null;
          return (
            <section key={classification} aria-label={classification} className="mt-8">
              <h2 className="text-xs uppercase tracking-widest text-ink-dim">
                {classification}{" "}
                <span className="normal-case tracking-normal">
                  · {classificationNote(classification)} · {targets.length}
                </span>
              </h2>
              <table className="mt-2 w-full border-collapse text-sm">
                <caption className="sr-only">Targets classified {classification}</caption>
                <thead>
                  <tr className="border-b border-panel-line text-left text-[10px] uppercase tracking-widest text-ink-dim">
                    <th scope="col" className="py-2 pr-4 font-normal">target</th>
                    <th scope="col" className="py-2 pr-4 font-normal">file</th>
                    <th scope="col" className="py-2 pr-4 font-normal">lang</th>
                    <th scope="col" className="py-2 pr-4 font-normal">verdict</th>
                    <th scope="col" className="py-2 pr-4 font-normal">changed-line coverage</th>
                    <th scope="col" className="py-2 pr-4 text-right font-normal">divergences</th>
                    <th scope="col" className="py-2 font-normal">reason</th>
                  </tr>
                </thead>
                <tbody>
                  {targets.map((target) => (
                    <tr key={target.id} className="border-b border-panel-line hover:bg-panel-raised">
                      <td className="py-1.5 pr-4">
                        <Link
                          href={`/targets/${target.id}`}
                          className="text-ink underline-offset-2 hover:underline"
                        >
                          {target.qualname}
                        </Link>
                      </td>
                      <td
                        className="max-w-64 truncate py-1.5 pr-4 text-ink-dim"
                        title={`${target.file_path} · ${target.module}`}
                      >
                        {target.file_path}
                      </td>
                      <td className="py-1.5 pr-4">
                        <LangBadge lang={target.lang} />
                      </td>
                      <td className="py-1.5 pr-4">
                        <VerdictChip verdict={target.verdict} />
                      </td>
                      <td className="py-1.5 pr-4">
                        <CoverageBar fraction={target.changed_line_coverage} />
                      </td>
                      <td
                        className={`py-1.5 pr-4 text-right tabular-nums ${
                          target.divergence_count > 0 ? "text-divergent" : "text-ink-dim"
                        }`}
                      >
                        {target.divergence_count}
                      </td>
                      <td className="py-1.5 text-xs text-ink-dim">{target.reason_code ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          );
        })
      )}
    </main>
  );
}

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="uppercase tracking-widest text-ink-dim">{label}</dt>
      <dd className="tabular-nums text-ink">{children}</dd>
    </div>
  );
}
