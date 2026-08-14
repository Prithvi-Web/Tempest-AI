/** Small deterministic formatters. UTC only — the dashboard renders evidence, not local time. */

export function shortSha(sha: string): string {
  return sha.slice(0, 7);
}

/** ISO-8601 → `YYYY-MM-DD HH:MM:SSZ`; malformed input is shown verbatim, never invented. */
export function formatUtc(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.toISOString().replace("T", " ").slice(0, 19)}Z`;
}

/** 0..1 → percentage with at most one decimal: 1 → "100%", 0.875 → "87.5%". */
export function formatPct(fraction: number): string {
  const pct = Math.max(0, Math.min(1, fraction)) * 100;
  const rounded = Math.round(pct * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}%`;
}

export function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
