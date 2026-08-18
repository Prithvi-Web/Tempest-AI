/** Query-param routing: the URL survives reloads inside the Tauri webview and needs no
 * server-side route table (`?view=run&id=3`). */
import { useCallback, useEffect, useState } from "react";

export type Route =
  | { view: "runs" }
  | { view: "run"; id: number }
  | { view: "target"; id: number }
  | { view: "divergence"; id: number }
  | { view: "prove" }
  | { view: "logs" }
  | { view: "watch" }
  | { view: "settings" };

export function parseRoute(search: string): Route {
  const params = new URLSearchParams(search);
  const view = params.get("view");
  // A MISSING id must not become run #0: Number(null) is 0, so the presence check comes
  // first, and only a positive integer names a row (ids are 1-based database keys).
  const raw = params.get("id");
  const id = raw === null ? NaN : Number(raw);
  const hasId = Number.isInteger(id) && id > 0;
  if (view === "run" && hasId) return { view: "run", id };
  if (view === "target" && hasId) return { view: "target", id };
  if (view === "divergence" && hasId) return { view: "divergence", id };
  if (view === "prove") return { view: "prove" };
  if (view === "logs") return { view: "logs" };
  if (view === "watch") return { view: "watch" };
  if (view === "settings") return { view: "settings" };
  return { view: "runs" };
}

export function routeHref(route: Route): string {
  if (route.view === "runs") return "?";
  if (route.view === "prove") return "?view=prove";
  if (route.view === "logs") return "?view=logs";
  if (route.view === "watch") return "?view=watch";
  if (route.view === "settings") return "?view=settings";
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
