/** Boundary B consumption (CLAUDE.md §9b): TanStack Query wrappers over the GENERATED typed
 * commands — the only sanctioned path to the sidecar. Handwritten `invoke()` is banned and
 * `make verify-desktop` greps for it.
 *
 * Absorbed into the platform client (C3). Two things differ from the desktop copy and nothing
 * else does: the bindings are imported across the package boundary rather than copied (one
 * generated boundary, one file — L12), and the query library here is TanStack Query v4, so the
 * two function-form `refetchInterval`s take `(data, query)` and the composer keeps its previous
 * answer with `keepPreviousData` instead of v5's `placeholderData`. */
import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

import {
  commands,
  type AiKeyStatus,
  type AiKeyTestResult_Serialize,
  type ComposeView,
  type DiagnosticBundle,
  type LocalProveRequest,
  type ModelCatalogRow,
  type ModelDownloadState,
  type ModelRemoved,
  type ModelServerStatus,
  type RunCreated,
  type EditorRunners,
  type EditorRunnersOut,
  type SettingsIn_Deserialize,
  type SettingsOut_Serialize,
  type ProjectFile,
  type ProjectFileRefusal,
  type SidecarFailure,
  type SyncReport,
  type Verdict,
  type WatchStartRequest,
  type WatchStatus,
} from "../../../../desktop/src/generated/bindings";

type BindingResult<T> = { status: "ok"; data: T } | { status: "error"; error: SidecarFailure };

export class SidecarError extends Error {
  readonly code: number;

  constructor(failure: SidecarFailure) {
    super(failure.message);
    this.name = "SidecarError";
    this.code = failure.code;
  }
}

/** The desktop copy also ran every dev-build result through the generated domain schema (ajv).
 * That validator is not in the platform client's dependency tree, so this copy shapes the error
 * and nothing more; the schema net still runs over the same commands in the desktop build. */
async function unwrap<T>(pending: Promise<BindingResult<T>>): Promise<T> {
  const result = await pending;
  if (result.status === "error") throw new SidecarError(result.error);
  return result.data;
}

/** Query v4 types TError as `unknown` (v5 said `Error`, which is what the desktop copy
 * compiled against). Everything `unwrap` throws is a SidecarError, so say it once here and
 * every consumer reads `.message` on a typed error instead of narrowing `unknown`. */
function useSidecarQuery<TData>(options: UseQueryOptions<TData, SidecarError>) {
  return useQuery<TData, SidecarError>(options);
}

export function useGetHealth() {
  return useSidecarQuery({
    queryKey: ["getHealth"],
    queryFn: () => unwrap(commands.getHealth()),
    // The sidecar may still be starting (or restarting after a crash) — keep probing.
    refetchInterval: (_data, query) => (query.state.status === "error" ? 2000 : false),
  });
}

export function useListRuns(
  filters: { verdict?: Verdict; cursor?: string; limit?: number } = {},
) {
  return useSidecarQuery({
    queryKey: ["listRuns", filters],
    queryFn: () =>
      unwrap(
        commands.listRuns(filters.verdict ?? null, filters.cursor ?? null, filters.limit ?? null),
      ),
  });
}

/** F12's composer (ADR-0061): the change as rows, each carrying what the engine found it does.
 *
 * Keyed by the SELECTION, so toggling a hunk is a key change and TanStack refetches — which is
 * the whole interaction. `accepted === null` is the state the view opens in (every hunk); an
 * empty array is the user having rejected everything, and the two are different questions.
 *
 * `enabled` gates on a repo path because the first render has none, and a composer that fired a
 * proof against an empty path would spend seconds discovering that.
 */
export function useComposeChange(args: {
  repoPath: string;
  base: string;
  head: string;
  accepted: string[] | null;
  maxInputs?: number;
}) {
  const request = {
    repo_path: args.repoPath,
    base: args.base,
    head: args.head,
    accepted: args.accepted,
    max_inputs: args.maxInputs ?? 50,
  };
  return useQuery<ComposeView>({
    queryKey: ["composeChange", request],
    queryFn: () => unwrap(commands.composeChange(request)),
    enabled: Boolean(args.repoPath && args.base && args.head),
    // A proof is expensive and deterministic for a given selection: never re-run it because a
    // window regained focus. The only thing that should refetch is the user changing the
    // selection, and that changes the key.
    refetchOnWindowFocus: false,
    staleTime: Infinity,
    // Toggling a hunk changes the query KEY, and a new key has no data — so without this the
    // whole list unmounts and the user stares at a blank panel until the re-proof lands. Keeping
    // the previous answer on screen while the next one is computed is the difference between a
    // composer and a form that reloads. `isFetching` is what tells them it is still moving.
    keepPreviousData: true,
  });
}

