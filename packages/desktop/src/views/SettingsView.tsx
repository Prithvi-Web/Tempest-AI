import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type {
  EditorRunners,
  EnvOverride,
  SettingsOut_Serialize,
  SyncReport,
} from "../generated/bindings";
import {
  clearAiKey,
  exportDiagnostics,
  revealInDataDir,
  setAiKey,
  syncPush,
  testAiKey,
  updateEditorRunners,
  updateSettings,
  useAiKeyStatus,
  useEditorRunners,
  useSettings,
} from "../hooks";

/** Settings (HANDOFF-WORLD-CLASS §3.2), four groups over one typed round trip.
 *
 * Two honesty rules run through every group. First, the key lives in the macOS Keychain and
 * nowhere else — the webview only ever learns {configured, last4} (L9). Second, a setting the
 * process ENVIRONMENT is forcing is shown as forced: the control is disabled and names the
 * variable, because a toggle that silently disagrees with reality is a lie. Copy states what
 * is true today, never what is planned. */

const MIB = 1024 * 1024;
const BUDGET_STEPS_MIB = [0, 100, 250, 500, 1000, 2000] as const;

function forced(overrides: EnvOverride[], field: string): string | null {
  return overrides.find((o) => o.field === field)?.variable ?? null;
}

/** The slider position for a stored budget: the first step that covers it, or the top step
 * when a hand-edited file (or an environment override) asks for more than the slider offers. */
function budgetIndex(bytes: number): number {
  const mib = Math.round(bytes / MIB);
  const found = BUDGET_STEPS_MIB.findIndex((step) => step >= mib);
  return found === -1 ? BUDGET_STEPS_MIB.length - 1 : found;
}

function budgetBytesAt(index: number): number {
  return (BUDGET_STEPS_MIB[index] ?? 0) * MIB;
}

function bytesLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < MIB) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * MIB) return `${(bytes / MIB).toFixed(1)} MB`;
  return `${(bytes / (1024 * MIB)).toFixed(2)} GB`;
}

/** A labelled switch that renders its own "forced by the environment" state. */
function Toggle({
  id,
  checked,
  onChange,
  label,
  disabledBy,
  busy,
}: {
  id: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabledBy: string | null;
  busy: boolean;
}) {
  return (
    <div className="setting-row">
      <label htmlFor={id} className="setting-label">
        {label}
      </label>
      <input
        id={id}
        type="checkbox"
        role="switch"
        className="switch"
        checked={checked}
        disabled={busy || disabledBy !== null}
        onChange={(e) => onChange(e.target.checked)}
      />
      {disabledBy !== null && (
        <span className="forced" role="note">
          forced by {disabledBy}
        </span>
      )}
    </div>
  );
}

/** The editor's two runners (Phase 20.6).
 *
 * Both were environment-variable-only until now, which made them undiscoverable — and an
 * undiscoverable feature is one nobody has. This is the whole of what the handoff called item 2
 * of three: a place to type the command, a statement of whether it can be FOUND, and the same
 * "forced by the environment" honesty the groups above already keep. */
