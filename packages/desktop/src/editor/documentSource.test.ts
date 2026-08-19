/**
 * The offline completion source (Phase 20.3b).
 *
 * States enumerated first: cursor not in an identifier · a one-character prefix · a prefix
 * nothing matches · exactly one match · several matches with different frequencies · a tie on
 * frequency · a word that IS the prefix (no completion to offer) · the partially typed word
 * appearing in its own corpus · non-identifier characters adjacent to the cursor.
 */
import { describe, expect, it } from "vitest";

import { completeFromDocument, documentCompletionSource, prefixAt } from "./documentSource";

describe("prefixAt", () => {
  it("reads the identifier immediately before the cursor", () => {
    expect(prefixAt("const val")).toBe("val");
    expect(prefixAt("foo(bar_ba")).toBe("bar_ba");
    expect(prefixAt("x = $sco")).toBe("$sco");
  });

  it("is empty when the cursor is not inside an identifier", () => {
    expect(prefixAt("")).toBe("");
    expect(prefixAt("const x = ")).toBe("");
    expect(prefixAt("total + ")).toBe("");
    // A number is not an identifier start.
    expect(prefixAt("42")).toBe("");
  });
});

describe("completeFromDocument", () => {
  it("refuses to guess from a single character", () => {
    // A one-character prefix matches most of a file; suggesting from it is noise, not help.
    expect(completeFromDocument("calculate calculate", "c")).toBe("");
  });

  it("returns nothing when no identifier extends the prefix", () => {
    expect(completeFromDocument("alpha beta", "zzz")).toBe("");
  });

  it("completes the only match", () => {
    expect(completeFromDocument("calculateTotal()", "calc")).toBe("ulateTotal");
  });

  it("prefers the identifier the file uses most", () => {
    const doc = "renderRow renderRow renderRow renderHeader";
    expect(completeFromDocument(doc, "render")).toBe("Row");
  });

  it("breaks a frequency tie toward the shorter completion", () => {
    // Less to undo when the guess is wrong.
    expect(completeFromDocument("parseA parseAlphabet", "parse")).toBe("A");
  });

  it("offers nothing when the only match IS the prefix", () => {
    expect(completeFromDocument("total total", "total")).toBe("");
  });
});

describe("documentCompletionSource", () => {
  it("does not complete the typed word with itself", async () => {
    // The partially typed word is removed from the corpus first; otherwise the prefix would
    // match its own occurrence and offer nothing.
    const before = "function calculateTotal() {}\nconst x = calc";
    await expect(
      documentCompletionSource({ textBeforeCursor: before, textAfterCursor: "" }),
    ).resolves.toBe("ulateTotal");
  });

  it("uses text after the cursor too", async () => {
    const suggestion = await documentCompletionSource({
      textBeforeCursor: "ren",
      textAfterCursor: "\nfunction renderRow() {}",
    });
    expect(suggestion).toBe("derRow");
  });

  it("is silent when the cursor is not in an identifier", async () => {
    expect(await documentCompletionSource({ textBeforeCursor: "x = ", textAfterCursor: "" })).toBe("");
  });
});