export function useGetRun(runId: number) {
  return useSidecarQuery({
    queryKey: ["getRun", runId],
    queryFn: () => unwrap(commands.getRun(runId)),
    // SLOW fallback only (§1.2): live freshness is pushed by the host's RunProgressEvent
    // once per second; this keeps hosts without a watcher (the browser E2E rig) and any
    // missed event converging. The function form reads query state, not render state.
    refetchInterval: (data) => (data?.status === "PENDING" ? 5000 : false),
  });
}

export function useListRunEvents(runId: number) {
  return useSidecarQuery({
    queryKey: ["listRunEvents", runId],
    queryFn: () => unwrap(commands.listRunEvents(runId)),
  });
}

export function useGetTarget(targetId: number) {
  return useSidecarQuery({
    queryKey: ["getTarget", targetId],
    queryFn: () => unwrap(commands.getTarget(targetId)),
  });
}

export function useGetDivergence(divergenceId: number) {
  return useSidecarQuery({
    queryKey: ["getDivergence", divergenceId],
    queryFn: () => unwrap(commands.getDivergence(divergenceId)),
  });
}

export function useGetDivergenceRepro(divergenceId: number) {
  return useSidecarQuery({
    queryKey: ["getDivergenceRepro", divergenceId],
    queryFn: async () => (await unwrap(commands.getDivergenceRepro(divergenceId))).text,
  });
}

export function startLocalProve(request: LocalProveRequest): Promise<RunCreated> {
  return unwrap(commands.startLocalProve(request));
}

export function cancelRun(runId: number) {
  return unwrap(commands.cancelRun(runId));
}

export function useSearchDivergences(q: string) {
  return useSidecarQuery({
    queryKey: ["searchDivergences", q],
    queryFn: () => unwrap(commands.searchDivergences(q, null)),
    enabled: q.trim().length > 0,
  });
}

export function useAiKeyStatus() {
  return useSidecarQuery({
    queryKey: ["aiKeyStatus"],
    queryFn: () => unwrap(commands.aiKeyStatus()),
  });
}

export function setAiKey(key: string): Promise<AiKeyStatus> {
  return unwrap(commands.setAiKey(key));
}

export function clearAiKey(): Promise<AiKeyStatus> {
  return unwrap(commands.clearAiKey());
}

export function useListLogRecords(limit?: number, level?: string | null) {
  return useSidecarQuery({
    queryKey: ["listLogRecords", limit ?? null, level ?? null],
    queryFn: () => unwrap(commands.listLogRecords(limit ?? null, level ?? null)),
    // Logs are a live surface: keep polling so the view follows the engine.
    refetchInterval: 3000,
  });
}

export function useSettings() {
  return useSidecarQuery({
    queryKey: ["getSettings"],
    queryFn: () => unwrap(commands.getSettings()),
  });
}

export function updateSettings(next: SettingsIn_Deserialize): Promise<SettingsOut_Serialize> {
  return unwrap(commands.updateSettings(next));
}

export function testAiKey(): Promise<AiKeyTestResult_Serialize> {
  return unwrap(commands.testAiKey());
}

export function syncPush(serverUrl: string): Promise<SyncReport> {
  return unwrap(commands.syncPush(serverUrl));
}

export function exportDiagnostics(): Promise<DiagnosticBundle> {
  return unwrap(commands.exportDiagnostics());
}

/** Host-side reveal: `null` opens the data folder, a bare filename reveals that archive.
 * The host rejects anything that is not a plain leaf name (commands.rs `safe_leaf`). */
export function revealInDataDir(diagnostic: string | null): Promise<null> {
  return unwrap(commands.revealInDataDir(diagnostic));
}

/** Watch status is a live surface with no push channel of its own: the host learns of a new
 * commit only by asking the engine. A 2s poll while the view is mounted is the honest cost —
 * the RUN it starts still rides the pushed RunProgressEvent like any other run (§1.2). */
export function useWatchStatus(enabled: boolean) {
  return useSidecarQuery({
    queryKey: ["getWatchStatus"],
    queryFn: () => unwrap(commands.getWatchStatus()),
    refetchInterval: 2000,
    enabled,
  });
}

