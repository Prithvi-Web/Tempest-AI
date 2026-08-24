/**
 * Local models, in the app's ONE settings home (ADR-0082).
 *
 * This is `LocalModelsGroup` from the proof surface's own settings page, moved. The owner's
 * words: *"I would like to be able to download local models on the vertical navigation bar
 * for the AI Tempest… people should be able to use local models or api keys for that."*
 * Downloading a model is a chat-app concern — it is how the assistant thinks — and it was
 * three clicks deep behind the proof surface, which is a TOOL the assistant uses (ADR-0067).
 *
 * **Restyled, not merely relocated.** The old markup used `tempest-views.css`, which loads
 * with the proof surface's lazy chunk — a class from there is unstyled for anyone who has not
 * opened that surface, which is the exact trap `LocalModelRemedy.tsx` documents. Every class
 * here is the vendored client's own, which is also what stops this reading as a panel bolted
 * onto someone else's app.
 *
 * The honesty rules are unchanged, because they were right. The SIZE and the free space are
 * on screen before the button, since gigabytes are a cost and L21 says a cost is visible
 * before it is spent. A model that will not fit says so rather than failing halfway. And the
 * runner is resolved on every status read, so a missing one is stated BEFORE anyone presses
 * Serve rather than as a refusal afterwards.
 */

import { useQueryClient } from "@tanstack/react-query";
import { Button, Progress, Spinner } from "@librechat/client";
import { useState } from "react";
import type { ReactNode } from "react";

import type { ModelCatalogRow } from "../../../../desktop/src/generated/bindings";
import {
  cancelModelDownload,
  removeModel,
  startModelDownload,
  startModelServer,
  stopModelServer,
  useModelCatalog,
  useModelServerStatus,
} from "../views/hooks";
import { gb } from "./format";

/** One line of state under a row — the panel's whole vocabulary for "what is true here". */
function Note({
  tone = "quiet",
  testId,
  alert = false,
  children,
}: {
  tone?: "quiet" | "warn";
  testId?: string;
  alert?: boolean;
  /** Imported by NAME, not reached through the `React.` global namespace. Two copies of
   *  `@types/react` resolve in this workspace, and this file is compiled by two projects —
   *  the seam's own tsconfig and, since `settingsManifest.test.ts` imports the manifest, the
   *  desktop package's. Through the global namespace those two projects disagreed about
   *  whether `ReactNode` includes `bigint`, and `make verify`'s node leg went red on a file
   *  the seam's own typecheck called clean. */
  children: ReactNode;
}) {
  return (
    <p
      className={
        tone === "warn"
          ? "text-sm text-text-warning"
          : "text-sm text-text-secondary"
      }
      data-testid={testId}
      role={alert ? "alert" : undefined}
    >
      {children}
    </p>
  );
}

