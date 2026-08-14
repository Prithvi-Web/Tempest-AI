import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { events } from "./generated/bindings";
import { useGetHealth } from "./hooks";
import { useRoute } from "./router";
import { DivergenceView } from "./views/DivergenceView";
import { LogsView } from "./views/LogsView";
import { ProveView } from "./views/ProveView";
import { RunsView } from "./views/RunsView";
import { RunView } from "./views/RunView";
import { TargetView } from "./views/TargetView";

export function App() {
  const [route, navigate] = useRoute();
  const health = useGetHealth();
  const queryClient = useQueryClient();

  // Typed sidecar lifecycle event: when the supervisor reports the engine (re)became healthy,
  // every stale query refetches immediately instead of waiting for its own retry clock.
  useEffect(() => {
    const unlisten = events.sidecarStateEvent.listen((event) => {
      if (event.payload.state === "healthy") void queryClient.invalidateQueries();
    });
    return () => {
      void unlisten.then((dispose) => dispose());
    };
  }, [queryClient]);

  return (
    <div className="shell">
      <header className="masthead">
        <a
          href="?"
          className="word"
          onClick={(e) => {
            e.preventDefault();
            navigate({ view: "runs" });
          }}
        >
          T E M P E S T
        </a>
        <span className="tag">behavioral proof agent · evidence, not opinion</span>
        <span className="spacer" />
        <span className="tag">
          {health.isPending ? (
            "engine starting…"
          ) : health.isError ? (
            <span className="yellow">engine unreachable — retrying</span>
          ) : (
            <span className="green">
              engine {health.data.engine_version} · schema v{health.data.schema_version}
            </span>
          )}
        </span>
      </header>
      {route.view === "runs" && <RunsView navigate={navigate} />}
      {route.view === "run" && <RunView id={route.id} navigate={navigate} />}
      {route.view === "target" && <TargetView id={route.id} navigate={navigate} />}
      {route.view === "divergence" && <DivergenceView id={route.id} navigate={navigate} />}
      {route.view === "prove" && <ProveView navigate={navigate} />}
      {route.view === "logs" && <LogsView navigate={navigate} />}
    </div>
  );
}
