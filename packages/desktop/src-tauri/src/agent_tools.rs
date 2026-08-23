//! **Boundary D — the Agent Tool Protocol** (CLAUDE.md §9c, ADR-0035).
//!
//! v1 had three generated boundaries (Python↔Rust↔TS). v2 adds a fourth shape that crosses all
//! of them *and* crosses into a model: the schema of every tool the agent may call. Hand-writing
//! that schema in three places plus a prompt is exactly the drift L12 forbids — and the failure
//! mode is worse than a type error, because a model handed a stale tool schema produces
//! plausible calls that silently do the wrong thing.
//!
//! **Root of truth is Rust, not Python**, unlike boundaries A/C. The orchestrator owns tool
//! dispatch, budget enforcement, and capability checks; the enforcement point and the schema
//! must not be able to disagree. Domain *values* inside tool arguments still come from the
//! Pydantic-rooted `generated::domain` types — referenced, never redefined.
//!
//! Everything downstream is generated from [`manifest`]:
//!
//! ```text
//!                     ┌─ packages/shared-schema/agent-tools.json   (canonical, drift-gated)
//!   manifest()  ──────┼─ packages/desktop/src/generated/agentTools.ts  (webview, typed)
//!                     └─ anthropic_tool_defs() / openai_tool_defs()    (model-facing)
//! ```
//!
//! ## What this module is NOT, stated plainly
//!
//! This is the **contract**, not the runtime. There is no `execute` here and no dispatch: the
//! agent orchestrator arrives in Phase 21 (`docs/PLAN-V2.md`), and it will implement dispatch
//! against these exact declarations. Shipping the schema first is deliberate — the drift gate
//! then guards every later change, instead of the tool surface growing unguarded and being
//! retrofitted.
//!
//! ## The policy metadata is the threat model, in types
//!
//! Each tool declares its own [`ToolPolicy`]. Two properties are enforced by the *type system*
//! rather than by reviewer vigilance:
//!
//! * [`WriteScope`] has **no variant for the user's working tree**. L19 says agent writes are
//!   staged in a shadow worktree until accepted; a tool therefore cannot even *express* a write
//!   to the user's checkout. An unrepresentable state cannot be reached by a bug.
//! * A tool that touches the network or is destructive cannot be [`Approval::Auto`] — checked by
//!   [`ToolSpec::invariants_hold`] and pinned by test, because §8 requires those to be
//!   approval-gated regardless of policy, always.

use serde::{Deserialize, Serialize};

/// How a tool call reaches execution: the approval tier the orchestrator must honour.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "snake_case")]
pub enum Approval {
    /// Runs without asking. Only ever valid for read-only, in-sandbox, non-destructive tools.
    Auto,
    /// Asks once, then remembers the answer for this project (F14's approval policy).
    PromptOncePerProject,
    /// Asks every single time and can never be remembered — `rm -rf`, force push, history
    /// rewrite, migration execution (§8 "regardless of policy, always").
    AlwaysPrompt,
}

/// Where a tool may write. **There is deliberately no `UserTree` variant** (L19).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "snake_case")]
pub enum WriteScope {
    /// Reads only; produces no filesystem mutation.
    None,
    /// Writes land in `.tempest/agent/worktrees/<task-id>/`, never the user's checkout.
    /// Acceptance into the working tree is a separate, journalled, user-driven step (L20).
    ShadowWorktree,
}

/// The capability envelope of one tool, enforced in Rust — outside the model (§8 T1).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
pub struct ToolPolicy {
    pub approval: Approval,
    /// Outbound network. Requires approval and is allowlisted per project (§8 T2).
    pub touches_network: bool,
    /// Can destroy user data or rewrite history. Forces [`Approval::AlwaysPrompt`].
    pub destructive: bool,
    pub writes: WriteScope,
}

impl ToolPolicy {
    /// A read-only, in-sandbox, non-destructive tool — the only shape allowed to run unattended.
    const fn read_only() -> Self {
        Self {
            approval: Approval::Auto,
            touches_network: false,
            destructive: false,
            writes: WriteScope::None,
        }
    }
}

/// One tool's complete declaration: identity, prose for the model, capability envelope, and the
/// JSON Schema of its arguments.
#[derive(Debug, Clone, Serialize, Deserialize, specta::Type)]
pub struct ToolSpec {
    pub name: String,
    /// Model-facing prose. This is the ONLY field a model reads as instruction; it never
    /// carries a verdict, a confidence, or a risk value (L17).
    pub description: String,
    pub policy: ToolPolicy,
    /// JSON Schema of the argument object, from `schemars` (which emits **draft-07** at 0.8).
    /// Both provider envelopes accept draft-07; the dialect is stated rather than assumed
    /// because a schema the model silently misreads produces plausible-but-wrong tool calls.
    #[specta(type = serde_json::Value)]
    pub args_schema: serde_json::Value,
}

