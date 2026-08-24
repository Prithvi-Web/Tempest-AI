/**
 * The keyless-turn remedy's decision (ADR-0080 §8).
 *
 * This predicate is the whole consumer side of a contract that shipped with no consumer at
 * all: the engine has carried `remedy: "local-model"` on the error part since the feature
 * landed, and nothing read it. The tests below are about the two ways a reader of an untyped
 * frame field goes wrong — trusting a shape it did not check, and matching on prose.
 */
import { describe, expect, it } from "vitest";

import {
  LOCAL_MODEL_REMEDY,
  hasLocalModelRemedy,
} from "../../platform/client/tempest/views/remedy";

describe("hasLocalModelRemedy", () => {
  it("recognises the remedy the engine actually sends", () => {
    // The exact shape `chatwire.error_content_part` builds.
    expect(
      hasLocalModelRemedy({
        type: "error",
        error: "no API key for Anthropic. Set it in Settings, or export ANTHROPIC_API_KEY.",
        remedy: "local-model",
      }),
    ).toBe(true);
  });

  it("does not fire on an error that has no way out", () => {
    // Most errors carry no remedy, and offering "get a local model" for a 500 from a provider
    // the user has configured would be advice that does not answer the problem.
    expect(hasLocalModelRemedy({ type: "error", error: "the provider returned 500" })).toBe(false);
    expect(hasLocalModelRemedy({ type: "error", error: "no API key", remedy: "" })).toBe(false);
    expect(hasLocalModelRemedy({ type: "error", error: "x", remedy: "some-future-remedy" })).toBe(
      false,
    );
  });

  it("never fires on the PROSE, which is the whole reason the field exists", () => {
    // A client that matched the sentence would light up here — and would then go dark the next
    // time somebody improved the sentence, which this repository does deliberately.
    expect(
      hasLocalModelRemedy({ type: "error", error: "no API key for Anthropic — local-model" }),
    ).toBe(false);
  });

  it("survives a shape it was not given, rather than throwing inside a message renderer", () => {
    // The caller is the vendored `Part.tsx`, rendering one part of one message. An exception
    // there costs the user the whole conversation view, so an unexpected frame must be a
    // `false`, not a crash.
    for (const notAPart of [null, undefined, "local-model", 7, [], () => LOCAL_MODEL_REMEDY]) {
      expect(hasLocalModelRemedy(notAPart)).toBe(false);
    }
  });

  it("keeps the value the engine and the client have to agree on in one place", () => {
    // If these two ever disagree the affordance silently stops appearing, which is the
    // failure mode a structured remedy was chosen to avoid in the first place.
    expect(LOCAL_MODEL_REMEDY).toBe("local-model");
  });
});
