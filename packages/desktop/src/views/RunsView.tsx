import { useState } from "react";

import { useListRuns, useSearchDivergences } from "../hooks";

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
          <th>run</th>
          <th>target</th>
          <th>class</th>
          <th>evidence</th>
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

  return (
    <main>
      <div className="statusline">
        <h1 style={{ flex: 1 }}>RUNS</h1>
        <input
          type="search"
          placeholder="search divergences…"
          aria-label="search divergences"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button onClick={() => navigate({ view: "logs" })}>LOGS</button>
        <button className="primary" onClick={() => navigate({ view: "prove" })}>
          NEW PROOF
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