impl ToolSpec {
    /// The invariants that make the policy metadata trustworthy rather than decorative.
    ///
    /// Returns the reason it fails, so a violation names itself instead of asserting `false`.
    pub fn invariants_hold(&self) -> Result<(), String> {
        if self.destructive_or_networked() && self.policy.approval == Approval::Auto {
            return Err(format!(
                "{}: a networked or destructive tool may never be Approval::Auto — §8 requires \
                 approval regardless of policy, always",
                self.name
            ));
        }
        if self.policy.destructive && self.policy.approval != Approval::AlwaysPrompt {
            return Err(format!(
                "{}: a destructive tool must be Approval::AlwaysPrompt — a remembered answer \
                 is not consent for `rm -rf`",
                self.name
            ));
        }
        if self.name.trim().is_empty() || self.description.trim().is_empty() {
            return Err(format!("{}: name and description are model-facing, never blank", self.name));
        }
        if self.args_schema.get("type").and_then(serde_json::Value::as_str) != Some("object") {
            return Err(format!(
                "{}: argument schemas must be objects — positional args have no stable names \
                 across providers",
                self.name
            ));
        }
        Ok(())
    }

    fn destructive_or_networked(&self) -> bool {
        self.policy.destructive || self.policy.touches_network
    }
}

/// Declares one tool: its name, its model-facing prose, its policy, and its `Args` type.
///
/// The macro exists so a tool cannot be added without all four — a declaration site that
/// compiles is a declaration that is complete.
macro_rules! declare_tools {
    ($( $(#[$doc:meta])* $args:ident => $name:literal, $policy:expr, $desc:literal );* $(;)?) => {
        /// Every tool the agent may call, in a stable order (the generated artifacts are
        /// byte-comparable across runs — L7's determinism habit applied to the contract).
        pub fn manifest() -> Vec<ToolSpec> {
            vec![$(
                ToolSpec {
                    name: $name.to_string(),
                    description: $desc.to_string(),
                    policy: $policy,
                    args_schema: schema_of::<$args>(),
                },
            )*]
        }
    };
}

fn schema_of<T: schemars::JsonSchema>() -> serde_json::Value {
    let schema = schemars::schema_for!(T);
    serde_json::to_value(schema).expect("schemars emits valid JSON")
}

// ---------------------------------------------------------------------------------------------
// Argument types. Each is a plain object with named fields: positional arguments have no stable
// naming across providers, and an optional field is how a provider-agnostic default is spelled.
// ---------------------------------------------------------------------------------------------

/// Arguments for `read_file`.
#[derive(Debug, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ReadFileArgs {
    /// Repository-relative path. Absolute paths, `..` traversal, and the credential denylist
    /// (`.env`, `~/.ssh`, keychains) are rejected by the orchestrator, not by the model.
    pub path: String,
    /// Truncate after this many bytes. Unbounded reads are a budget violation (L15.4).
    pub max_bytes: Option<u32>,
}

/// Arguments for `list_dir`.
#[derive(Debug, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ListDirArgs {
    /// Repository-relative directory.
    pub path: String,
    /// Walk subdirectories. Depth and entry count are budgeted regardless (L15.4).
    pub recursive: Option<bool>,
}

/// Arguments for `search_text`.
#[derive(Debug, Serialize, Deserialize, schemars::JsonSchema)]
pub struct SearchTextArgs {
    /// Literal or regular-expression pattern.
    pub pattern: String,
    /// Restrict to a repository-relative subtree.
    pub path: Option<String>,
    /// Cap on returned matches.
    pub max_results: Option<u32>,
}

/// Arguments for `write_file`.
#[derive(Debug, Serialize, Deserialize, schemars::JsonSchema)]
pub struct WriteFileArgs {
    /// Repository-relative path **inside the shadow worktree**. The user's checkout is not
    /// reachable from this tool by construction (L19).
    pub path: String,
    /// Full replacement contents.
    pub contents: String,
}

/// Arguments for `run_command`.
#[derive(Debug, Serialize, Deserialize, schemars::JsonSchema)]
pub struct RunCommandArgs {
    /// Argv, already split. A single shell string would invite quoting bugs and make the
    /// allowlist unanalysable.
    pub argv: Vec<String>,
    /// Wall-clock budget in seconds. Every command is bounded (L15.4).
    pub timeout_seconds: Option<u32>,
}

