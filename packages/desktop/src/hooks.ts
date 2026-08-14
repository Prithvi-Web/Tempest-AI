/** Boundary B consumption (CLAUDE.md §9b): TanStack Query wrappers over the GENERATED typed
 * commands — the only sanctioned path to the sidecar. Handwritten `invoke()` is banned and
 * `make verify-desktop` greps for it. */
import { useQuery } from "@tanstack/react-query";

import {
  commands,
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

async function unwrap<T>(pending: Promise<BindingResult<T>>): Promise<T> {
  const result = await pending;
  if (result.status === "error") throw new SidecarError(result.error);
  return result.data;
}

export function useGetHealth() {
  return useQuery({
    queryKey: ["getHealth"],
    queryFn: () => unwrap(commands.getHealth()),
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
        commands.listRuns(filters.verdict ?? null, filters.cursor ?? null, filters.limit ?? null),
      ),
  });
}

export function useGetRun(runId: number) {
  return useQuery({
    queryKey: ["getRun", runId],
    queryFn: () => unwrap(commands.getRun(runId)),
  });
}

export function useListRunEvents(runId: number) {
  return useQuery({
    queryKey: ["listRunEvents", runId],
    queryFn: () => unwrap(commands.listRunEvents(runId)),
  });
}

export function useGetTarget(targetId: number) {
  return useQuery({
    queryKey: ["getTarget", targetId],
    queryFn: () => unwrap(commands.getTarget(targetId)),
  });
}

export function useGetDivergence(divergenceId: number) {
  return useQuery({
    queryKey: ["getDivergence", divergenceId],
    queryFn: () => unwrap(commands.getDivergence(divergenceId)),
  });
}

export function useGetDivergenceRepro(divergenceId: number) {
  return useQuery({
    queryKey: ["getDivergenceRepro", divergenceId],
    queryFn: async () => (await unwrap(commands.getDivergenceRepro(divergenceId))).text,
  });
}

export function startLocalProve(request: LocalProveRequest): Promise<RunCreated> {
  return unwrap(commands.startLocalProve(request));
}
