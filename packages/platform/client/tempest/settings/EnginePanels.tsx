/**
 * The proof engine's settings, in the app's one settings home (ADR-0082).
 *
 * Storage, team sync, editor runners and privacy — every group from the proof surface's own
 * settings page except the two that are about how the assistant thinks, which moved to the
 * Models tab. Restyled into the client's own language for the reason `ModelsPanel` gives:
 * `tempest-views.css` ships with the proof surface's lazy chunk and would be absent here.
 *
 * The engine settings are ONE typed round trip (`useSettings`), so the panels below share it
 * through react-query's cache rather than each holding a copy. `save()` is optimistic and
 * then authoritative: the control moves the instant it is used — a switch that waits for a
 * round trip feels broken — and the ENGINE's reply replaces the guess, so an environment
 * override or a refused value visibly wins. A failure puts the old value back and says why.
 */

import { useQueryClient } from "@tanstack/react-query";
import { Button, Input, Slider, Spinner, Switch } from "@librechat/client";
import { useEffect, useState } from "react";

import type {
  EditorRunners,
  SettingsOut_Serialize,
  SyncReport,
} from "../../../../desktop/src/generated/bindings";
import {
  exportDiagnostics,
  revealInDataDir,
  syncPush,
  updateEditorRunners,
  updateSettings,
  useEditorRunners,
  useSettings,
} from "../views/hooks";
import { BUDGET_STEPS_MIB, budgetBytesAt, budgetIndex, bytesLabel, forcedBy } from "./format";

/** "forced by TEMPEST_X" — a setting the process environment is holding, said out loud. */
function Forced({ variable }: { variable: string | null }): JSX.Element | null {
  if (variable === null) return null;
  return (
    <span className="font-mono text-xs text-text-tertiary" role="note">
      forced by {variable}
    </span>
  );
}

/** The shared read of the engine's settings document, with its two honest non-states. */
function useEngineSettings() {
  const settings = useSettings();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const data: SettingsOut_Serialize | undefined = settings.data;

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

  return { settings, data, busy, problem, save, act };
}

/** Loading and unreachable, rendered once so four panels do not each invent their own. */
function EngineState({
  settings,
  problem,
}: {
  settings: ReturnType<typeof useSettings>;
  problem: string | null;
}): JSX.Element | null {
  if (settings.isLoading) {
    return (
      <p className="flex items-center gap-2 text-sm text-text-secondary">
        <Spinner className="size-4" />
        reading settings…
      </p>
    );
  }
  if (settings.isError || !settings.data) {
    return (
      <p className="text-sm text-text-warning" role="alert">
        settings could not be read — {settings.error?.message ?? "the engine did not answer"}
      </p>
    );
  }
  if (problem !== null) {
    return (
      <p className="text-sm text-text-warning" role="alert">
        that change was not saved — {problem}
      </p>
    );
  }
  return null;
}

export function StoragePanel(): JSX.Element {
  const { settings, data, busy, problem, save, act } = useEngineSettings();
  const state = <EngineState settings={settings} problem={problem} />;
  if (!data) return <div className="flex flex-col gap-3">{state}</div>;
  const budgetForced = forcedBy(data.env_overrides, "bundle_budget_bytes");

  return (
    <div className="flex flex-col gap-3">
      {state}
      <p className="text-sm text-text-secondary">
        Run bundles are the evidence behind every verdict — kept locally so any past run can be
        re-read and re-run. When a budget is set and an ingest passes it, the oldest runs are
        dropped first; the newest run is never dropped.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="tempest-budget" className="text-sm text-text-primary">
          Bundle budget
        </label>
        <Slider
          id="tempest-budget"
          className="w-48"
          min={0}
          max={BUDGET_STEPS_MIB.length - 1}
          step={1}
          disabled={busy || budgetForced !== null}
          value={[budgetIndex(data.bundle_budget_bytes)]}
          onValueChange={([index]) =>
            void save({ bundle_budget_bytes: budgetBytesAt(index ?? 0) })
          }
          aria-label="Bundle budget"
        />
        <span className="text-sm text-text-secondary" data-testid="budget-value">
          {data.bundle_budget_bytes === 0 ? "unlimited" : bytesLabel(data.bundle_budget_bytes)}
        </span>
        <Forced variable={budgetForced} />
      </div>
      <p className="text-sm text-text-secondary">
        Bundles currently use <strong>{bytesLabel(data.store_bytes)}</strong> in{" "}
        <span className="font-mono text-xs">{data.data_dir}</span>.
      </p>
      <div>
        <Button
          size="sm"
          variant="subtle"
          disabled={busy}
          data-testid="open-data-folder"
          onClick={() =>
            void act(
              async () => void (await revealInDataDir(null)),
              "the folder could not be opened",
            )
          }
        >
          Open data folder
        </Button>
      </div>
    </div>
  );
}

