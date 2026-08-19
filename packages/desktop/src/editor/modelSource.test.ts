/**
 * The model-then-document completion source (Phase 20.3d).
 *
 * States enumerated first: the model answers · no model configured (null) · the model returns an
 * empty string · the model returns only whitespace · the invoke itself throws · the model answers
 * but the document could too (the model must win) · neither can answer.
 *
 * The fallback is the behaviour that matters, and it is exactly what an integration test could
 * not force on demand — which is why `invokeLocal` is injected.
 */
import { describe, expect, it, vi } from "vitest";

import { MODEL_DEADLINE_MS, modelBackedSource } from "./modelSource";

// The generated Boundary B binding calls __TAURI_INVOKE, which does not exist outside Tauri.
// Mocked so the DEFAULT source — the one product code actually uses — is exercised here rather
// than only the injected one. Without this, nothing proved the source calls the real command.
vi.mock("../generated/bindings", () => ({
  commands: { localCompletion: vi.fn(async () => "from the generated binding") },
}));

const CONTEXT = {
  textBeforeCursor: "def calculateTotal(items):\n    return sum(items)\n\ncalc",
  textAfterCursor: "",
};

describe("modelBackedSource", () => {
  it("prefers the model when it answers", async () => {
    const source = modelBackedSource(async () => "ulateTotal(items)  # from the model");
    await expect(source(CONTEXT)).resolves.toBe("ulateTotal(items)  # from the model");
  });

  it("hands the model the text before the cursor and its share of the budget", async () => {
    const invoke = vi.fn(async () => "x");
    await modelBackedSource(invoke)(CONTEXT);
    expect(invoke).toHaveBeenCalledWith(CONTEXT.textBeforeCursor, MODEL_DEADLINE_MS);
    // Smaller than the 120 ms p50 budget: the fallback still has to render inside it.
    expect(MODEL_DEADLINE_MS).toBeLessThan(120);
  });

  it("falls back to the document when no model is configured", async () => {
    const source = modelBackedSource(async () => null);
    await expect(source(CONTEXT)).resolves.toBe("ulateTotal");
  });

  it("falls back when the model answers with nothing", async () => {
    await expect(modelBackedSource(async () => "")(CONTEXT)).resolves.toBe("ulateTotal");
  });

  it("falls back when the model answers with whitespace only", async () => {
    // Otherwise it renders as an invisible "accept me" under Tab.
    await expect(modelBackedSource(async () => "   \n ")(CONTEXT)).resolves.toBe("ulateTotal");
  });

  it("falls back when the invoke itself throws", async () => {
    // An IPC failure is not a completion failure the user should be shown; the offline source is
    // still a real answer.
    const source = modelBackedSource(async () => {
      throw new Error("ipc exploded");
    });
    await expect(source(CONTEXT)).resolves.toBe("ulateTotal");
  });

  it("returns nothing when neither the model nor the document can answer", async () => {
    const source = modelBackedSource(async () => null);
    await expect(
      source({ textBeforeCursor: "zzz_nothing_matches_this", textAfterCursor: "" }),
    ).resolves.toBe("");
  });
});

describe("the default source — the one product code uses", () => {
  it("calls the generated localCompletion binding", async () => {
    const { commands } = await import("../generated/bindings");
    const source = modelBackedSource();
    await expect(source(CONTEXT)).resolves.toBe("from the generated binding");
    expect(commands.localCompletion).toHaveBeenCalledWith(
      CONTEXT.textBeforeCursor,
      MODEL_DEADLINE_MS,
    );
  });
});
