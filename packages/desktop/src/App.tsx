import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { events } from "./generated/bindings";
import { useGetHealth } from "./hooks";
import { routeHref, useRoute, type Route } from "./router";
import { DivergenceView } from "./views/DivergenceView";
import { EditorView } from "./views/EditorView";
import { LogsView } from "./views/LogsView";
import { ProveView } from "./views/ProveView";
import { RunsView } from "./views/RunsView";
import { RunView } from "./views/RunView";
import { SettingsView } from "./views/SettingsView";
import { WatchView } from "./views/WatchView";
import { TargetView } from "./views/TargetView";

/** SF-Symbol-inspired strokes, inlined so the app stays fully offline (L8). */
function Icon({ name }: { name: "runs" | "prove" | "watch" | "logs" | "settings" }) {
  const paths: Record<string, string> = {
    runs: "M3 5h12M3 9h12M3 13h8",
    prove: "M9 3v12M3 9h12",
    watch: "M9 4.5a4.5 4.5 0 1 1-4.5 4.5M9 4.5V2M9 4.5 6.6 6M9 9l2.6 1.5",
    logs: "M4 3h10v12H4zM6.5 6h5M6.5 9h5M6.5 12h3",
    settings:
      "M9 6.2A2.8 2.8 0 1 1 9 11.8 2.8 2.8 0 0 1 9 6.2zM9 2v2M9 14v2M2 9h2M14 9h2M4 4l1.4 1.4M12.6 12.6L14 14M14 4l-1.4 1.4M5.4 12.6L4 14",
  };
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  );
}

function NavItem({
  route,
  current,
  navigate,
  icon,
  label,
}: {
  route: Route;
  current: boolean;
  navigate: (r: Route) => void;
  icon: "runs" | "prove" | "watch" | "logs" | "settings";
  label: string;
}) {
  return (
    <a
      href="?"
      className={`nav-item${current ? " current" : ""}`}
      aria-current={current ? "page" : undefined}
      onClick={(e) => {
        e.preventDefault();
        navigate(route);
      }}
    >
      <Icon name={icon} />
      {label}
    </a>
  );
}

export function App() {
  const [route, navigate] = useRoute();
  const health = useGetHealth();
  const queryClient = useQueryClient();

  // VoiceOver/keyboard (§3.3): after in-app navigation, focus lands on the new view's title,
  // so the destination is announced and the Tab order restarts at the content — the standard
  // SPA pattern for a webview with no real page loads. The guard compares ROUTES rather than
  // counting renders: StrictMode's dev double-mount re-runs effects with refs intact, so a
  // boolean "first render" flag would flip on the replay and steal focus on initial load.
  const lastFocusedRoute = useRef(routeHref(route));
  useEffect(() => {
    const href = routeHref(route);
    if (href === lastFocusedRoute.current) return;
    lastFocusedRoute.current = href;
    const title = document.querySelector<HTMLHeadingElement>(".content main h1");
    if (title) {
      title.setAttribute("tabindex", "-1");
      title.focus({ preventScroll: false });
    }
  }, [route]);

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

  // Live run progress (§1.2): the host's central watcher pushes once per second for every
  // running prove — views refetch on the push instead of owning fast timers (the slow
  // fallback in useGetRun remains for hosts without a watcher, e.g. the browser E2E rig).
  useEffect(() => {
    const unlisten = events.runProgressEvent.listen((event) => {
      void queryClient.invalidateQueries({ queryKey: ["getRun", event.payload.run_id] });
      void queryClient.invalidateQueries({ queryKey: ["listRunEvents", event.payload.run_id] });
      void queryClient.invalidateQueries({ queryKey: ["listRuns"] });
    });
    return () => {
      void unlisten.then((dispose) => dispose());
    };
  }, [queryClient]);

  // Run-family views highlight Runs in the sidebar — they are drill-downs, not destinations.
  const section =
    route.view === "run" || route.view === "target" || route.view === "divergence"
      ? "runs"
      : route.view;

  return (
    <div className="app">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(e) => {
          e.preventDefault();
          const content = document.getElementById("main-content");
          if (content) {
            content.setAttribute("tabindex", "-1");
            content.focus();
          }
        }}
      >
        Skip to content
      </a>
      <div className="drag-strip" data-tauri-drag-region />
      <aside className="sidebar">
        <div className="brand">
          <strong>Tempest</strong>
          <span>behavioral proof · evidence, not opinion</span>
        </div>
        <nav aria-label="Primary">
          <NavItem route={{ view: "runs" }} current={section === "runs"} navigate={navigate} icon="runs" label="Runs" />
          <NavItem route={{ view: "prove" }} current={section === "prove"} navigate={navigate} icon="prove" label="New proof" />
          <NavItem route={{ view: "watch" }} current={section === "watch"} navigate={navigate} icon="watch" label="Watch" />
          <NavItem route={{ view: "logs" }} current={section === "logs"} navigate={navigate} icon="logs" label="Logs" />
          <NavItem
            route={{ view: "settings" }}
            current={section === "settings"}
            navigate={navigate}
            icon="settings"
            label="Settings"
          />
        </nav>
        <div className="sidebar-foot" role="status" aria-live="polite" aria-label="engine status">
          {health.isPending ? (
            <span className="pill dim">engine starting…</span>
          ) : health.isError ? (
            <span className="pill yellow">engine unreachable — retrying</span>
          ) : (
            <span className="pill green">
              engine {health.data.engine_version} · schema v{health.data.schema_version}
            </span>
          )}
        </div>
      </aside>
      <div className="content" id="main-content">
        {route.view === "runs" && <RunsView navigate={navigate} />}
        {route.view === "run" && <RunView id={route.id} navigate={navigate} />}
        {route.view === "target" && <TargetView id={route.id} navigate={navigate} />}
        {route.view === "divergence" && <DivergenceView id={route.id} navigate={navigate} />}
        {route.view === "prove" && <ProveView navigate={navigate} />}
        {route.view === "watch" && <WatchView navigate={navigate} />}
        {route.view === "logs" && <LogsView navigate={navigate} />}
        {route.view === "settings" && <SettingsView />}
        {route.view === "editor" && (
          <EditorView repo={route.repo} file={route.file} navigate={navigate} />
        )}
      </div>
    </div>
  );
}
