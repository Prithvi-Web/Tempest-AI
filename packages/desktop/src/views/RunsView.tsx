import { useListRuns } from "../hooks";

import type { Route } from "../router";

export function RunsView({ navigate }: { navigate: (r: Route) => void }) {
  const runs = useListRuns({});

  return (
    <main>
      <div className="statusline">
        <h1 style={{ flex: 1 }}>RUNS</h1>
        <button className="primary" onClick={() => navigate({ view: "prove" })}>
          NEW PROOF
        </button>
      </div>
      {runs.isPending && <p className="dim">loading…</p>}
      {runs.isError && (
        <p className="yellow">could not load runs — the engine may still be starting</p>
      )}
      {runs.data && runs.data.items.length === 0 && (
        <div className="panel">
          <p className="dim">
            No runs yet. Click <span className="yellow">NEW PROOF</span> to execute a repository's
            base and head side by side and see where behavior diverges — with evidence.
          </p>
        </div>
      )}
      {runs.data && runs.data.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>run</th>
              <th>repo</th>
              <th>base → head</th>
              <th>status</th>
              <th>verdict</th>
              <th className="num">targets</th>
              <th className="num">divergences</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.items.map((run) => (
              <tr
                key={run.id}
                className="rowlink"
                tabIndex={0}
                onClick={() => navigate({ view: "run", id: run.id })}
                onKeyDown={(e) => e.key === "Enter" && navigate({ view: "run", id: run.id })}
              >
                <td>#{run.id}</td>
                <td>{run.repo}</td>
                <td className="dim">
                  {run.base_sha.slice(0, 8)} → {run.head_sha.slice(0, 8)}
                </td>
                <td className="dim">{run.status.toLowerCase()}</td>
                <td>
                  {run.verdict ? <span className={`chip ${run.verdict}`}>{run.verdict}</span> : "—"}
                </td>
                <td className="num">{run.target_count}</td>
                <td className={`num ${run.divergence_count > 0 ? "red" : ""}`}>
                  {run.divergence_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