export function SyncPanel(): JSX.Element {
  const { settings, data, busy, problem, save, act } = useEngineSettings();
  const [urlDraft, setUrlDraft] = useState<string | null>(null);
  const [pushReport, setPushReport] = useState<SyncReport | null>(null);

  // The URL field is the one control the user types into; it tracks the server value until
  // they start editing, and never fights their cursor afterwards.
  useEffect(() => {
    if (data && urlDraft === null) setUrlDraft(data.sync_server_url ?? "");
  }, [data, urlDraft]);

  const state = <EngineState settings={settings} problem={problem} />;
  if (!data) return <div className="flex flex-col gap-3">{state}</div>;
  const urlForced = forcedBy(data.env_overrides, "sync_server_url");
  const shareForced = forcedBy(data.env_overrides, "sync_share_source");
  const serverUrl = data.sync_server_url ?? "";

  return (
    <div className="flex flex-col gap-3">
      {state}
      <p className="text-sm text-text-secondary">
        Optional. Tempest is fully usable with no server at all — proving, history, search, and
        evidence are local. A push sends finished run bundles to a team server you choose, and
        nothing is sent until you press Push now.
      </p>
      <label htmlFor="tempest-sync-url" className="text-sm text-text-primary">
        Team server URL
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id="tempest-sync-url"
          className="flex-1 font-mono"
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
        <Button
          size="sm"
          variant="subtle"
          disabled={busy || serverUrl === ""}
          data-testid="sync-push"
          onClick={() =>
            void act(async () => {
              setPushReport(await syncPush(serverUrl));
            }, "the push could not be started")
          }
        >
          Push now
        </Button>
      </div>
      <Forced variable={urlForced} />

      <div className="flex items-center justify-between gap-3">
        <label htmlFor="tempest-share-source" className="text-sm text-text-primary">
          Include source code in pushed bundles
        </label>
        <div className="flex items-center gap-2">
          <Forced variable={shareForced} />
          <Switch
            id="tempest-share-source"
            data-testid="share-source"
            aria-label="Include source code in pushed bundles"
            checked={data.sync_share_source}
            disabled={busy || shareForced !== null}
            onCheckedChange={(next) => void save({ sync_share_source: next })}
          />
        </div>
      </div>
      <p className="text-sm text-text-secondary">
        Off by default. With it off, repro scripts and every string mined from your code are
        replaced by one-way hashes before a bundle leaves this machine; verdicts, counts, and
        structure still cross, so shared evidence stays readable.
      </p>

      {pushReport && (
        <div className="rounded-xl border border-border-light p-3" role="status">
          <strong className="text-sm text-text-primary">Push finished</strong>
          <p className="text-sm text-text-secondary">
            {pushReport.pushed} pushed · {pushReport.skipped} already there ·{" "}
            {pushReport.failed} failed · {pushReport.remaining} still to go (of{" "}
            {pushReport.candidates}).
          </p>
          {pushReport.errors.length > 0 && (
            <ul className="list-disc pl-5 text-sm text-text-tertiary">
              {pushReport.errors.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** The editor's three runners (Phase 20.6): a place to type the command, and a statement of
 * whether it can be FOUND. All three were environment-variable-only, which made them
 * undiscoverable — and an undiscoverable feature is one nobody has. */
export function EditorRunnersPanel(): JSX.Element {
  const runners = useEditorRunners();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<EditorRunners | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const stored = draft ?? runners.data?.stored ?? null;
  const forcedVar = (field: string): string | null =>
    runners.data?.forced.find((o) => o.field === field)?.variable ?? null;
  const statusOf = (field: string) => runners.data?.status.find((s) => s.field === field) ?? null;

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

  async function save(next: EditorRunners) {
    setBusy(true);
    setProblem(null);
    try {
      await updateEditorRunners(next);
      setDraft(null);
      await queryClient.invalidateQueries({ queryKey: ["editorRunners"] });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "the runners were not saved");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-text-secondary">
        Programs on this machine that Tempest starts for you: a language server for hover, and a
        local model for F11 completions. Both are optional and neither is bundled — they are
        yours, they run locally, and nothing here is sent anywhere. Leave a box empty to turn
        that runner off; the editor keeps working without it.
      </p>

      {runners.isError && (
        <p className="text-sm text-text-warning" role="alert">
          {runners.error.message}
        </p>
      )}
      {problem !== null && (
        <p className="text-sm text-text-warning" role="alert">
          {problem}
        </p>
      )}

      {stored !== null &&
        FIELDS.map(({ key, label, hint, example }) => {
          const variable = forcedVar(key);
          const status = statusOf(key);
          return (
            <div key={key} className="flex flex-col gap-1.5">
              <label htmlFor={`runner-${key}`} className="text-sm text-text-primary">
                {label}
              </label>
              <Input
                id={`runner-${key}`}
                data-testid={`runner-${key}`}
                className="font-mono"
                type="text"
                spellCheck={false}
                autoComplete="off"
                placeholder={example}
                value={stored[key] ?? ""}
                disabled={busy || variable !== null}
                onChange={(e) => setDraft({ ...stored, [key]: e.target.value })}
              />
              <p className="text-sm text-text-secondary">
                {hint} <Forced variable={variable} />
                {/* Whether the program can be FOUND, stated. "I typed it and nothing happened"
                    is the failure this surface exists to prevent, and a missing binary looks
                    exactly like a broken one from the outside. */}
                {status !== null && status.command.trim() !== "" ? (
                  <span
                    data-testid={`runner-status-${key}`}
                    className={status.found ? "text-text-tertiary" : "text-text-warning"}
                  >
                    {" "}
                    {status.found
                      ? `found: ${status.command}`
                      : `not found on this machine: ${status.command}`}
                  </span>
                ) : (
                  <span data-testid={`runner-status-${key}`} className="text-text-tertiary">
                    {" "}
                    not configured
                  </span>
                )}
              </p>
            </div>
          );
        })}

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="subtle"
          data-testid="save-runners"
          disabled={busy || draft === null}
          onClick={() => void (draft !== null && save(draft))}
        >
          {busy ? "Saving…" : "Save runners"}
        </Button>
        {draft !== null && (
          <Button size="sm" variant="subtle" disabled={busy} onClick={() => setDraft(null)}>
            Discard
          </Button>
        )}
      </div>
      <p className="text-sm text-text-secondary">
        Saved to{" "}
        <span className="font-mono text-xs">{runners.data?.path ?? "the app data folder"}</span>.
        Changing a language server stops the one already running, so the next hover starts the
        one you named rather than the one you replaced.
      </p>
    </div>
  );
}

export function TelemetryPanel(): JSX.Element {
  const { settings, data, busy, problem, save } = useEngineSettings();
  const state = <EngineState settings={settings} problem={problem} />;
  if (!data) return <div className="flex flex-col gap-3">{state}</div>;
  const telemetryForced = forcedBy(data.env_overrides, "telemetry_enabled");

  return (
    <div className="flex flex-col gap-3">
      {state}
      <p className="text-sm text-text-secondary">
        Tempest is local-first: proving, history, search, and evidence all work with the network
        unplugged, and nothing leaves this machine in local mode — proven by the egress gate in
        CI, not promised.
      </p>
      <div className="flex items-center justify-between gap-3">
        <label htmlFor="tempest-telemetry" className="text-sm text-text-primary">
          Share anonymous usage counters
        </label>
        <div className="flex items-center gap-2">
          <Forced variable={telemetryForced} />
          <Switch
            id="tempest-telemetry"
            data-testid="telemetry"
            aria-label="Share anonymous usage counters"
            checked={data.telemetry_enabled}
            disabled={busy || telemetryForced !== null}
            onCheckedChange={(next) => void save({ telemetry_enabled: next })}
          />
        </div>
      </div>
      <p className="text-sm text-text-secondary">
        Off by default. Counters only — how many runs, which verdicts, which UNPROVEN reasons,
        which sandbox tiers. No paths, no repository names, no source, no per-run timestamps.
        The file stays on this machine; it travels only inside a diagnostic bundle you export
        and send yourself.
      </p>
    </div>
  );
}

export function DiagnosticsPanel(): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [diagnostic, setDiagnostic] = useState<{ filename: string; manifest: string } | null>(
    null,
  );

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

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="subtle"
          disabled={busy}
          data-testid="export-diagnostics"
          onClick={() =>
            void act(async () => {
              const bundle = await exportDiagnostics();
              setDiagnostic({ filename: bundle.filename, manifest: bundle.manifest });
            }, "the diagnostic bundle could not be written")
          }
        >
          {busy ? "Working…" : "Export diagnostic bundle"}
        </Button>
        {diagnostic && (
          <Button
            size="sm"
            variant="subtle"
            disabled={busy}
            data-testid="reveal-diagnostics"
            onClick={() =>
              void act(
                async () => void (await revealInDataDir(diagnostic.filename)),
                "the bundle could not be revealed",
              )
            }
          >
            Show in Finder
          </Button>
        )}
      </div>
      {problem && (
        <p className="text-sm text-text-warning" role="alert">
          {problem}
        </p>
      )}
      {diagnostic && (
        <div className="rounded-xl border border-border-light p-3" role="status">
          <strong className="text-sm text-text-primary">Wrote {diagnostic.filename}</strong>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-xs text-text-secondary">
            {diagnostic.manifest}
          </pre>
        </div>
      )}
      <p className="text-sm text-text-secondary">
        Everything in that archive passes the redaction engine first, and nothing is sent
        anywhere by exporting it — read it, then decide. The full policy is docs/PRIVACY.md in
        the Tempest repository.
      </p>
    </div>
  );
}
