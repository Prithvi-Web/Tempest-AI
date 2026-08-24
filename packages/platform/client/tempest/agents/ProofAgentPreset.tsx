/**
 * One click to an agent that knows how to use Tempest (ADR-0083).
 *
 * The runtime has been able to do this for a while: a tool-bearing agent dispatches through
 * `run_task`, its tools act on a shadow worktree, and `prove` runs a real differential. What a
 * new user actually had was **an empty agent list** and a tool library with seven entries and
 * no opinion about what to do with them. The owner's mandate — *"the tempest that i integrated
 * is more of like a tool that the AI will use to accomplish important tasks"* — needs the
 * capability to be reachable, not merely present.
 *
 * **A preset, not a seeded agent.** The alternative was writing a built-in agent into the
 * user's store on first run, and it is worse in a specific way: the user can edit it and
 * delete it, so the store needs a marker to stop it coming back, and a row that reappears
 * after you deleted it is the kind of thing that makes people distrust an app. A preset writes
 * nothing until the user presses Create, and what it writes is theirs.
 *
 * It deliberately fills only what a person cannot be expected to type: the tools, and the
 * instructions that make the model use them well. The model and the repository stay empty
 * because those are the two facts only the user knows.
 */

import { useFormContext, useWatch } from "react-hook-form";

/** The tools that make an assistant able to work in a repository and prove what it changed. */
const PROOF_TOOLS = ["read_file", "list_dir", "search_text", "write_file", "run_command", "prove"];

/**
 * What the model is told. This is the part that cannot be guessed, and the part that decides
 * whether `prove` gets used at the right moments or ignored.
 *
 * It is written to hold L2 and L31 from the model's side: the four verdicts are the ENGINE's
 * outputs, and an assistant that paraphrases one into "looks correct" has destroyed the only
 * thing this product sells. Saying so in the system prompt is not a substitute for the
 * structural guarantee (`ProvenChange` still has no constructor without a bundle id) — it is
 * what stops the model wasting a turn trying.
 */
const INSTRUCTIONS = [
  "You work in the repository configured for this agent. Your tools act on a shadow worktree",
  "cut from it — never on the user's working tree — so you can change code freely and nothing",
  "is lost if the change turns out to be wrong.",
  "",
  "Read before you write, and prefer the smallest change that answers the request.",
  "",
  "When you change code, prove it. The `prove` tool executes the changed code and the original",
  "side by side on generated inputs and reports where their observable behaviour differs, with",
  "a minimized reproduction. Run it after any edit that could change behaviour, and report what",
  "it found rather than what you meant to do.",
  "",
  "The verdicts are the engine's, not yours: DIVERGENT, EQUIVALENT_UNDER_BUDGET, UNPROVEN and",
  "ERROR. Never upgrade one into a claim of your own — 'I checked it' is not a verdict, and",
  "EQUIVALENT_UNDER_BUDGET means the inputs that ran agreed, not that the change is correct. If",
  "something could not be exercised, say UNPROVEN and say what blocked it.",
].join("\n");

interface PresetForm {
  name?: string | null;
  instructions?: string | null;
  tools?: string[];
}

export default function ProofAgentPreset(): JSX.Element | null {
  const { control, setValue } = useFormContext<PresetForm>();
  const tools = useWatch({ control, name: "tools" });
  const name = useWatch({ control, name: "name" });

  // Offered on a blank slate only. Once there are tools or a name, the person has made
  // decisions, and a button that would overwrite them is a trap rather than a shortcut.
  if ((tools ?? []).length > 0 || (name ?? "").trim() !== "") {
    return null;
  }

  return (
    <div className="mb-3 rounded-xl border border-border-light p-3" data-testid="proof-agent-preset">
      <p className="text-sm font-medium text-text-primary">Start from the proof agent</p>
      <p className="mt-1 text-xs text-text-secondary">
        Fills in the tools for working in a repository and the instructions for using{" "}
        <span className="font-medium text-text-primary">Prove</span> — which runs your changed
        code against the original and reports where they actually behave differently. You still
        choose the model and the repository.
      </p>
      <button
        type="button"
        data-testid="use-proof-agent-preset"
        className="mt-2 rounded-lg border border-border-light bg-transparent px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-border-xheavy"
        onClick={() => {
          setValue("name", "Proof agent", { shouldDirty: true });
          setValue("instructions", INSTRUCTIONS, { shouldDirty: true });
          setValue("tools", [...PROOF_TOOLS], { shouldDirty: true });
        }}
      >
        Use this preset
      </button>
    </div>
  );
}
