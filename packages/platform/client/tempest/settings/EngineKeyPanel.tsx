/**
 * The proof engine's own Anthropic key, in the app's one settings home (ADR-0082).
 *
 * `AiKeyGroup` from the proof surface's settings page, restyled into the client's own
 * language. It sits in the Models tab beside the provider keys and the local models, because
 * the owner's requirement is that a person choosing how the assistant thinks should not have
 * to know whether the answer is "download this" or "paste a key".
 *
 * It is NOT the same key as the chat provider keys above it, and the copy says so: this one
 * is spent on harness synthesis inside the proof engine, and a user who has a chat key
 * configured would otherwise reasonably assume proving was already funded.
 *
 * Two honesty rules survive the move. The key lives in the macOS Keychain and nowhere else —
 * the webview only ever learns `{configured, last4}` (L9). And the plaintext leaves the page
 * the moment the keychain has it.
 */

import { useQueryClient } from "@tanstack/react-query";
import { Button, Input, Spinner } from "@librechat/client";
import { useState } from "react";

import { clearAiKey, setAiKey, testAiKey, useAiKeyStatus } from "../views/hooks";

export default function EngineKeyPanel(): JSX.Element {
  const status = useAiKeyStatus();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [ping, setPing] = useState<{ ok: boolean; detail: string } | null>(null);

  async function run(action: () => Promise<unknown>, fallback: string) {
    setBusy(true);
    setProblem(null);
    try {
      await action();
      await queryClient.invalidateQueries({ queryKey: ["aiKeyStatus"] });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-text-secondary">
        Bring your own key: it is stored in the macOS Keychain — never in files, the database,
        logs, or run bundles — and is handed only to the engine process when it starts. It
        powers AI harness synthesis: when an instance method cannot be reached directly,
        Tempest asks the model to write a small adapter, validates it by real execution, and
        caches it in your repo so later runs replay offline. That synthesis request is the only
        network call the key is ever used for — your diff itself is never uploaded, only the
        changed class&apos;s source. Without a key, those targets are reported UNPROVEN.
      </p>

      {status.isLoading && (
        <p className="flex items-center gap-2 text-sm text-text-secondary">
          <Spinner className="size-4" />
          checking the keychain…
        </p>
      )}
      {status.isError && (
        <p className="text-sm text-text-warning">
          could not read key status — {status.error.message}
        </p>
      )}

      {status.data && status.data.configured && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <p className="flex-1 text-sm text-text-primary">
              Key configured
              {status.data.last4 ? (
                <span className="ml-1 font-mono text-xs text-text-tertiary">
                  ends in {status.data.last4}
                </span>
              ) : null}
            </p>
            <Button
              size="sm"
              variant="subtle"
              disabled={busy}
              data-testid="test-engine-key"
              onClick={() =>
                void run(async () => {
                  const result = await testAiKey();
                  setPing({ ok: result.ok, detail: result.detail });
                }, "the key could not be tested")
              }
            >
              {busy ? "Testing…" : "Test key"}
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={busy}
              data-testid="remove-engine-key"
              onClick={() => void run(clearAiKey, "the key could not be removed")}
            >
              Remove key
            </Button>
          </div>
          <p className="text-sm text-text-secondary">
            Testing sends one tiny request (a single token) to the model to confirm the key
            works. No source, no repo name, and nothing about your code goes with it.
          </p>
          {ping && (
            <p
              className={ping.ok ? "text-sm text-status-success" : "text-sm text-text-warning"}
              role="status"
            >
              {ping.detail}
            </p>
          )}
        </>
      )}

      {status.data && !status.data.configured && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              id="tempest-engine-key"
              className="flex-1 font-mono"
              type="password"
              placeholder="sk-ant-…"
              aria-label="Anthropic API key for the proof engine"
              value={draft}
              autoComplete="off"
              data-testid="engine-key-input"
              onChange={(e) => setDraft(e.target.value)}
            />
            <Button
              size="sm"
              disabled={busy || draft.trim() === ""}
              data-testid="save-engine-key"
              onClick={() =>
                void run(async () => {
                  await setAiKey(draft);
                  setDraft(""); // the plaintext leaves the page the moment the keychain has it
                }, "the key could not be saved")
              }
            >
              {busy ? "Saving…" : "Save key"}
            </Button>
          </div>
          <p className="text-sm text-text-secondary">
            Create one at console.anthropic.com. A saved key applies the next time the engine
            starts. You do not need one to chat — a local model runs with no key at all.
          </p>
        </>
      )}

      {problem && (
        <p className="text-sm text-text-warning" role="alert">
          that did not work — {problem}
        </p>
      )}
    </div>
  );
}
