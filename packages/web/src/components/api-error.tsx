import { errorCodeNote, isErrorEnvelope } from "@/lib/verdict";

/**
 * Renders a failed request honestly: the machine-readable code, the server's message, and any
 * details verbatim. A network failure is named as such — never dressed up as an empty state.
 */
export function ApiErrorPanel({ error, context }: { error: unknown; context: string }) {
  if (isErrorEnvelope(error)) {
    const { code, message, details } = error.error;
    return (
      <div role="alert" className="border border-error bg-panel-raised p-4 text-sm">
        <p className="text-xs uppercase tracking-widest text-error">
          {context} — {code}
        </p>
        <p className="mt-2 text-ink">{message}</p>
        <p className="mt-1 text-xs text-ink-dim">{errorCodeNote(code)}</p>
        {details != null && (
          <pre className="mt-3 overflow-x-auto border border-panel-line bg-panel p-2 text-xs text-ink-dim">
            {JSON.stringify(details, null, 2)}
          </pre>
        )}
      </div>
    );
  }
  return (
    <div role="alert" className="border border-error bg-panel-raised p-4 text-sm">
      <p className="text-xs uppercase tracking-widest text-error">{context} — request failed</p>
      <p className="mt-2 text-ink">
        {error instanceof Error ? error.message : String(error)}
      </p>
      <p className="mt-1 text-xs text-ink-dim">
        if the API is down, start it: <code className="text-ink">docker compose up</code> (see
        docker/) or <code className="text-ink">uvicorn tempest_api.app:create_app --factory</code>
      </p>
    </div>
  );
}
