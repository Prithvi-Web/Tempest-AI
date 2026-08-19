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
  const hovered = []; // every lsp_hover the webview issues (Phase 20.5 reachability)
  let scriptedHover = null; // a spec may script ONE answer; null = behave as a fresh install
  // Backed by sessionStorage so a SAVE survives a reload, which is the real command's observable
  // contract (runners.rs writes a JSON file in the app data dir). The double models persistence
  // because the app HAS persistence — unlike lsp_hover's old `ok(null)`, which modelled an
  // answer the host never gives.
  const RUNNERS_KEY = "__tempest_e2e_runners__";
  const readRunners = () => {
    try {
      return { python_lsp: "", typescript_lsp: "", local_model: "",
        ...JSON.parse(sessionStorage.getItem(RUNNERS_KEY) ?? "{}") };
    } catch {
      return { python_lsp: "", typescript_lsp: "", local_model: "" };
    }
  };

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
      // Host-side (commands.rs local_completion): no sidecar behind it, and no local model in
      // this environment. `null` is what the real command returns when none is configured — the
      // expected state on a fresh install — so the editor exercises its FALLBACK path here,
      // which is the one that has to work on a plane. Answering honestly also keeps the console
      // clean: an unknown-command error from the bridge would fail the zero-issues bar, and
      // suppressing that would be hiding a real signal rather than fixing it.
      if (cmd === "local_completion") {
        return null;
      }
      // Host-side (commands.rs get/update_editor_runners — Phase 20.6): no sidecar behind them.
      // The store is in-memory here; the REAL rules (env overrides win and are reported, a
      // missing binary is reported as not found) are pinned in Rust where they live.
      if (cmd === "get_editor_runners" || cmd === "update_editor_runners") {
        let runners = readRunners();
        if (cmd === "update_editor_runners") {
          runners = { ...runners, ...args.runners };
          sessionStorage.setItem(RUNNERS_KEY, JSON.stringify(runners));
        }
        return {
          stored: runners,
          forced: [],
          status: ["python_lsp", "typescript_lsp", "local_model"].map((field) => ({
            field,
            command: runners[field] ?? "",
            // `/bin/sh` is the one command this harness can honestly call resolvable.
            found: (runners[field] ?? "").split(/\s+/)[0] === "/bin/sh",
          })),
          path: "/tmp/tempest-e2e/editor-runners.json",
        };
      }
      // Host-side (commands.rs lsp_hover): no sidecar behind it, and no language server is
      // configured in this environment.
      //
      // THE REAL COMMAND NEVER RETURNS null HERE, and the previous comment claiming it did was
      // the shim standing in for behaviour the app does not have. With no TEMPEST_LSP_* set,
      // `configured_servers()` is empty and the multiplexer answers
      // `Err(Unsupported { language })` — so a UI branch written against `ok(null)` would be
      // exercised by every E2E spec and taken by no user on a fresh install. `unsupported` is
      // also the ONE error `hoverSource` renders as silence, so the no-hover path is still what
      // gets exercised — now for the reason the shipped app has, not a fictional one.
      //
      // Thrown as a plain object, never an Error: that is what makes the generated `typedError`
      // wrapper produce `{status: "error", error}` rather than a rejected promise.
      if (cmd === "lsp_hover") {
        // Every call is recorded, so a spec can prove the webview REACHES this command at all —
        // which is the whole of Phase 20.5, and was false for the life of 20.2.
        hovered.push({
          repoPath: args.repoPath,
          path: args.path,
          line: args.line,
          character: args.character,
          textLength: String(args.text ?? "").length,
        });
        // A spec may script one answer, to exercise the rendered paths that a harness with no
        // Rust host and no installed language server cannot otherwise reach.
        if (scriptedHover !== null) {
          if (scriptedHover.error !== undefined) throw scriptedHover.error;
          return scriptedHover.ok ?? null;
        }
        const lower = String(args.path ?? "").toLowerCase();
        const language = lower.endsWith(".py") || lower.endsWith(".pyi")
          ? "python"
          : /\.(tsx?|js)$/.test(lower)
            ? "typescript"
            : "unknown";
        throw { kind: "unsupported", language };
      }
      // Host-side (commands.rs read_project_file): no sidecar behind it. The bridge does a real
      // read; the guard's rules live in Rust and are pinned there.
      if (cmd === "read_project_file") {
        const hosted = await fetch(`${bridgeUrl}/project-file`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ repo_path: args.repoPath, path: args.path }),
        });
        const payload = await hosted.json();
        if (payload.error !== undefined) throw payload.error;
        return payload;
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
    /** Every `lsp_hover` the webview has issued (Phase 20.5 reachability). */
    hovered,
    /** Script the next hover answer: {ok:{contents}} | {error:LspError} | null to reset. */
    scriptHover(reply) {
      scriptedHover = reply;
    },
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