/// Arguments for `ask_user` — the human-in-the-loop question (C5, LC18).
#[derive(Debug, Serialize, Deserialize, schemars::JsonSchema)]
pub struct AskUserArgs {
    /// The question, in plain language the user can answer without reading the transcript.
    pub question: String,
    /// Optional fixed choices. Omit for a free-text answer.
    pub options: Option<Vec<String>>,
}

/// Arguments for `prove` — the tool that makes this an agent nobody else can build.
#[derive(Debug, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ProveArgs {
    /// Baseline revision. Defaults to the task's pre-edit baseline when omitted.
    pub base: Option<String>,
    /// Restrict proving to these fully-qualified symbols; omit to prove the changed set.
    pub symbols: Option<Vec<String>>,
    /// Per-target input budget. The verdict always states what was and was not exercised (L2).
    pub max_inputs: Option<u32>,
}

declare_tools! {
    ReadFileArgs => "read_file", ToolPolicy::read_only(),
        "Read a repository-relative file. Returns its contents, truncated to max_bytes. \
         Credential files are refused by the host, not by you.";

    ListDirArgs => "list_dir", ToolPolicy::read_only(),
        "List the entries of a repository-relative directory.";

    SearchTextArgs => "search_text", ToolPolicy::read_only(),
        "Search the repository for a pattern and return matching lines with their locations.";

    WriteFileArgs => "write_file", ToolPolicy {
        approval: Approval::Auto,
        touches_network: false,
        destructive: false,
        writes: WriteScope::ShadowWorktree,
    },
        "Write a file in the shadow worktree. This never touches the user's working tree; the \
         change is staged for review and is undoable in one keystroke.";

    RunCommandArgs => "run_command", ToolPolicy {
        approval: Approval::PromptOncePerProject,
        touches_network: false,
        destructive: false,
        writes: WriteScope::ShadowWorktree,
    },
        "Run a build, test, or script inside the sandbox, with the shadow worktree as the \
         working directory. Output is streamed and capped.";

    ProveArgs => "prove", ToolPolicy::read_only(),
        "Run a differential behavioural proof of the current shadow worktree against the \
         baseline and return the verdict with its evidence. The verdict is computed by the \
         engine; you may explain it, never author it.";

    AskUserArgs => "ask_user", ToolPolicy {
        approval: Approval::AlwaysPrompt,
        touches_network: false,
        destructive: false,
        writes: WriteScope::None,
    },
        "Ask the user ONE question and wait for their answer. Use it when the task is \
         ambiguous in a way only they can settle; never to ask permission a tool policy \
         already handles. The answer arrives as this tool's result.";
}

// ---------------------------------------------------------------------------------------------
// Model-facing adapters. Pure functions of the manifest: adding a provider must not touch
// feature code (master prompt §7), and the two shapes below differ only in envelope.
// ---------------------------------------------------------------------------------------------

/// Anthropic Messages API tool definitions: `{name, description, input_schema}`.
pub fn anthropic_tool_defs(manifest: &[ToolSpec]) -> serde_json::Value {
    serde_json::Value::Array(
        manifest
            .iter()
            .map(|tool| {
                serde_json::json!({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.args_schema,
                })
            })
            .collect(),
    )
}

/// OpenAI-compatible tool definitions: `{type: "function", function: {…, parameters}}`. The
/// same envelope serves every OpenAI-compatible endpoint (Ollama, groq, OpenRouter, …), which
/// is why P1's provider breadth costs one adapter rather than twelve.
pub fn openai_tool_defs(manifest: &[ToolSpec]) -> serde_json::Value {
    serde_json::Value::Array(
        manifest
            .iter()
            .map(|tool| {
                serde_json::json!({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.args_schema,
                    },
                })
            })
            .collect(),
    )
}

/// The canonical committed document: the manifest plus a version so a stored agent turn can
/// say which tool contract it ran under.
pub fn canonical_document() -> serde_json::Value {
    serde_json::json!({
        "$comment": "Boundary D — generated by `make gen-contracts`. Do not edit by hand.",
        "protocol_version": PROTOCOL_VERSION,
        "tools": manifest(),
    })
}

