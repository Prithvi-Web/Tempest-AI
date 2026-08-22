import { Link, useNavigate } from "react-router-dom";

import { useGetRun, useGetTarget } from "./hooks";
import { divergencePath, editorPath, runPath, runsPath } from "./routes";
import {
  ClassificationChip,
  VerdictChip,
  divergenceClassLabel,
  langLabel,
  reasonHint,
  severityLabel,
} from "./vocabulary";

export function TargetView({ id }: { id: number }) {
  const target = useGetTarget(id);
  const navigate = useNavigate();
  // The run carries the repository this target was proved in, the target carries the file inside
  // it. Both are needed to open the source, and no view held them together — which is why the
  // editor shipped with no way in except a hand-typed URL.
  const run = useGetRun(target.data?.run_id ?? 0);

  if (target.isLoading) return <p className="dim">loading target #{id}…</p>;
  if (target.isError) return <p className="yellow">could not load target #{id}</p>;
  const t = target.data;
  const repo = run.data?.repo;
  // float-over-JSON is number|null in the contract; coverage is always finite in practice
  const pct = Math.round((t.changed_line_coverage ?? 0) * 100);

  return (
    <main>
      <nav className="crumbs">
        <Link to={runsPath()}>Runs</Link> / <Link to={runPath(t.run_id)}>#{t.run_id}</Link> /{" "}
        {t.qualname}
      </nav>
      <div className="statusline">
        <h1>
          {t.module}.{t.qualname}
        </h1>
        <VerdictChip verdict={t.verdict} />
        <ClassificationChip classification={t.classification} />
        <span className="chip neutral">{langLabel(t.lang)}</span>
        {repo !== undefined && (
          <Link
            className="chip neutral"
            to={editorPath(repo, t.file_path)}
            data-testid="open-in-editor"
          >
            open {t.file_path}
          </Link>
        )}
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
                  onClick={() => navigate(divergencePath(d.id))}
                  onKeyDown={(e) => e.key === "Enter" && navigate(divergencePath(d.id))}
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
