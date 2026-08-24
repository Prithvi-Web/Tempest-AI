/**
 * The repository a tool-bearing agent works in (ADR-0083).
 *
 * The owner's mandate: *"the tempest that i integrated is more of like a tool that the AI will
 * use to accomplish important tasks."* That runtime exists and is proven — a tool-bearing agent
 * dispatches through `run_task`, the tools act on a shadow worktree, and `prove` runs a real
 * differential (ADR-0075, e2e spec 24). What was missing was the one field that makes any of it
 * reachable: `tempest_repo` was settable over the API and had **no UI at all**, so an agent built
 * in the app could not be pointed at a checkout, and every tool-bearing turn refused to start.
 *
 * A text field rather than a native folder picker, deliberately: the proof surface's own
 * `ProveView` takes a repository the same way, so this matches what the product already does,
 * and a picker would mean a new Tauri command and a new boundary-B shape for a string the user
 * can paste. That is worth doing; it is not worth doing in the commit that unblocks the feature.
 *
 * The refusal it prevents is the L15.3 one: an agent with tools and no repository fails at the
 * moment the user sends their first message, which is the worst possible time to learn it. It
 * is said here instead, while they are still building.
 */

import { Controller, useFormContext, useWatch } from "react-hook-form";

/** Upstream's own capability toggles are tools too, and they do not need a checkout. */
const CAPABILITY_TOGGLES = new Set([
  "execute_code",
  "file_search",
  "web_search",
  "memory",
]);

interface RepositoryForm {
  tempest_repo?: string | null;
  tools?: string[];
}

export default function RepositoryField(): JSX.Element {
  const { control } = useFormContext<RepositoryForm>();
  const tools = useWatch({ control, name: "tools" });
  const needsRepo = (tools ?? []).some((tool) => !CAPABILITY_TOGGLES.has(tool));

  return (
    <Controller
      name="tempest_repo"
      control={control}
      render={({ field }) => {
        const value = field.value ?? "";
        const missing = needsRepo && value.trim() === "";
        return (
          <div className="mb-3 flex flex-col" data-testid="tempest-repo-field">
            <label
              htmlFor="tempest_repo"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-text-secondary"
            >
              Repository
            </label>
            <input
              id="tempest_repo"
              type="text"
              spellCheck={false}
              autoComplete="off"
              data-testid="tempest-repo-input"
              placeholder="/Users/you/projects/my-repo"
              className="w-full rounded-lg border border-border-light bg-surface-secondary px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-border-xheavy"
              value={value}
              onChange={(event) => field.onChange(event.target.value)}
              onBlur={field.onBlur}
              ref={field.ref}
            />
            <p className="mt-1 text-xs text-text-secondary">
              The checkout this agent&apos;s tools work in. Edits land in a shadow worktree cut
              from it — never in your working tree — and{" "}
              <span className="font-medium text-text-primary">Prove</span> runs the change
              against the original to see whether behaviour actually differs.
            </p>
            {missing && (
              <p
                className="mt-1 text-xs text-text-warning"
                role="alert"
                data-testid="tempest-repo-missing"
              >
                This agent has tools, so it needs a repository — without one it will refuse the
                first message rather than guess which code you meant.
              </p>
            )}
          </div>
        );
      }}
    />
  );
}
