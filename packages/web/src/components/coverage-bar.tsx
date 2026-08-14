import { formatPct } from "@/lib/format";

/**
 * Changed-line coverage as a plain CSS bar — no chart library (CLAUDE.md §5: default to tables).
 * Full coverage renders equivalent-green; anything less renders unproven-yellow, because
 * unexecuted changed lines prove nothing.
 */
export function CoverageBar({ fraction, wide = false }: { fraction: number; wide?: boolean }) {
  const clamped = Math.max(0, Math.min(1, fraction));
  return (
    <span className="inline-flex items-center gap-2">
      <span
        role="img"
        aria-label={`changed-line coverage ${formatPct(clamped)}`}
        className={`${wide ? "h-2 w-64" : "h-1.5 w-24"} inline-block border border-panel-line bg-panel align-middle`}
      >
        <span
          className={`block h-full ${clamped >= 1 ? "bg-equivalent" : "bg-unproven"}`}
          style={{ width: `${clamped * 100}%` }}
        />
      </span>
      <span className="text-xs tabular-nums text-ink">{formatPct(clamped)}</span>
    </span>
  );
}