export default function ModelsPanel(): JSX.Element {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // One observer; the poll turns itself on while a download is running (see useModelCatalog).
  const catalog = useModelCatalog();
  const rows = catalog.data ?? [];
  const server = useModelServerStatus();

  async function act(work: () => Promise<unknown>, whenItFails: string) {
    setProblem(null);
    try {
      await work();
      await queryClient.invalidateQueries({ queryKey: ["modelCatalog"] });
      await queryClient.invalidateQueries({ queryKey: ["modelServer"] });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : whenItFails);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-text-secondary">
        Free, openly licensed models you can download and run on this machine. No account, no
        key, and nothing you type goes anywhere — once a model is downloaded it works with the
        network unplugged. Downloads start only when you press Download.
      </p>

      {problem !== null && (
        <Note tone="warn" alert>
          {problem}
        </Note>
      )}
      {server.data !== undefined && server.data.runner === null && (
        <Note tone="warn" testId="runner-missing">
          {server.data.runner_problem}
        </Note>
      )}
      {catalog.isLoading && (
        <p
          className="flex items-center gap-2 text-sm text-text-secondary"
          data-testid="models-loading"
        >
          <Spinner className="size-4" />
          Reading the model catalogue…
        </p>
      )}
      {catalog.isError && (
        <Note tone="warn" alert testId="models-unavailable">
          The model catalogue could not be read: {catalog.error.message}. Downloaded models are
          unaffected — this is the list, not the files.
        </Note>
      )}
      {rows.length === 0 && !catalog.isLoading && !catalog.isError && (
        <Note testId="models-empty">
          No models are listed. This build shipped without a catalogue.
        </Note>
      )}

      {rows.map((row: ModelCatalogRow) => {
        const state = row.download?.state ?? null;
        const isDownloading = state === "running";
        const done = row.download?.doneBytes ?? 0;
        const total = row.download?.totalBytes ?? row.sizeBytes ?? 0;
        const percent = total > 0 ? Math.round((done / total) * 100) : 0;
        const paused = !isDownloading && (row.partialBytes ?? 0) > 0;
        const stray = row.strayBytes ?? 0;
        // Anything of this row's on disk — an install, a paused partial, or a file that is
        // not the model at all. Remove used to render only for `installed`, so a partial was
        // gigabytes with no way to free them and a stray file had no way out either.
        const anythingOnDisk = row.installed || paused || stray > 0;
        const servingThisRow =
          server.data?.running === true &&
          row.installedPath !== null &&
          server.data.model_path === row.installedPath;
        return (
          <div
            key={row.id}
            className="flex flex-col gap-2 rounded-xl border border-border-light p-3"
            data-testid={`model-${row.id}`}
          >
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-medium text-text-primary">{row.label}</span>
              <span className="text-xs text-text-tertiary">
                {gb(row.sizeBytes)} · {row.license}
              </span>
              {servingThisRow && (
                <span className="rounded-full bg-surface-tertiary px-2 py-0.5 text-xs text-text-secondary">
                  serving
                </span>
              )}
            </div>
            <p className="text-sm text-text-secondary">
              {row.goodAt} {row.ramNote}
            </p>

            {row.installed && (
              <Note testId={`installed-${row.id}`}>
                Downloaded. {gb(row.freeBytes)} free on this disk.
              </Note>
            )}
            {!row.installed && !row.fitsOnDisk && (
              <Note tone="warn" testId={`too-big-${row.id}`}>
                This needs {gb(row.sizeBytes)} and only {gb(row.freeBytes)} is free — free some
                space first, rather than starting a download that cannot finish.
              </Note>
            )}
            {paused && (
              <Note testId={`paused-${row.id}`}>
                Paused with {gb(row.partialBytes)} of {gb(row.sizeBytes)} already downloaded.
                Download again to continue from there, or remove it to get the space back.
              </Note>
            )}
            {stray > 0 && (
              <Note tone="warn" alert testId={`stray-${row.id}`}>
                There is a file where this model goes that is not this model ({gb(stray)}, and
                the catalogue records {gb(row.sizeBytes)}). It may be a copy from another tool,
                or a model that was re-uploaded upstream. Remove it and download again — Tempest
                will not serve a file it cannot identify.
              </Note>
            )}
            {isDownloading && (
              <div className="flex flex-col gap-1.5">
                <Progress value={percent} aria-label={`Downloading ${row.label}`} />
                <p className="text-sm text-text-secondary" data-testid={`progress-${row.id}`}>
                  Downloading… {percent}% ({gb(done)} of {gb(total)})
                </p>
              </div>
            )}
            {state === "failed" && row.download !== null && (
              <Note tone="warn" alert testId={`failed-${row.id}`}>
                {row.download.error}
              </Note>
            )}
            {state === "cancelled" && row.download !== null && (
              <Note testId={`cancelled-${row.id}`}>{row.download.error}</Note>
            )}

            <div className="flex flex-wrap gap-2">
              {!row.installed && !isDownloading && stray === 0 && (
                <Button
                  size="sm"
                  variant="subtle"
                  disabled={busy !== null || !row.fitsOnDisk}
                  data-testid={`download-${row.id}`}
                  onClick={() => {
                    setBusy(row.id);
                    void act(
                      () => startModelDownload(row.id),
                      "the download could not be started",
                    );
                  }}
                >
                  {paused ? "Resume download" : "Download"}
                </Button>
              )}
              {isDownloading && (
                <Button
                  size="sm"
                  variant="subtle"
                  data-testid={`stop-${row.id}`}
                  onClick={() => void act(() => cancelModelDownload(row.id), "could not stop")}
                >
                  Stop
                </Button>
              )}
              {row.installed && (
                <Button
                  size="sm"
                  disabled={busy !== null || server.data?.runner == null || servingThisRow}
                  data-testid={`serve-${row.id}`}
                  onClick={() => {
                    setBusy(row.id);
                    void act(
                      () => startModelServer(row.installedPath ?? ""),
                      "the model server could not be started",
                    );
                  }}
                >
                  {servingThisRow ? "Serving" : "Serve"}
                </Button>
              )}
              {anythingOnDisk && !isDownloading && (
                <Button
                  size="sm"
                  variant="subtle"
                  disabled={busy !== null}
                  data-testid={`remove-${row.id}`}
                  onClick={() => {
                    setBusy(row.id);
                    // Stop the server FIRST when it is serving this very file. Deleting the
                    // file out from under a live `llama-server` reported success and freed
                    // nothing — on POSIX the inode survives until the last fd closes — while
                    // the panel went on claiming to serve a path that no longer existed.
                    void act(async () => {
                      if (servingThisRow) await stopModelServer();
                      return removeModel(row.id);
                    }, "could not remove it");
                  }}
                >
                  Remove
                </Button>
              )}
            </div>
          </div>
        );
      })}

      {server.data?.running === true && (
        <div className="flex flex-col gap-2 rounded-xl border border-border-light bg-surface-secondary p-3">
          <p className="text-sm text-text-secondary" data-testid="server-running">
            Serving on 127.0.0.1 — pick <span className="font-medium">llama.cpp server
            (local)</span> in the model list to chat with it. It is reachable only from this
            machine.
          </p>
          <div>
            <Button
              size="sm"
              variant="subtle"
              data-testid="stop-server"
              onClick={() => void act(stopModelServer, "could not stop")}
            >
              Stop serving
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
