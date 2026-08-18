import { useGetTarget } from "../hooks";
import {
  ClassificationChip,
  VerdictChip,
  divergenceClassLabel,
  langLabel,
  reasonHint,
  severityLabel,
} from "../vocabulary";

import type { Route } from "../router";

export function TargetView({ id, navigate }: { id: number; navigate: (r: Route) => void }) {
  const target = useGetTarget(id);

  if (target.isPending) return <p className="dim">loading target #{id}…</p>;
  if (target.isError) return <p className="yellow">could not load target #{id}</p>;
  const t = target.data;
  // float-over-JSON is number|null in the contract; coverage is always finite in practice
  const pct = Math.round((t.changed_line_coverage ?? 0) * 100);

  return (
    <main>
      <nav className="crumbs">
        <a
          href="?"
          onClick={(e) => {
            e.preventDefault();
            navigate({ view: "runs" });
          }}
        >
          Runs
        </a>{" "}
        /{" "}
        <a
          href={`?view=run&id=${t.run_id}`}
          onClick={(e) => {
            e.preventDefault();
            navigate({ view: "run", id: t.run_id });
          }}
        >
          #{t.run_id}
        </a>{" "}
        / {t.qualname}
      </nav>
      <div className="statusline">
        <h1>
          {t.module}.{t.qualname}
        </h1>
        <VerdictChip verdict={t.verdict} />
        <ClassificationChip classification={t.classification} />
        <span className="chip neutral">{langLabel(t.lang)}</span>
      </div>

      {t.verdict === "UNPROVEN" && (
        <div className="panel notproven">
          <strong className="yellow">⚠ {t.reason_code}</strong>
          <p>{t.reason_detail}</p>
          {t.reason_code !== null && (
            <p className="dim" style={{ marginBottom: 0 }}>
              {reasonHint(t.reason_code)}
            </p>
          )}
        </div>
      )}

      <h2>Changed-line coverage</h2>
      <div className="bar" style={{ maxWidth: 420 }}>
        <i className={pct >= 100 ? "full" : ""} style={{ width: `${pct}%` }} />
      </div>
      <p className="dim">
        {pct}% of this symbol's changed lines actually executed
        {pct < 100 ? " — unexecuted lines are unproven territory, stated honestly" : ""}
      </p>

      <h2>Inputs</h2>
      <p>
        {t.inputs_run} run · <span className="green">{t.equivalent_inputs} equivalent</span> ·{" "}
        <span className="red">{t.divergences.length} divergent</span> ·{" "}
        <span className="yellow">{t.unprovable_inputs} unprovable</span>
      </p>

      {t.divergences.length > 0 && (
        <>
          <h2>Divergences</h2>
          <table>
            <tbody>
              {t.divergences.map((d) => (
                <tr
                  key={d.id}
                  className="rowlink"
                  tabIndex={0}
                  onClick={() => navigate({ view: "divergence", id: d.id })}
                  onKeyDown={(e) =>
                    e.key === "Enter" && navigate({ view: "divergence", id: d.id })
                  }
                >
                  <td>
                    <span className="chip DIVERGENT" title={divergenceClassLabel(d.divergence_class)}>
                      {d.divergence_class}
                    </span>
                  </td>
                  <td className="mono">{d.minimized_args}</td>
                  <td className="dim" title={severityLabel(d.severity)}>
                    {d.severity}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
