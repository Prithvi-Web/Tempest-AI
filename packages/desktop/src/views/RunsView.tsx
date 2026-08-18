import { useState } from "react";

import { startDemoProve, useListRuns, useSearchDivergences } from "../hooks";
import { VerdictChip, runStatusLabel } from "../vocabulary";

import type { Route } from "../router";

function SearchResults({ query, navigate }: { query: string; navigate: (r: Route) => void }) {
  const search = useSearchDivergences(query);

  if (search.isPending) return <p className="dim">searching…</p>;
  if (search.isError) return <p className="yellow">search unavailable — {search.error.message}</p>;
  if (search.data.hits.length === 0)
    return (
      <div className="panel">
        <p className="dim">No divergences match “{query}”.</p>
      </div>
    );
  return (
    <table>
      <thead>
        <tr>
          <th>Run</th>
          <th>Target</th>
          <th>Class</th>
          <th>Evidence</th>
        </tr>
      </thead>
      <tbody>
        {search.data.hits.map((hit) => (
          <tr
            key={hit.divergence_id}
            className="rowlink"
            tabIndex={0}
            onClick={() => navigate({ view: "divergence", id: hit.divergence_id })}
            onKeyDown={(e) =>
              e.key === "Enter" && navigate({ view: "divergence", id: hit.divergence_id })
            }
          >
            <td>#{hit.run_id}</td>
            <td>
              {hit.module}.{hit.qualname}
            </td>
            <td className="dim">{hit.divergence_class}</td>
            <td className="dim">{hit.snippet}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RunsView({ navigate }: { navigate: (r: Route) => void }) {
  const runs = useListRuns({});
  const [query, setQuery] = useState("");
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoProblem, setDemoProblem] = useState<string | null>(null);

  async function runDemo() {
    setDemoBusy(true);
    setDemoProblem(null);
    try {
      const created = await startDemoProve();
      navigate({ view: "run", id: created.run_id });
    } catch (err) {
      setDemoProblem(err instanceof Error ? err.message : "the demo could not be started");
      setDemoBusy(false);
    }
  }

  return (
    <main>
      <div className="statusline">
        <h1 style={{ flex: 1 }}>Runs</h1>
        <input
          type="search"
          placeholder="search divergences…"
          aria-label="search divergences"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="primary" onClick={() => navigate({ view: "prove" })}>
          New proof
        </button>
      </div>
      {query.trim().length > 0 && <SearchResults query={query.trim()} navigate={navigate} />}
      {runs.isPending && <p className="dim">loading…</p>}
      {runs.isError && (
        <p className="yellow">could not load runs — the engine may still be starting</p>
      )}
      {runs.data && runs.data.items.length === 0 && (
        <div className="panel">
          <p className="dim">
            No runs yet. Click <span className="yellow">New proof</span> to execute a repository's
            base and head side by side and see where behavior diverges — with evidence.
          </p>
          <p className="dim">
            Or watch it happen first: the demo writes a tiny repository with a
            &ldquo;harmless&rdquo; rounding cleanup and proves — with real inputs and a real
            reproduction — that it changes what customers pay.
          </p>
          <p style={{ marginBottom: 0 }}>
            <button className="primary" disabled={demoBusy} onClick={() => void runDemo()}>
              {demoBusy ? "Starting the demo…" : "Try a demo proof"}
            </button>
          </p>
          {demoProblem && (
            <p className="yellow" style={{ marginBottom: 0 }}>
              {demoProblem}
            </p>
          )}
        </div>
      )}
      {runs.data && runs.data.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Repository</th>
              <th>Base → head</th>
              <th>Status</th>
              <th>Verdict</th>
              <th className="num">Targets</th>
              <th className="num">Divergences</th>
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
                <td className="dim mono">
                  {run.base_sha.slice(0, 8)} → {run.head_sha.slice(0, 8)}
                </td>
                <td className="dim">{runStatusLabel(run.status)}</td>
                <td>
                  {run.verdict ? <VerdictChip verdict={run.verdict} /> : "—"}
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
