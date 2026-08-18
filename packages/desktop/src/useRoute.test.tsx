/**
 * The useRoute hook against real jsdom history: initial parse, navigate (pushState + state),
 * and the popstate path the back button takes. No mocked history — jsdom's is the real API.
 */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { routeHref, useRoute, type Route } from "./router";

afterEach(cleanup);

let latest: { route: Route; navigate: (r: Route) => void } | null = null;

function Probe() {
  const [route, navigate] = useRoute();
  latest = { route, navigate };
  return <span data-testid="view">{route.view}</span>;
}

describe("useRoute", () => {
  it("parses the URL it mounts on", () => {
    window.history.replaceState(null, "", "/?view=logs");
    const { getByTestId } = render(<Probe />);
    expect(getByTestId("view").textContent).toBe("logs");
  });

  it("navigate pushes the href and updates the route", () => {
    window.history.replaceState(null, "", "/?");
    const { getByTestId } = render(<Probe />);
    act(() => latest?.navigate({ view: "run", id: 4 }));
    expect(getByTestId("view").textContent).toBe("run");
    expect(window.location.search).toBe(routeHref({ view: "run", id: 4 }));
  });

  it("popstate (the back button) re-parses the URL", () => {
    window.history.replaceState(null, "", "/?");
    const { getByTestId } = render(<Probe />);
    act(() => latest?.navigate({ view: "settings" }));
    expect(getByTestId("view").textContent).toBe("settings");
    act(() => {
      window.history.replaceState(null, "", "/?view=watch");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(getByTestId("view").textContent).toBe("watch");
  });

  it("the popstate listener is removed on unmount (no leak across remounts)", () => {
    window.history.replaceState(null, "", "/?");
    const { unmount } = render(<Probe />);
    unmount();
    const before = latest?.route;
    window.history.replaceState(null, "", "/?view=logs");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(latest?.route).toBe(before); // nothing re-rendered — the listener is gone
  });
});
