/**
 * Tauri IPC shim, injected by Playwright BEFORE any page script runs. Implements the exact
 * `window.__TAURI_INTERNALS__` surface @tauri-apps/api@2 touches (core.js + event.js):
 *
 *   invoke(cmd, args)      → POST to the e2e bridge, which forwards to the REAL sidecar
 *   transformCallback(cb)  → callback registry (the event plugin hands these ids around)
 *   unregisterCallback(id)
 *   plugin:event|listen / unlisten → an in-page event bus
 *
 * Contract detail that matters: on engine failure the promise must reject with the PLAIN
 * SidecarFailure object (not an Error) — tauri-specta's typedError() only converts non-Error
 * rejections into `{status: "error"}` results, which is what the hooks' unwrap() expects.
 *
 * `window.__E2E__.emit(name, payload)` lets tests stage host-emitted events
 * (e.g. sidecar-state-event) the way the Rust supervisor would.
 */
(() => {
  const bridgeUrl = window.__E2E_BRIDGE_URL__ ?? "http://127.0.0.1:39755";
  const callbacks = new Map(); // callbackId -> fn
  const listeners = new Map(); // event name -> Map(eventId -> callbackId)
  let nextCallbackId = 1;
  let nextEventId = 1;
  let shimAiKey = null; // the in-memory keychain stand-in (see the ai_key_* handler below)
  const revealed = []; // every reveal_in_data_dir argument, for the Settings spec to assert

  window.__TAURI_INTERNALS__ = {
    transformCallback(callback) {
      const id = nextCallbackId++;
      callbacks.set(id, callback);
      return id;
    },
    unregisterCallback(id) {
      callbacks.delete(id);
    },
    convertFileSrc(filePath) {
      return filePath;
    },
    async invoke(cmd, args = {}) {
      if (cmd === "plugin:event|listen") {
        const eventId = nextEventId++;
        if (!listeners.has(args.event)) listeners.set(args.event, new Map());
        listeners.get(args.event).set(eventId, args.handler);
        return eventId;
      }
      if (cmd === "plugin:event|unlisten") {
        listeners.get(args.event)?.delete(args.eventId);
        return null;
      }
      // The AI-key commands live in the RUST host (keychain.rs), which this browser harness
      // replaces — an in-memory stand-in mirrors its exact semantics (validation message
      // included) so the Settings UI is testable end-to-end; the real keychain storage and
      // spawn-env injection are proven by cargo tests.
      if (cmd === "ai_key_status" || cmd === "set_ai_key" || cmd === "clear_ai_key") {
        if (cmd === "set_ai_key") {
          const trimmed = String(args.key ?? "").trim();
          const rest = trimmed.startsWith("sk-ant-") ? trimmed.slice("sk-ant-".length) : null;
          const shapely = rest !== null && rest.length >= 16 && /^[A-Za-z0-9_-]+$/.test(rest);
          if (!shapely) {
            throw {
              code: -3,
              message:
                "that does not look like an Anthropic API key — keys start with sk-ant- " +
                "(create one at console.anthropic.com)",
            };
          }
          shimAiKey = trimmed;
        }
        if (cmd === "clear_ai_key") shimAiKey = null;
        return shimAiKey === null
          ? { configured: false, last4: null }
          : { configured: true, last4: shimAiKey.slice(-4) };
      }
      // Host-side action (commands.rs reveal_in_data_dir): there is no sidecar behind it,
      // and a browser has no Finder. Mirror the host's containment rule so a spec can prove
      // the UI only ever names a bare leaf, and record the calls for assertion.
      if (cmd === "reveal_in_data_dir") {
        const name = args.diagnostic ?? null;
        if (name !== null) {
          const bad =
            name === "" || name === ".." || name.startsWith(".") ||
            name.includes("/") || name.includes("\\") || name.includes("\0");
          if (bad) throw { code: -4, message: `${JSON.stringify(name)} is not a plain file name inside the data folder` };
        }
        revealed.push(name);
        return null;
      }
      const response = await fetch(`${bridgeUrl}/invoke`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ cmd, args }),
      });
      const body = await response.json();
      // Engine errors ride in-band as {error} on a 200 (see bridge.mjs). Throwing the PLAIN
      // object (never an Error) is what makes typedError produce {status: "error"}.
      if (body.error !== undefined) throw body.error;
      return body.data;
    },
  };

  // The unlisten path bypasses invoke: event.js calls this directly (StrictMode's
  // double-mount exercises it on every page load).
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = {
    unregisterListener(event, eventId) {
      listeners.get(event)?.delete(eventId);
    },
  };

  window.__E2E__ = {
    revealed,
    emit(name, payload) {
      const subscribers = listeners.get(name);
      if (!subscribers) return 0;
      let delivered = 0;
      for (const callbackId of subscribers.values()) {
        const callback = callbacks.get(callbackId);
        if (callback) {
          callback({ event: name, id: 0, payload });
          delivered += 1;
        }
      }
      return delivered;
    },
  };
})();