export function startWatch(request: WatchStartRequest): Promise<WatchStatus> {
  return unwrap(commands.startWatch(request));
}

export function stopWatch(): Promise<WatchStatus> {
  return unwrap(commands.stopWatch());
}

export function startDemoProve(): Promise<RunCreated> {
  return unwrap(commands.startDemoProve());
}

/** The editor's two runners (Phase 20.6). Host-local, like `readProjectFile` — there is no
 * engine behind it, so it does not go through the domain-schema net; its shape is a Tauri-local
 * type generated from `runners.rs` and checked by tsc. */
export function useEditorRunners() {
  return useQuery<EditorRunnersOut, SidecarError>({
    queryKey: ["editorRunners"],
    queryFn: async () => {
      const result = await commands.getEditorRunners();
      if (result.status === "error") throw new SidecarError(result.error);
      return result.data;
    },
  });
}

export async function updateEditorRunners(runners: EditorRunners): Promise<EditorRunnersOut> {
  const result = await commands.updateEditorRunners(runners);
  if (result.status === "error") throw new SidecarError(result.error);
  return result.data;
}

/** A refusal from `pathguard`, carrying the branchable reason as well as the sentence. */
export class ProjectFileError extends Error {
  readonly refusal: ProjectFileRefusal["refusal"];

  constructor(refusal: ProjectFileRefusal) {
    super(refusal.message);
    this.name = "ProjectFileError";
    this.refusal = refusal.refusal;
  }
}

/**
 * Open one file from one project (Phase 20.1). Not a sidecar call — see `read_project_file`.
 *
 * `retry: false` because every failure this command produces is a DECISION (absolute path,
 * credential, not a project), and retrying a decision just asks the same question again.
 */
export function useProjectFile(repoPath: string, path: string) {
  return useQuery<ProjectFile, ProjectFileError>({
    queryKey: ["projectFile", repoPath, path],
    retry: false,
    queryFn: async () => {
      const result = await commands.readProjectFile(repoPath, path, null);
      if (result.status === "error") throw new ProjectFileError(result.error);
      return result.data;
    },
  });
}

// ── Local models (ADR-0080) ─────────────────────────────────────────────────────────────────

/** The catalogue, with `installed`, `freeBytes` and `fitsOnDisk` already resolved by the
 * engine — the size and the room for it in one reply, so the panel never has to make a second
 * call to answer "can I?" (L21). */
export function useModelCatalog(pollMs: number | false) {
  return useQuery<ModelCatalogRow[], SidecarError>({
    queryKey: ["modelCatalog"],
    queryFn: async () => {
      const result = await commands.listModelCatalog();
      if (result.status === "error") throw new SidecarError(result.error);
      return result.data;
    },
    // Downloads report by POLLING, not by a second stream: the app already has exactly one
    // push mechanism for long work, and a progress bar needs less than that. `false` while
    // nothing is downloading, so an idle panel is not a timer.
    refetchInterval: pollMs,
  });
}

export function useModelServerStatus(configuredRunner: string | null) {
  return useQuery<ModelServerStatus, SidecarError>({
    queryKey: ["modelServer", configuredRunner],
    queryFn: async () => {
      const result = await commands.modelServerStatus(configuredRunner);
      if (result.status === "error") throw new SidecarError(result.error);
      return result.data;
    },
  });
}

export async function startModelDownload(modelId: string): Promise<ModelDownloadState> {
  const result = await commands.startModelDownload(modelId);
  if (result.status === "error") throw new SidecarError(result.error);
  return result.data;
}

export async function cancelModelDownload(modelId: string): Promise<ModelDownloadState> {
  const result = await commands.cancelModelDownload(modelId);
  if (result.status === "error") throw new SidecarError(result.error);
  return result.data;
}

export async function removeModel(modelId: string): Promise<ModelRemoved> {
  const result = await commands.removeModel(modelId);
  if (result.status === "error") throw new SidecarError(result.error);
  return result.data;
}

export async function startModelServer(
  modelPath: string,
  configuredRunner: string | null,
): Promise<ModelServerStatus> {
  const result = await commands.startModelServer(modelPath, configuredRunner);
  if (result.status === "error") throw new SidecarError(result.error);
  return result.data;
}

export async function stopModelServer(): Promise<ModelServerStatus> {
  const result = await commands.stopModelServer();
  if (result.status === "error") throw new SidecarError(result.error);
  return result.data;
}
