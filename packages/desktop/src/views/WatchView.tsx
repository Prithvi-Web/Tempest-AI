import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { WatchStatus } from "../generated/bindings";
import { startWatch, stopWatch, useWatchStatus } from "../hooks";
import type { Route } from "../router";
import { VerdictChip, runStatusLabel } from "../vocabulary";

/** Watch — the continuous agent, live (ADR-0029, HANDOFF-WORLD-CLASS §2.4/§3.2).
 *
 * Point it at a repository and every NEW commit is proven against the one before it, one at a
 * time. What appears below is not a private feed: each row IS a run, with the same verdict,
 * the same ledger, and the same evidence as a proof started by hand — click through and you
 * land in the ordinary run view. Nothing here re-derives a verdict (L1/L2). */
export function WatchView({ navigate }: { navigate: (r: Route) => void }) {
  const status = useWatchStatus(true);
  const queryClient = useQueryClient();
  const [repoPath, setRepoPath] = useState("");
  const [intervalSeconds, setIntervalSeconds] = useState(15);
  const [maxInputs, setMaxInputs] = useState(300);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function act(action: () => Promise<WatchStatus>, fallback: string) {
    setBusy(true);
    setProblem(null);
    try {
      queryClient.setQueryData(["getWatchStatus"], await action());
      await queryClient.invalidateQueries({ queryKey: ["listRuns"] });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  const data = status.data;

  return (
    <main>
      <h1>Watch</h1>
      <p className="dim">
        Keep proving as you work: Tempest polls the repository and, on every new commit, proves
        it against the commit before it. One proof at a time, paused on battery or thermal
        pressure, and stoppable at any moment.
      </p>

      {status.isError && (
        <div className="panel notproven" role="alert">
          <strong className="yellow">watch status unavailable</strong>
          <p style={{ marginBottom: 0 }}>{status.error.message}</p>
        </div>
      )}
      {problem && (
        <div className="panel notproven" role="alert">
          <strong className="yellow">that did not work</strong>
          <p style={{ marginBottom: 0 }}>{problem}</p>
        </div>
      )}
      {data?.problem && (
        <div className="panel notproven" role="alert">
          <strong className="yellow">watching stopped</strong>
          <p style={{ marginBottom: 0 }}>{data.problem}</p>
        </div>
      )}

      {data && !data.watching && (
        <>
          <label htmlFor="watch-repo">Repository folder (full path)</label>
          <input
            id="watch-repo"
            className="mono"
            value={repoPath}
            placeholder="/Users/you/projects/my-repo"
            onChange={(e) => setRepoPath(e.target.value)}
          />
          <div className="split">
            <div>
              <label htmlFor="watch-interval">Check every (seconds)</label>
              <input
                id="watch-interval"
                type="number"
                min={1}
                max={3600}
                value={intervalSeconds}
                onChange={(e) => setIntervalSeconds(Number(e.target.value) || 15)}
              />
            </div>
            <div>
              <label htmlFor="watch-budget">Input budget per target</label>
              <input
                id="watch-budget"
                type="number"
                min={10}
                max={2000}
                value={maxInputs}
                onChange={(e) => setMaxInputs(Number(e.target.value) || 300)}
              />
            </div>
          </div>
          <p>
            <button
              className="primary"
              disabled={busy || repoPath.trim() === ""}
              onClick={() =>
                void act(
                  () =>
                    startWatch({
                      repo_path: repoPath.trim(),
                      interval_seconds: intervalSeconds,
                      max_inputs: maxInputs,
                    }),
                  "watching could not be started",
                )
              }
            >
              {busy ? "Starting…" : "Start watching"}
            </button>
          </p>
          <p className="dim">
            Watching proves what happens next — the commit you are on now is the starting
            point, not the first proof. To prove a pair that already exists, use New proof.
          </p>
        </>
      )}

      {data?.watching && (
        <div className="panel" role="status">
          <div className="keyrow">
            <p style={{ flex: 1, margin: 0 }}>
              <span className="pill green">watching</span> {data.repo_name}
              <span className="dim mono"> · {data.repo_path}</span>
            </p>
            <button
              className="destructive"
              disabled={busy}
              onClick={() => void act(stopWatch, "watching could not be stopped")}
            >
              Stop watching
            </button>
          </div>
          <p className="dim" style={{ marginBottom: 0 }}>
            Checking every {data.interval_seconds}s · last commit picked up{" "}
            <span className="mono">{(data.last_sha ?? "").slice(0, 12)}</span>
            {data.active_run_id !== null && (
              <>
                {" "}
                · <strong>proving run #{data.active_run_id} now</strong>
              </>
            )}
          </p>
        </div>
      )}

      <h2>Commits proven in this session</h2>
      {data && data.runs.length === 0 && (
        <div className="panel">
          <p className="dim" style={{ marginBottom: 0 }}>
            {data.watching
              ? "Nothing yet — commit something and Tempest will prove it."
              : "No commits have been proven by watching yet."}
          </p>
        </div>
      )}
      {data && data.runs.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Commit</th>
              <th>Status</th>
              <th>Verdict</th>
              <th>Divergences</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((run) => (
              <tr
                key={run.run_id}
                className="rowlink"
                tabIndex={0}
                onClick={() => navigate({ view: "run", id: run.run_id })}
                onKeyDown={(e) => e.key === "Enter" && navigate({ view: "run", id: run.run_id })}
              >
                <td>#{run.run_id}</td>
                <td className="mono">{run.head_sha.slice(0, 12)}</td>
                <td className="dim">{runStatusLabel(run.status)}</td>
                <td>
                  {run.verdict ? <VerdictChip verdict={run.verdict} /> : "—"}
                </td>
                <td>{run.divergence_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
