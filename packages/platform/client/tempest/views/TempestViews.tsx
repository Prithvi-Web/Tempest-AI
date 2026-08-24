/**
 * The Tempest proof surface as ONE route subtree inside the platform client (C3).
 *
 * This is the desktop shell's `App.tsx` with its two shell responsibilities removed and nothing
 * else changed: the window (title bar, drag region, document-level resets) belongs to the client
 * that hosts this subtree now, and routing is react-router rather than the query-param table the
 * webview carried for want of one. What stays is the whole of the surface — the ten views, the
 * rail that reaches them, the engine-status foot, and the two pushed events that keep run data
 * live — because a proof surface that loses a view in the move has not been absorbed, it has been
 * reduced.
 *
 * Everything paints under `.tempest-views` (see `tempest-views.css`): the absorbed design language
 * is scoped to this subtree, and the client's own surfaces keep theirs.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";

import { events } from "../../../../desktop/src/generated/bindings";
import { ComposerView } from "./ComposerView";
import { DivergenceView } from "./DivergenceView";
import { EditorView } from "./EditorView";
import { LogsView } from "./LogsView";
import { ProveView } from "./ProveView";
import { RunsView } from "./RunsView";
import { RunView } from "./RunView";
import SettingsRedirect from "../settings/SettingsRedirect";
import { openSettingsHome } from "../settings/home";
import { TEMPEST_ENGINE_TAB } from "../settings/tabIds";
import { TargetView } from "./TargetView";
import { WatchView } from "./WatchView";
import { useGetHealth } from "./hooks";
import {
  TEMPEST_BASE,
  composerPath,
  logsPath,
  provePath,
  rowId,
  runsPath,
  watchPath,
} from "./routes";
import "./tempest-views.css";

/** SF-Symbol-inspired strokes, inlined so the app stays fully offline (L8). */
function Icon({ name }: { name: "runs" | "prove" | "watch" | "composer" | "logs" | "settings" }) {
  const paths: Record<string, string> = {
    runs: "M3 5h12M3 9h12M3 13h8",
    prove: "M9 3v12M3 9h12",
    watch: "M9 4.5a4.5 4.5 0 1 1-4.5 4.5M9 4.5V2M9 4.5 6.6 6M9 9l2.6 1.5",
    // Three stacked rows with a mark against each: hunks, and the column that judges them.
    composer: "M3 4h7M3 9h7M3 14h7M13 4l1.5 1.5L17 3M13 9l1.5 1.5L17 8M13 14l1.5 1.5L17 13",
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
  to,
  current,
  icon,
  label,
}: {
  to: string;
  current: boolean;
  icon: "runs" | "prove" | "watch" | "composer" | "logs" | "settings";
  label: string;
}) {
  return (
    <Link to={to} className={`nav-item${current ? " current" : ""}`} aria-current={current ? "page" : undefined}>
      <Icon name={icon} />
      {label}
    </Link>
  );
}

/**
 * The rail's Settings item, which is no longer a destination inside this surface (ADR-0082).
 *
 * It opens the app's ONE settings home on the proof-engine tab. Two doors into one home is
 * fine and is what a person expects — what the owner asked to end was two HOMES, which is
 * what a second settings page inside a tool surface is.
 */
function SettingsNavItem() {
  return (
    <button
      type="button"
      className="nav-item"
      data-testid="tempest-open-settings"
      onClick={() => openSettingsHome(TEMPEST_ENGINE_TAB)}
    >
      <Icon name="settings" />
      Settings
    </button>
  );
}

/** Run-family views highlight Runs in the rail — they are drill-downs, not destinations. */
const RUN_FAMILY = new Set(["", "runs", "targets", "divergences"]);

function sectionOf(pathname: string): string {
  const inside = pathname.startsWith(TEMPEST_BASE) ? pathname.slice(TEMPEST_BASE.length) : pathname;
  const first = inside.replace(/^\/+/, "").split("/")[0] ?? "";
  return RUN_FAMILY.has(first) ? "runs" : first;
}

