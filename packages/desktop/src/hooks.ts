/** Boundary B consumption (CLAUDE.md §9b): TanStack Query wrappers over the GENERATED typed
 * commands — the only sanctioned path to the sidecar. Handwritten `invoke()` is banned and
 * `make verify-desktop` greps for it. */
import { useQuery } from "@tanstack/react-query";

import {
  commands,
  type AiKeyStatus,
  type LocalProveRequest,
  type RunCreated,
  type SidecarFailure,
  type Verdict,
} from "./generated/bindings";

type BindingResult<T> = { status: "ok"; data: T } | { status: "error"; error: SidecarFailure };

export class SidecarError extends Error {
  readonly code: number;

  constructor(failure: SidecarFailure) {
    super(failure.message);
    this.name = "SidecarError";
    this.code = failure.code;
  }
}

async function unwrap<T>(command: string, pending: Promise<BindingResult<T>>): Promise<T> {
  const result = await pending;
  if (result.status === "error") throw new SidecarError(result.error);
  if (import.meta.env.DEV) {
    // Deep validation at Boundary B (§9b): dev builds check every result against the
    // generated domain schema — statically dead (and tree-shaken) in production.
    const { assertValidCommandResult } = await import("./devValidate");
    assertValidCommandResult(command, result.data);
  }
  return result.data;
}

export function useGetHealth() {
  return useQuery({
    queryKey: ["getHealth"],
    queryFn: () => unwrap("getHealth", commands.getHealth()),
    // The sidecar may still be starting (or restarting after a crash) — keep probing.
    refetchInterval: (query) => (query.state.status === "error" ? 2000 : false),
  });
}

export function useListRuns(
  filters: { verdict?: Verdict; cursor?: string; limit?: number } = {},
) {
  return useQuery({
    queryKey: ["listRuns", filters],
    queryFn: () =>
      unwrap(
        "listRuns",
        commands.listRuns(filters.verdict ?? null, filters.cursor ?? null, filters.limit ?? null),
      ),
  });
}

export function useGetRun(runId: number) {
  return useQuery({
    queryKey: ["getRun", runId],
    queryFn: () => unwrap("getRun", commands.getRun(runId)),
  });
}

export function useListRunEvents(runId: number) {
  return useQuery({
    queryKey: ["listRunEvents", runId],
    queryFn: () => unwrap("listRunEvents", commands.listRunEvents(runId)),
  });
}

export function useGetTarget(targetId: number) {
  return useQuery({
    queryKey: ["getTarget", targetId],
    queryFn: () => unwrap("getTarget", commands.getTarget(targetId)),
  });
}

export function useGetDivergence(divergenceId: number) {
  return useQuery({
    queryKey: ["getDivergence", divergenceId],
    queryFn: () => unwrap("getDivergence", commands.getDivergence(divergenceId)),
  });
}

export function useGetDivergenceRepro(divergenceId: number) {
  return useQuery({
    queryKey: ["getDivergenceRepro", divergenceId],
    queryFn: async () => (await unwrap("getDivergenceRepro", commands.getDivergenceRepro(divergenceId))).text,
  });
}

export function startLocalProve(request: LocalProveRequest): Promise<RunCreated> {
  return unwrap("startLocalProve", commands.startLocalProve(request));
}

export function cancelRun(runId: number) {
  return unwrap("cancelRun", commands.cancelRun(runId));
}

export function useSearchDivergences(q: string) {
  return useQuery({
    queryKey: ["searchDivergences", q],
    queryFn: () => unwrap("searchDivergences", commands.searchDivergences(q, null)),
    enabled: q.trim().length > 0,
  });
}

export function useAiKeyStatus() {
  return useQuery({
    queryKey: ["aiKeyStatus"],
    queryFn: () => unwrap("aiKeyStatus", commands.aiKeyStatus()),
  });
}

export function setAiKey(key: string): Promise<AiKeyStatus> {
  return unwrap("setAiKey", commands.setAiKey(key));
}

export function clearAiKey(): Promise<AiKeyStatus> {
  return unwrap("clearAiKey", commands.clearAiKey());
}

export function useListLogRecords(limit?: number, level?: string | null) {
  return useQuery({
    queryKey: ["listLogRecords", limit ?? null, level ?? null],
    queryFn: () => unwrap("listLogRecords", commands.listLogRecords(limit ?? null, level ?? null)),
    // Logs are a live surface: keep polling so the view follows the engine.
    refetchInterval: 3000,
  });
}
