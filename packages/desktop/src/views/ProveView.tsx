import { useState } from "react";

import { startLocalProve } from "../hooks";
import type { Route } from "../router";

export function ProveView({ navigate }: { navigate: (r: Route) => void }) {
  const [repoPath, setRepoPath] = useState("");
  const [base, setBase] = useState("main");
  const [head, setHead] = useState("HEAD");
  const [maxInputs, setMaxInputs] = useState(300);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setProblem(null);
    try {
      const created = await startLocalProve({
        repo_path: repoPath.trim(),
        base,
        head,
        max_inputs: maxInputs,
      });
      navigate({ view: "run", id: created.run_id });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "the engine rejected the request");
    } finally {
      setBusy(false);
    }
  }

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
        / new proof
      </nav>
      <h1>NEW PROOF</h1>
      <p className="dim">
        Tempest executes both revisions side by side under identical conditions and reports
        concrete inputs where behavior diverges — with a minimized reproduction. A change it
        cannot exercise is UNPROVEN, never blessed.
      </p>

      <label htmlFor="repo">repository folder (full path)</label>
      <input
        id="repo"
        value={repoPath}
        placeholder="/Users/you/projects/my-repo"
        onChange={(e) => setRepoPath(e.target.value)}
      />

      <div className="split">
        <div>
          <label htmlFor="base">base (pre-change ref)</label>
          <input id="base" value={base} onChange={(e) => setBase(e.target.value)} />
        </div>
        <div>
          <label htmlFor="head">head (post-change ref)</label>
          <input id="head" value={head} onChange={(e) => setHead(e.target.value)} />
        </div>
      </div>

      <label htmlFor="budget">input budget per target</label>
      <input
        id="budget"
        type="number"
        min={10}
        max={2000}
        value={maxInputs}
        onChange={(e) => setMaxInputs(Number(e.target.value) || 300)}
      />

      {problem && (
        <div className="panel notproven">
          <strong className="yellow">could not start</strong>
          <p style={{ marginBottom: 0 }}>{problem}</p>
        </div>
      )}

      <p>
        <button className="primary" disabled={busy || repoPath.trim() === ""} onClick={start}>
          {busy ? "STARTING…" : "PROVE IT"}
        </button>
      </p>
      <p className="dim">
        Note: proving arbitrary repositories requires Docker Desktop (Law L6 — no unsandboxed
        execution). Without it, targets are honestly reported UNPROVEN (sandbox unavailable).
      </p>
    </main>
  );
}