function EditorRunnersGroup() {
  const runners = useEditorRunners();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<EditorRunners | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const stored = draft ?? runners.data?.stored ?? null;
  const forcedBy = (field: string): string | null =>
    runners.data?.forced.find((o) => o.field === field)?.variable ?? null;
  const statusOf = (field: string) => runners.data?.status.find((s) => s.field === field) ?? null;

  async function save(next: EditorRunners) {
    setBusy(true);
    setProblem(null);
    try {
      await updateEditorRunners(next);
      setDraft(null);
      await queryClient.invalidateQueries({ queryKey: ["editorRunners"] });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "the editor settings could not be saved");
    } finally {
      setBusy(false);
    }
  }

  const FIELDS: { key: keyof EditorRunners; label: string; hint: string; example: string }[] = [
    {
      key: "python_lsp",
      label: "Python language server",
      hint: "Powers hover in .py files.",
      example: "pyright-langserver --stdio",
    },
    {
      key: "typescript_lsp",
      label: "TypeScript language server",
      hint: "Powers hover in .ts, .tsx and .js files.",
      example: "typescript-language-server --stdio",
    },
    {
      key: "local_model",
      label: "Local completion model",
      hint: "Powers F11. Without it, F11 still works from the open document.",
      example: "llama-cli -m /models/qwen.gguf",
    },
  ];

  return (
    <section className="settings-group" aria-labelledby="runners-heading">
      <h2 id="runners-heading">Editor runners</h2>
      <p className="group-note">
        Programs on this machine that Tempest starts for you: a language server for hover, and a
        local model for F11 completions. Both are optional and neither is bundled — they are
        yours, they run locally, and nothing here is sent anywhere. Leave a box empty to turn
        that runner off; the editor keeps working without it.
      </p>

      {runners.isError && (
        <p className="yellow" role="alert">
          {runners.error.message}
        </p>
      )}
      {problem !== null && (
        <p className="yellow" role="alert">
          {problem}
        </p>
      )}

      {stored !== null &&
        FIELDS.map(({ key, label, hint, example }) => {
          const variable = forcedBy(key);
          const status = statusOf(key);
          return (
            <div key={key} className="setting-stack">
              <label htmlFor={`runner-${key}`} className="setting-label">
                {label}
              </label>
              <input
                id={`runner-${key}`}
                data-testid={`runner-${key}`}
                type="text"
                spellCheck={false}
                autoComplete="off"
                placeholder={example}
                value={stored[key]}
                disabled={busy || variable !== null}
                onChange={(e) => setDraft({ ...stored, [key]: e.target.value })}
              />
              <p className="group-note" style={{ marginTop: 4, marginBottom: 0 }}>
                {hint}{" "}
                {variable !== null ? (
                  <span className="forced" role="note">
                    forced by {variable}
                  </span>
                ) : null}
                {/* Whether the program can be FOUND, stated. "I typed it and nothing happened"
                    is the failure this surface exists to prevent, and a missing binary looks
                    exactly like a broken one from the outside. */}
                {status !== null && status.command.trim() !== "" ? (
                  <span
                    data-testid={`runner-status-${key}`}
                    className={status.found ? "dim" : "yellow"}
                  >
                    {" "}
                    {status.found
                      ? `found: ${status.command}`
                      : `not found on this machine: ${status.command}`}
                  </span>
                ) : (
                  <span data-testid={`runner-status-${key}`} className="dim">
                    {" "}
                    not configured
                  </span>
                )}
              </p>
            </div>
          );
        })}

      <div className="keyrow" style={{ marginTop: 12 }}>
        <button
          data-testid="save-runners"
          disabled={busy || draft === null}
          onClick={() => void (draft !== null && save(draft))}
        >
          {busy ? "Saving…" : "Save runners"}
        </button>
        {draft !== null && (
          <button disabled={busy} onClick={() => setDraft(null)}>
            Discard
          </button>
        )}
      </div>
      <p className="group-note" style={{ marginTop: 10, marginBottom: 0 }}>
        Saved to <span className="mono">{runners.data?.path ?? "the app data folder"}</span>.
        Changing a language server stops the one already running, so the next hover starts the
        one you named rather than the one you replaced.
      </p>
    </section>
  );
}

function AiKeyGroup() {
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
    <section className="settings-group" aria-labelledby="ai-key-heading">
      <h2 id="ai-key-heading">Anthropic API key</h2>
      <p className="group-note">
        Bring your own key: it is stored in the macOS Keychain — never in files, the database,
        logs, or run bundles — and is handed only to the engine process when it starts. It
        powers AI harness synthesis: when an instance method cannot be reached directly,
        Tempest asks the model to write a small adapter, validates it by real execution, and
        caches it in your repo so later runs replay offline. That synthesis request is the
        only network call the key is ever used for — your diff itself is never uploaded, only
        the changed class&apos;s source. Without a key, those targets are reported UNPROVEN.
      </p>
      {status.isPending && <p className="dim">checking the keychain…</p>}
      {status.isError && (
        <p className="yellow">could not read key status — {status.error.message}</p>
      )}

      {status.data && status.data.configured && (
        <>
          <div className="keyrow">
            <p style={{ flex: 1, margin: 0 }}>
              Key configured
              {status.data.last4 ? (
                <span className="dim mono"> · ends in {status.data.last4}</span>
              ) : null}
            </p>
            <button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const result = await testAiKey();
                  setPing({ ok: result.ok, detail: result.detail });
                }, "the key could not be tested")
              }
            >
              {busy ? "Testing…" : "Test key"}
            </button>
            <button className="destructive" disabled={busy} onClick={() => void run(clearAiKey, "the key could not be removed")}>
              Remove key
            </button>
          </div>
          <p className="group-note" style={{ marginTop: 8 }}>
            Testing sends one tiny request (a single token) to the model to confirm the key
            works. No source, no repo name, and nothing about your code goes with it.
          </p>
          {ping && (
            <p className={ping.ok ? "green" : "yellow"} role="status">
              {ping.detail}
            </p>
          )}
        </>
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
              onClick={() =>
                void run(async () => {
                  await setAiKey(draft);
                  setDraft(""); // the plaintext leaves the page the moment the keychain has it
                }, "the key could not be saved")
              }
            >
              {busy ? "Saving…" : "Save key"}
            </button>
          </div>
          <p className="group-note" style={{ marginTop: 8 }}>
            Create one at console.anthropic.com. A saved key applies the next time the engine
            starts.
          </p>
        </>
      )}

      {problem && (
        <div className="panel notproven">
          <strong className="yellow">that did not work</strong>
          <p style={{ marginBottom: 0 }}>{problem}</p>
        </div>
      )}
    </section>
  );
}

