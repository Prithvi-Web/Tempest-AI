import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { clearAiKey, setAiKey, useAiKeyStatus } from "../hooks";

/** Settings (HANDOFF-WORLD-CLASS §3.2). The AI key group is the BYOK surface: the key lives
 * in the macOS Keychain only, the webview ever sees {configured, last4}, and the engine
 * receives it through its spawn environment. Copy here states exactly what is and is not
 * true today — the key is stored and delivered, and nothing calls Anthropic until the
 * harness-synthesis feature lands (no silent network, L8/L10). */
export function SettingsView() {
  const status = useAiKeyStatus();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setProblem(null);
    try {
      await setAiKey(draft);
      setDraft(""); // the plaintext leaves the page the moment the keychain has it
      await queryClient.invalidateQueries({ queryKey: ["aiKeyStatus"] });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "the key could not be saved");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setProblem(null);
    try {
      await clearAiKey();
      await queryClient.invalidateQueries({ queryKey: ["aiKeyStatus"] });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "the key could not be removed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>Settings</h1>

      <section className="settings-group" aria-labelledby="ai-key-heading">
        <h2 id="ai-key-heading">Anthropic API key</h2>
        <p className="group-note">
          Bring your own key: it is stored in the macOS Keychain — never in files, the
          database, logs, or run bundles — and is handed only to the engine process when it
          starts. It will power AI harness synthesis for hard-to-reach targets; until that
          feature ships, Tempest makes no network calls with it.
        </p>

        {status.isPending && <p className="dim">checking the keychain…</p>}
        {status.isError && (
          <p className="yellow">could not read key status — {status.error.message}</p>
        )}

        {status.data && status.data.configured && (
          <div className="keyrow">
            <p style={{ flex: 1, margin: 0 }}>
              Key configured
              {status.data.last4 ? (
                <span className="dim mono"> · ends in {status.data.last4}</span>
              ) : null}
            </p>
            <button className="destructive" disabled={busy} onClick={remove}>
              Remove key
            </button>
          </div>
        )}

        {status.data && !status.data.configured && (
          <>
            <label htmlFor="ai-key">API key</label>
            <div className="keyrow">
              <input
                id="ai-key"
                className="mono"
                type="password"
                placeholder="sk-ant-…"
                value={draft}
                autoComplete="off"
                onChange={(e) => setDraft(e.target.value)}
              />
              <button
                className="primary"
                disabled={busy || draft.trim() === ""}
                onClick={save}
              >
                {busy ? "Saving…" : "Save key"}
              </button>
            </div>
            <p className="group-note" style={{ marginTop: 8 }}>
              Create one at console.anthropic.com. A saved key applies the next time the
              engine starts.
            </p>
          </>
        )}

        {problem && (
          <div className="panel notproven">
            <strong className="yellow">could not save</strong>
            <p style={{ marginBottom: 0 }}>{problem}</p>
          </div>
        )}
      </section>

      <section className="settings-group" aria-labelledby="privacy-heading">
        <h2 id="privacy-heading">Privacy</h2>
        <p className="group-note" style={{ marginBottom: 0 }}>
          Tempest is local-first: proving, history, search, and evidence all work with the
          network unplugged, and nothing leaves this machine in local mode — proven by the
          egress gate in CI, not promised. Telemetry is off by default and stays off until
          you opt in (the opt-in switch arrives with the sync settings).
        </p>
      </section>
    </main>
  );
}
