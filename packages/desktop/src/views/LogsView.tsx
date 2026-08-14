import { useState } from "react";

import { useListLogRecords } from "../hooks";

import type { Route } from "../router";

/** Minimum-severity filter, mirroring the engine's `--level` semantics ("" = everything). */
const LEVELS = ["", "INFO", "WARNING", "ERROR"] as const;

function levelClass(level: string): string {
  if (level === "ERROR" || level === "CRITICAL") return "red";
  if (level === "WARNING") return "yellow";
  return "dim";
}

export function LogsView({ navigate }: { navigate: (r: Route) => void }) {
  const [level, setLevel] = useState("");
  const logs = useListLogRecords(undefined, level === "" ? null : level);

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
        / logs
      </nav>
      <div className="statusline">
        <h1 style={{ flex: 1 }}>LOGS</h1>
        <select
          aria-label="minimum level"
          value={level}
          onChange={(e) => setLevel(e.target.value)}
          style={{ font: "inherit", color: "var(--ink)", background: "var(--panel-raised)", border: "1px solid var(--panel-line)", padding: "7px 12px" }}
        >
          {LEVELS.map((lvl) => (
            <option key={lvl} value={lvl}>
              {lvl === "" ? "ALL LEVELS" : lvl}
            </option>
          ))}
        </select>
      </div>
      <p className="dim">
        The engine's own structured log — local data about Tempest itself, newest last.
      </p>
      {logs.isPending && <p className="dim">loading…</p>}
      {logs.isError && (
        <p className="yellow">could not load logs — the engine may still be starting</p>
      )}
      {logs.data && logs.data.length === 0 && (
        <div className="panel">
          <p className="dim">
            No log records{level === "" ? "" : ` at ${level} or above`} yet.
          </p>
        </div>
      )}
      {logs.data && logs.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>ts</th>
              <th>level</th>
              <th>component</th>
              <th>message</th>
            </tr>
          </thead>
          <tbody>
            {logs.data.map((record, i) => (
              <tr key={`${record.ts}-${i}`}>
                <td className="dim">{record.ts}</td>
                <td className={levelClass(record.level)}>{record.level}</td>
                <td className="dim">{record.component}</td>
                <td>{record.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