/// Bumped whenever a tool is added, removed, or its arguments change shape. Stored with agent
/// turns so a replayed turn is interpreted under the contract it actually ran under.
pub const PROTOCOL_VERSION: u32 = 1;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_declared_tool_satisfies_its_own_policy_invariants() {
        for tool in manifest() {
            tool.invariants_hold().expect("declared tool violates a policy invariant");
        }
    }

    #[test]
    fn a_networked_tool_may_not_be_auto_approved() {
        // The invariant exists to be violated by a future careless declaration; prove it bites.
        let bad = ToolSpec {
            name: "fetch_url".into(),
            description: "fetch a url".into(),
            policy: ToolPolicy {
                approval: Approval::Auto,
                touches_network: true,
                destructive: false,
                writes: WriteScope::None,
            },
            args_schema: serde_json::json!({"type": "object"}),
        };
        let err = bad.invariants_hold().expect_err("networked + Auto must be rejected");
        assert!(err.contains("never be Approval::Auto"), "{err}");
    }

    #[test]
    fn a_destructive_tool_must_always_prompt() {
        let bad = ToolSpec {
            name: "force_push".into(),
            description: "force push".into(),
            policy: ToolPolicy {
                approval: Approval::PromptOncePerProject,
                touches_network: false,
                destructive: true,
                writes: WriteScope::ShadowWorktree,
            },
            args_schema: serde_json::json!({"type": "object"}),
        };
        let err = bad.invariants_hold().expect_err("destructive + remembered must be rejected");
        assert!(err.contains("AlwaysPrompt"), "{err}");
    }

    #[test]
    fn blank_model_facing_prose_is_rejected() {
        let bad = ToolSpec {
            name: "x".into(),
            description: "   ".into(),
            policy: ToolPolicy::read_only(),
            args_schema: serde_json::json!({"type": "object"}),
        };
        assert!(bad.invariants_hold().is_err());
    }

    #[test]
    fn non_object_argument_schemas_are_rejected() {
        let bad = ToolSpec {
            name: "x".into(),
            description: "d".into(),
            policy: ToolPolicy::read_only(),
            args_schema: serde_json::json!({"type": "array"}),
        };
        let err = bad.invariants_hold().expect_err("non-object args must be rejected");
        assert!(err.contains("must be objects"), "{err}");
    }

    #[test]
    fn tool_names_are_unique_and_stable_in_order() {
        let names: Vec<String> = manifest().into_iter().map(|t| t.name).collect();
        let mut sorted = names.clone();
        sorted.sort();
        sorted.dedup();
        assert_eq!(sorted.len(), names.len(), "duplicate tool name in the manifest");
        assert_eq!(
            names,
            vec![
                "read_file",
                "list_dir",
                "search_text",
                "write_file",
                "run_command",
                "prove",
                "ask_user"
            ],
            "tool order is part of the generated artifact; changing it is a contract change"
        );
    }

    #[test]
    fn no_tool_can_write_the_users_working_tree() {
        // L19 by construction: WriteScope has no such variant, so this is a proof that the
        // enum stayed closed rather than a runtime check that could rot.
        for tool in manifest() {
            match tool.policy.writes {
                WriteScope::None | WriteScope::ShadowWorktree => {}
            }
        }
    }

    #[test]
    fn generation_is_deterministic() {
        assert_eq!(canonical_document(), canonical_document());
    }

    #[test]
    fn every_args_schema_is_a_json_schema_object_with_properties() {
        for tool in manifest() {
            assert_eq!(tool.args_schema["type"], "object", "{}", tool.name);
            assert!(
                tool.args_schema.get("properties").is_some(),
                "{} has no properties — a model cannot call it",
                tool.name
            );
        }
    }

    #[test]
    fn anthropic_adapter_carries_name_description_and_schema() {
        let defs = anthropic_tool_defs(&manifest());
        let first = &defs[0];
        assert_eq!(first["name"], "read_file");
        assert!(first["description"].as_str().is_some_and(|d| !d.is_empty()));
        assert_eq!(first["input_schema"]["type"], "object");
        assert_eq!(defs.as_array().map(Vec::len), Some(manifest().len()));
    }

    #[test]
    fn openai_adapter_wraps_the_same_schema_in_the_function_envelope() {
        let defs = openai_tool_defs(&manifest());
        let first = &defs[0];
        assert_eq!(first["type"], "function");
        assert_eq!(first["function"]["name"], "read_file");
        assert_eq!(first["function"]["parameters"]["type"], "object");
    }

    #[test]
    fn both_providers_expose_exactly_the_same_tools() {
        // The adapters differ in envelope only — a tool visible to one provider and not the
        // other would make F21's cross-model ranking compare unlike things.
        let anthropic = anthropic_tool_defs(&manifest());
        let openai = openai_tool_defs(&manifest());
        let a: Vec<&str> = anthropic.as_array().unwrap().iter().map(|t| t["name"].as_str().unwrap()).collect();
        let o: Vec<&str> = openai
            .as_array()
            .unwrap()
            .iter()
            .map(|t| t["function"]["name"].as_str().unwrap())
            .collect();
        assert_eq!(a, o);
    }

    #[test]
    fn the_canonical_document_pins_its_protocol_version() {
        assert_eq!(canonical_document()["protocol_version"], PROTOCOL_VERSION);
        assert_eq!(
            canonical_document()["tools"].as_array().map(Vec::len),
            Some(manifest().len())
        );
    }
}