export function SettingsView() {
  const settings = useSettings();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [urlDraft, setUrlDraft] = useState<string | null>(null);
  const [pushReport, setPushReport] = useState<SyncReport | null>(null);
  const [diagnostic, setDiagnostic] = useState<{ filename: string; manifest: string } | null>(
    null,
  );

  const data: SettingsOut_Serialize | undefined = settings.data;

  // The URL field is the one control the user types into; it tracks the server value until
  // they start editing, and never fights their cursor afterwards.
  useEffect(() => {
    if (data && urlDraft === null) setUrlDraft(data.sync_server_url ?? "");
  }, [data, urlDraft]);

  /** Optimistic, then authoritative: the control moves the instant it is used (a switch that
   * waits for a round trip feels broken), and the ENGINE's reply replaces the guess — so an
   * environment override or a refused value visibly wins. A failure puts the old value back
   * and says why; the UI never keeps a state the engine did not accept. */
  async function save(patch: Partial<SettingsOut_Serialize>) {
    if (!data) return;
    const previous = data;
    const next = { ...data, ...patch };
    queryClient.setQueryData(["getSettings"], next);
    setBusy(true);
    setProblem(null);
    try {
      const saved = await updateSettings({
        sync_server_url: next.sync_server_url ?? null,
        sync_share_source: next.sync_share_source,
        bundle_budget_bytes: next.bundle_budget_bytes,
        telemetry_enabled: next.telemetry_enabled,
      });
      queryClient.setQueryData(["getSettings"], saved);
    } catch (err) {
      queryClient.setQueryData(["getSettings"], previous);
      setProblem(err instanceof Error ? err.message : "the setting could not be saved");
    } finally {
      setBusy(false);
    }
  }

  async function act(action: () => Promise<void>, fallback: string) {
    setBusy(true);
    setProblem(null);
    try {
      await action();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  if (settings.isPending) {
    return (
      <main>
        <h1>Settings</h1>
        <p className="dim">loading settings…</p>
      </main>
    );
  }
  if (settings.isError || !data) {
    return (
      <main>
        <h1>Settings</h1>
        <div className="panel notproven">
          <strong className="yellow">settings could not be read</strong>
          <p style={{ marginBottom: 0 }}>
            {settings.error?.message ?? "the engine did not answer"}
          </p>
        </div>
      </main>
    );
  }

  const overrides = data.env_overrides;
  const budgetForced = forced(overrides, "bundle_budget_bytes");
  const urlForced = forced(overrides, "sync_server_url");
  const serverUrl = data.sync_server_url ?? "";

  return (
    <main>
      <h1>Settings</h1>

      {data.problem !== null && (
        <div className="panel notproven" role="alert">
          <strong className="yellow">the settings file could not be read</strong>
          <p style={{ marginBottom: 0 }}>
            {data.problem} Changing any setting below writes a fresh, valid file.
          </p>
        </div>
      )}
      {problem && (
        <div className="panel notproven" role="alert">
          <strong className="yellow">that change was not saved</strong>
          <p style={{ marginBottom: 0 }}>{problem}</p>
        </div>
      )}

      <AiKeyGroup />

      <section className="settings-group" aria-labelledby="sync-heading">
        <h2 id="sync-heading">Sync</h2>
        <p className="group-note">
          Optional. Tempest is fully usable with no server at all — proving, history, search,
          and evidence are local. A push sends finished run bundles to a team server you
          choose, and nothing is sent until you press Push now.
        </p>

        <label htmlFor="sync-url">Team server URL</label>
        <div className="keyrow">
          <input
            id="sync-url"
            className="mono"
            type="url"
            inputMode="url"
            placeholder="https://tempest.your-company.com"
            value={urlForced !== null ? serverUrl : (urlDraft ?? "")}
            disabled={busy || urlForced !== null}
            onChange={(e) => setUrlDraft(e.target.value)}
            onBlur={() => {
              if (urlForced === null && (urlDraft ?? "") !== serverUrl) {
                void save({ sync_server_url: urlDraft === "" ? null : urlDraft });
              }
            }}
          />
          <button
            disabled={busy || serverUrl === ""}
            onClick={() =>
              void act(async () => {
                setPushReport(await syncPush(serverUrl));
              }, "the push could not be started")
            }
          >
            Push now
          </button>
        </div>
        {urlForced !== null && (
          <p className="forced" role="note">
            forced by {urlForced}
          </p>
        )}

        <Toggle
          id="share-source"
          label="Include source code in pushed bundles"
          checked={data.sync_share_source}
          disabledBy={forced(overrides, "sync_share_source")}
          busy={busy}
          onChange={(next) => void save({ sync_share_source: next })}
        />
        <p className="group-note" style={{ marginTop: 6 }}>
          Off by default. With it off, repro scripts and every string mined from your code are
          replaced by one-way hashes before a bundle leaves this machine; verdicts, counts, and
          structure still cross, so shared evidence stays readable.
        </p>

        {pushReport && (
          <div className="panel" role="status">
            <strong>Push finished</strong>
            <p style={{ marginBottom: 0 }}>
              {pushReport.pushed} pushed · {pushReport.skipped} already there ·{" "}
              {pushReport.failed} failed · {pushReport.remaining} still to go (of{" "}
              {pushReport.candidates}).
            </p>
            {pushReport.errors.length > 0 && (
              <ul className="dim" style={{ marginBottom: 0 }}>
                {pushReport.errors.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <section className="settings-group" aria-labelledby="storage-heading">
        <h2 id="storage-heading">Storage</h2>
        <p className="group-note">
          Run bundles are the evidence behind every verdict — kept locally so any past run can
          be re-read and re-run. When a budget is set and an ingest passes it, the oldest runs
          are dropped first; the newest run is never dropped.
        </p>

        <div className="setting-row">
          <label htmlFor="budget" className="setting-label">
            Bundle budget
          </label>
          <input
            id="budget"
            type="range"
            className="slider"
            min={0}
            max={BUDGET_STEPS_MIB.length - 1}
            step={1}
            disabled={busy || budgetForced !== null}
            value={budgetIndex(data.bundle_budget_bytes)}
            onChange={(e) =>
              void save({ bundle_budget_bytes: budgetBytesAt(Number(e.target.value)) })
            }
          />
          <span className="setting-value">
            {data.bundle_budget_bytes === 0 ? "unlimited" : bytesLabel(data.bundle_budget_bytes)}
          </span>
          {budgetForced !== null && (
            <span className="forced" role="note">
              forced by {budgetForced}
            </span>
          )}
        </div>

        <p className="group-note" style={{ marginTop: 10 }}>
          Bundles currently use <strong>{bytesLabel(data.store_bytes)}</strong> in{" "}
          <span className="mono">{data.data_dir}</span>.
        </p>
        <button
          disabled={busy}
          onClick={() => void act(async () => void (await revealInDataDir(null)), "the folder could not be opened")}
        >
          Open data folder
        </button>
      </section>

      <EditorRunnersGroup />

      <section className="settings-group" aria-labelledby="privacy-heading">
        <h2 id="privacy-heading">Privacy</h2>
        <p className="group-note">
          Tempest is local-first: proving, history, search, and evidence all work with the
          network unplugged, and nothing leaves this machine in local mode — proven by the
          egress gate in CI, not promised.
        </p>

        <Toggle
          id="telemetry"
          label="Share anonymous usage counters"
          checked={data.telemetry_enabled}
          disabledBy={forced(overrides, "telemetry_enabled")}
          busy={busy}
          onChange={(next) => void save({ telemetry_enabled: next })}
        />
        <p className="group-note" style={{ marginTop: 6 }}>
          Off by default. Counters only — how many runs, which verdicts, which UNPROVEN
          reasons, which sandbox tiers. No paths, no repository names, no source, no
          per-run timestamps. The file stays on this machine; it travels only inside a
          diagnostic bundle you export and send yourself.
        </p>

        <div className="keyrow" style={{ marginTop: 14 }}>
          <button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                const bundle = await exportDiagnostics();
                setDiagnostic({ filename: bundle.filename, manifest: bundle.manifest });
              }, "the diagnostic bundle could not be written")
            }
          >
            {busy ? "Working…" : "Export diagnostic bundle"}
          </button>
          {diagnostic && (
            <button
              disabled={busy}
              onClick={() =>
                void act(
                  async () => void (await revealInDataDir(diagnostic.filename)),
                  "the bundle could not be revealed",
                )
              }
            >
              Show in Finder
            </button>
          )}
        </div>
        {diagnostic && (
          <div className="panel" role="status">
            <strong>Wrote {diagnostic.filename}</strong>
            <pre className="mono-block">{diagnostic.manifest}</pre>
          </div>
        )}
        <p className="group-note" style={{ marginTop: 10, marginBottom: 0 }}>
          Everything in that archive passes the redaction engine first, and nothing is sent
          anywhere by exporting it — read it, then decide. The full policy is docs/PRIVACY.md
          in the Tempest repository.
        </p>
      </section>
    </main>
  );
}
