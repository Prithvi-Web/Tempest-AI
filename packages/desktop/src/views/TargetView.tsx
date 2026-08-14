import { useGetTarget } from "../hooks";

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
          runs
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
        <span className={`chip ${t.verdict}`}>{t.verdict}</span>
        <span className="chip neutral">{t.classification}</span>
      </div>

      {t.verdict === "UNPROVEN" && (
        <div className="panel notproven">
          <strong className="yellow">⚠ {t.reason_code}</strong>
          <p style={{ marginBottom: 0 }}>{t.reason_detail}</p>
        </div>
      )}

      <h2>changed-line coverage</h2>
      <div className="bar" style={{ maxWidth: 420 }}>
        <i className={pct >= 100 ? "full" : ""} style={{ width: `${pct}%` }} />
      </div>
      <p className="dim">
        {pct}% of this symbol's changed lines actually executed
        {pct < 100 ? " — unexecuted lines are unproven territory, stated honestly" : ""}
      </p>

      <h2>inputs</h2>
      <p>
        {t.inputs_run} run · <span className="green">{t.equivalent_inputs} equivalent</span> ·{" "}
        <span className="red">{t.divergences.length} divergent</span> ·{" "}
        <span className="yellow">{t.unprovable_inputs} unprovable</span>
      </p>

      {t.divergences.length > 0 && (
        <>
          <h2>divergences</h2>
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
                    <span className="chip DIVERGENT">{d.divergence_class}</span>
                  </td>
                  <td className="mono-cell">{d.minimized_args}</td>
                  <td className="dim">{d.severity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