/**
 * The id adapters. `parseRoute` refused to turn a missing or malformed id into row #0 and fell
 * back to the list; a URL is no more trustworthy for having a router in front of it, so the same
 * refusal happens here — one place per view, before the view is asked to fetch anything.
 */
function RunRoute() {
  const id = rowId(useParams().runId);
  return id === null ? <Navigate to={runsPath()} replace /> : <RunView id={id} />;
}

function TargetRoute() {
  const id = rowId(useParams().targetId);
  return id === null ? <Navigate to={runsPath()} replace /> : <TargetView id={id} />;
}

function DivergenceRoute() {
  const id = rowId(useParams().divergenceId);
  return id === null ? <Navigate to={runsPath()} replace /> : <DivergenceView id={id} />;
}

export default function TempestViews() {
  const location = useLocation();
  const health = useGetHealth();
  const queryClient = useQueryClient();
  const section = sectionOf(location.pathname);

  // VoiceOver/keyboard (§3.3): after in-app navigation, focus lands on the new view's title,
  // so the destination is announced and the Tab order restarts at the content — the standard
  // SPA pattern for a webview with no real page loads. The guard compares LOCATIONS rather than
  // counting renders: StrictMode's dev double-mount re-runs effects with refs intact, so a
  // boolean "first render" flag would flip on the replay and steal focus on initial load. It is
  // also scoped to this subtree's own title: the client outside owns its own focus.
  const here = `${location.pathname}${location.search}`;
  const lastFocused = useRef(here);
  useEffect(() => {
    if (here === lastFocused.current) return;
    lastFocused.current = here;
    const title = document.querySelector<HTMLHeadingElement>(".tempest-views .content main h1");
    if (title) {
      title.setAttribute("tabindex", "-1");
      title.focus({ preventScroll: false });
    }
  }, [here]);

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

  return (
    <div className="tempest-views">
      <div className="app">
        <a
          className="skip-link"
          href="#tempest-main-content"
          onClick={(e) => {
            e.preventDefault();
            const content = document.getElementById("tempest-main-content");
            if (content) {
              content.setAttribute("tabindex", "-1");
              content.focus();
            }
          }}
        >
          Skip to content
        </a>
        <aside className="sidebar">
          <div className="brand">
            <strong>Tempest</strong>
            <span>behavioral proof · evidence, not opinion</span>
          </div>
          <nav aria-label="Tempest">
            <NavItem to={runsPath()} current={section === "runs"} icon="runs" label="Runs" />
            <NavItem to={provePath()} current={section === "prove"} icon="prove" label="New proof" />
            <NavItem to={watchPath()} current={section === "watch"} icon="watch" label="Watch" />
            <NavItem
              to={composerPath()}
              current={section === "composer"}
              icon="composer"
              label="Composer"
            />
            <NavItem to={logsPath()} current={section === "logs"} icon="logs" label="Logs" />
            <SettingsNavItem />
          </nav>
          <div className="sidebar-foot" role="status" aria-live="polite" aria-label="engine status">
            {health.isLoading ? (
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
        <div className="content" id="tempest-main-content">
          {/* Relative patterns: the subtree is mounted on ONE path that ends in a splat, and every
              href it emits is absolute (`routes.ts`), so the two cannot drift apart. */}
          <Routes>
            <Route index element={<RunsView />} />
            <Route path="runs/:runId" element={<RunRoute />} />
            <Route path="targets/:targetId" element={<TargetRoute />} />
            <Route path="divergences/:divergenceId" element={<DivergenceRoute />} />
            <Route path="prove" element={<ProveView />} />
            <Route path="watch" element={<WatchView />} />
            <Route path="composer" element={<ComposerView />} />
            <Route path="logs" element={<LogsView />} />
            {/* Kept as a deep link into the one settings home (ADR-0082), never a second one. */}
            <Route path="settings" element={<SettingsRedirect />} />
            <Route path="editor" element={<EditorView />} />
            {/* `parseRoute` answered every unrecognised URL with the runs list rather than an
                error page, and a bad link is still not an error worth a screen of its own. */}
            <Route path="*" element={<Navigate to={runsPath()} replace />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
