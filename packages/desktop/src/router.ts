/** Query-param routing: the URL survives reloads inside the Tauri webview and needs no
 * server-side route table (`?view=run&id=3`). */
import { useCallback, useEffect, useState } from "react";

export type Route =
  | { view: "runs" }
  | { view: "run"; id: number }
  | { view: "target"; id: number }
  | { view: "divergence"; id: number }
  | { view: "prove" }
  | { view: "logs" };

export function parseRoute(search: string): Route {
  const params = new URLSearchParams(search);
  const view = params.get("view");
  const id = Number(params.get("id"));
  if (view === "run" && Number.isFinite(id)) return { view: "run", id };
  if (view === "target" && Number.isFinite(id)) return { view: "target", id };
  if (view === "divergence" && Number.isFinite(id)) return { view: "divergence", id };
  if (view === "prove") return { view: "prove" };
  if (view === "logs") return { view: "logs" };
  return { view: "runs" };
}

export function routeHref(route: Route): string {
  if (route.view === "runs") return "?";
  if (route.view === "prove") return "?view=prove";
  if (route.view === "logs") return "?view=logs";
  return `?view=${route.view}&id=${route.id}`;
}

export function useRoute(): [Route, (r: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.search));
  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const navigate = useCallback((r: Route) => {
    window.history.pushState(null, "", routeHref(r));
    setRoute(r);
  }, []);
  return [route, navigate];
}
