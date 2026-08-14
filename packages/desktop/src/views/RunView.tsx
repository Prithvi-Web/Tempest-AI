import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { useGetRun } from "../hooks";

import type { Route } from "../router";

export function RunView({ id, navigate }: { id: number; navigate: (r: Route) => void }) {
  const run = useGetRun(id);
  const queryClient = useQueryClient();
  const stillRunning = run.data?.status === "PENDING";

  // Poll while the proof executes. invalidateQueries (not a render-time refetch chain): an
  // unchanged poll causes no re-render, so any render-driven scheduling would silently stop.
  useEffect(() => {
    if (!stillRunning) return;
    const timer = setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: ["getRun", id] });
    }, 1500);
    return () => clearInterval(timer);
  }, [stillRunning, id, queryClient]);

  if (run.isPending) return <p className="dim">loading run #{id}…</p>;
  if (run.isError) return <p className="yellow">could not load run #{id}</p>;
  const data = run.data;
  const unproven = data.targets.filter((t) => t.verdict === "UNPROVEN");
  const isPending = data.status === "PENDING";

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
        / #{data.id}
      </nav>
      <div className="statusline">
        <h1>
          run #{data.id} · {data.repo}
        </h1>
        {data.verdict ? (
          <span className={`chip ${data.verdict}`}>{data.verdict}</span>
        ) : (
          <span className="chip neutral">{isPending ? "RUNNING…" : data.status}</span>
        )}
      </div>
      <p className="dim">
        {data.base_sha.slice(0, 12)} → {data.head_sha.slice(0, 12)}
        {data.engine_version ? ` · engine ${data.engine_version}` : ""}
        {isPending ? " · executing base and head side by side…" : ""}
      </p>

      {unproven.length > 0 && (
        <div className="panel notproven">
          <strong className="yellow">
            ⚠ NOT PROVEN — {unproven.length} of {data.targets.length} targets could not be
            exercised
          </strong>
          <p className="dim" style={{ marginBottom: 0 }}>
            Nothing below is blessed. Every row is a claim Tempest refused to make.
          </p>
          <table>
            <tbody>
              {unproven.map((t) => (
                <tr
                  key={t.id}
                  className="rowlink"
                  tabIndex={0}
                  onClick={() => navigate({ view: "target", id: t.id })}
                  onKeyDown={(e) => e.key === "Enter" && navigate({ view: "target", id: t.id })}
                >
                  <td>
                    {t.module}.{t.qualname}
                  </td>
                  <td>
                    <span className="chip UNPROVEN">{t.reason_code ?? "UNPROVEN"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.targets.length > 0 && (
        <>
          <h2>targets</h2>
          <table>
            <thead>
              <tr>
                <th>target</th>
                <th>file</th>
                <th>classification</th>
                <th>verdict</th>
                <th>changed-line cov</th>
                <th className="num">div</th>
              </tr>
            </thead>
            <tbody>
              {data.targets.map((t) => (
                <tr
                  key={t.id}
                  className="rowlink"
                  tabIndex={0}
                  onClick={() => navigate({ view: "target", id: t.id })}
                  onKeyDown={(e) => e.key === "Enter" && navigate({ view: "target", id: t.id })}
                >
                  <td>
                    {t.module}.{t.qualname}
                  </td>
                  <td className="dim">{t.file_path}</td>
                  <td className="dim">{t.classification}</td>
                  <td>
                    <span className={`chip ${t.verdict}`}>{t.verdict}</span>
                  </td>
                  <td>
                    {/* float-over-JSON is number|null in the contract; coverage is always finite */}
                    <div
                      className="bar"
                      title={`${Math.round((t.changed_line_coverage ?? 0) * 100)}%`}
                    >
                      <i
                        className={(t.changed_line_coverage ?? 0) >= 1 ? "full" : ""}
                        style={{ width: `${Math.round((t.changed_line_coverage ?? 0) * 100)}%` }}
                      />
                    </div>
                  </td>
                  <td className={`num ${t.divergence_count > 0 ? "red" : ""}`}>
                    {t.divergence_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {data.targets.length === 0 && !isPending && (
        <p className="dim">No targets were selected from this diff.</p>
      )}
    </main>
  );
}
