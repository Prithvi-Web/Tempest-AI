"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Copies evidence byte-for-byte. The label flip is status feedback, not decoration —
 * no animation, honest failure state if the clipboard API refuses.
 */
export function CopyButton({ text, label = "copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState("idle"), 1500);
  }

  return (
    <button
      type="button"
      onClick={onCopy}
      aria-live="polite"
      className={`border px-2 py-0.5 text-[10px] uppercase tracking-widest ${
        state === "failed"
          ? "border-divergent text-divergent"
          : state === "copied"
            ? "border-equivalent text-equivalent"
            : "border-panel-line text-ink-dim hover:border-ink-dim hover:text-ink"
      }`}
    >
      {state === "idle" ? label : state}
    </button>
  );
}
