import { useGetDivergence, useGetDivergenceRepro } from "../hooks";

import type { Route } from "../router";

function CopyButton({ text }: { text: string }) {
  return (
    <button
      onClick={() => {
        void navigator.clipboard.writeText(text);
      }}
    >
      Copy
    </button>
  );
}

export function DivergenceView({ id, navigate }: { id: number; navigate: (r: Route) => void }) {
  const divergence = useGetDivergence(id);
  const repro = useGetDivergenceRepro(id);

  if (divergence.isPending) return <p className="dim">loading divergence #{id}…</p>;
  if (divergence.isError) return <p className="yellow">could not load divergence #{id}</p>;
  const d = divergence.data;

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
          Runs
        </a>{" "}
        /{" "}
        <a
          href={`?view=target&id=${d.target_id}`}
          onClick={(e) => {
            e.preventDefault();
            navigate({ view: "target", id: d.target_id });
          }}
        >
          Target #{d.target_id}
        </a>{" "}
        / Divergence #{d.id}
      </nav>
      <div className="statusline">
        <h1>Divergence #{d.id}</h1>
        <span className="chip DIVERGENT">{d.divergence_class}</span>
        <span className="chip neutral">{d.severity}</span>
      </div>
      <p className="dim">{d.detail}</p>

      <div className="panel diverge">
        <h2 style={{ marginTop: 0 }}>
          Minimized input <span className="dim">— smallest input still producing this divergence</span>
        </h2>
        <div className="statusline">
          <code style={{ flex: 1 }} className="mono-block">
            {d.minimized_args}
          </code>
          <CopyButton text={d.minimized_args} />
        </div>
        {d.minimized_kwargs !== "{}" && (
          <div className="statusline">
            <code style={{ flex: 1 }} className="mono-block">
              {d.minimized_kwargs}
            </code>
            <CopyButton text={d.minimized_kwargs} />
          </div>
        )}
      </div>

      <h2>Observed behavior, identical conditions</h2>
      <div className="split">
        <div className="panel">
          <span className="dim">BASE</span>
          <div className="mono-block">{d.base_summary}</div>
        </div>
        <div className="panel">
          <span className="red">HEAD</span>
          <div className="mono-block">{d.head_summary}</div>
        </div>
      </div>

      <div className="statusline">
        <h2 style={{ flex: 1 }}>Reproduction script · {d.repro_filename}</h2>
        {repro.data && <CopyButton text={repro.data} />}
      </div>
      {repro.isPending && <p className="dim">loading script…</p>}
      {repro.data && <pre className="mono-block script">{repro.data}</pre>}

      {d.shrink_path.length > 0 && (
        <details>
          <summary className="dim">
            How it shrank — {d.shrink_path.length} step(s) from {d.args_literal}
          </summary>
          <ol className="dim">
            {d.shrink_path.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </details>
      )}
    </main>
  );
}
