import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { startDemoProve, startLocalProve } from "./hooks";
import { runPath, runsPath } from "./routes";

export function ProveView() {
  const navigate = useNavigate();
  const [repoPath, setRepoPath] = useState("");
  const [base, setBase] = useState("main");
  const [head, setHead] = useState("HEAD");
  const [maxInputs, setMaxInputs] = useState(300);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // The demo's second home (ADR-0032): the empty-state button vanishes once history exists,
  // but "show me it working before I point it at MY code" stays a reasonable ask forever.
  async function demo() {
    setBusy(true);
    setProblem(null);
    try {
      const created = await startDemoProve();
      navigate(runPath(created.run_id));
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "the demo could not be started");
      setBusy(false);
    }
  }

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
      navigate(runPath(created.run_id));
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "the engine rejected the request");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <nav className="crumbs">
        <Link to={runsPath()}>Runs</Link> / New proof
      </nav>
      <h1>New proof</h1>
      <p className="dim">
        Tempest executes both revisions side by side under identical conditions and reports
        concrete inputs where behavior diverges — with a minimized reproduction. A change it
        cannot exercise is UNPROVEN, never blessed.
      </p>

      <label htmlFor="repo">Repository folder (full path)</label>
      <input
        id="repo"
        className="mono"
        value={repoPath}
        placeholder="/Users/you/projects/my-repo"
        onChange={(e) => setRepoPath(e.target.value)}
      />

      <div className="split">
        <div>
          <label htmlFor="base">Base (pre-change ref)</label>
          <input id="base" value={base} onChange={(e) => setBase(e.target.value)} />
        </div>
        <div>
          <label htmlFor="head">Head (post-change ref)</label>
          <input id="head" value={head} onChange={(e) => setHead(e.target.value)} />
        </div>
      </div>

      <label htmlFor="budget">Input budget per target</label>
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

      <p className="keyrow">
        <button className="primary" disabled={busy || repoPath.trim() === ""} onClick={start}>
          {busy ? "Starting…" : "Prove it"}
        </button>
        <button disabled={busy} onClick={() => void demo()}>
          Try a demo proof
        </button>
      </p>
      <p className="group-note" style={{ marginTop: 0 }}>
        The demo writes a tiny repository of its own and proves — with real inputs and a real
        reproduction — that a &ldquo;harmless&rdquo; rounding cleanup changes what customers
        pay. Nothing of yours is touched.
      </p>
      <p className="dim">
        Note: repositories always run inside a sandbox, never unsandboxed (Law L6): Docker when
        available (T1), otherwise the OS-native macOS sandbox (T2). With no tier available,
        targets are honestly reported UNPROVEN (sandbox unavailable).
      </p>
    </main>
  );
}
