import {
  langBadge,
  severityChipClass,
  verdictChipClass,
  verdictNote,
  type Lang,
  type Severity,
  type Verdict,
} from "@/lib/verdict";

const CHIP_BASE =
  "inline-block whitespace-nowrap border px-1.5 py-px text-[10px] uppercase tracking-widest";

/** The honest verdict vocabulary, verbatim (Law L2) — never abbreviated, never renamed. */
export function VerdictChip({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`${CHIP_BASE} ${verdictChipClass(verdict)}`} title={verdictNote(verdict)}>
      {verdict}
    </span>
  );
}

export function SeverityChip({ severity }: { severity: Severity }) {
  return <span className={`${CHIP_BASE} ${severityChipClass(severity)}`}>{severity}</span>;
}

export function LangBadge({ lang }: { lang: Lang }) {
  return (
    <span className={`${CHIP_BASE} border-panel-line text-ink-dim`} title={lang}>
      {langBadge(lang)}
    </span>
  );
}
