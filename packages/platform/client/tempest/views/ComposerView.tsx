import { useMemo, useRef, useState } from "react";

import type { HunkRow } from "../../../../desktop/src/generated/bindings";
import { useComposeChange } from "./hooks";
import { VerdictChip } from "./vocabulary";

/** F12 — the multi-file composer, and the column that makes it more than a diff viewer.
 *
 * Every other review tool shows you which lines changed. This shows, per hunk, **what that hunk
 * does**: the engine's verdict over the symbols it touches, how many divergences it caused, and
 * how much of what it changed was actually exercised. Accepting a subset re-proves THAT subset
 * (ADR-0061) — it does not filter the whole change's evidence, because hunks interact and a tree
 * nobody executed has no verdict to report (L16).
 *
 * Nothing here computes a verdict. Every value in the third column arrives from the engine
 * through `composeChange`; the view's whole job is to render it without softening it (L17).
 */

/** Fixed, because windowing needs to know where a row is without measuring it. Changing this
 * means changing `--composer-row` in tempest-views.css — the two are one number in two
 * languages. */
const ROW_HEIGHT = 44;

/** Rows rendered beyond each edge of the viewport. Enough that a fast scroll never shows a gap,
 * small enough that a 1000-hunk changeset still mounts ~20 nodes rather than 1000. */
const OVERSCAN = 6;

/** Inputs per symbol for a composer proof.
 *
 * Smaller than a full run's on purpose: this re-proves on every toggle, and a budget that makes
 * one toggle take a minute is a budget that makes the feature unusable. The honesty is in the
 * vocabulary, not in the number — `EQUIVALENT_UNDER_BUDGET` says exactly what it is, and the
 * count line below names the budget so nobody reads a fast answer as a thorough one. A full run
 * is what `New proof` is for. */
const COMPOSER_INPUTS = 12;

function coverageLabel(row: HunkRow): string {
  // Two different absences, both shown as "—" rather than as 0%: a hunk with no executable
  // symbol, and a coverage the engine did not report. Rendering either as 0% would state a
  // measurement nobody took.
  if (!row.qualnames.length || row.changed_line_coverage === null) return "—";
  return `${Math.round(row.changed_line_coverage * 100)}%`;
}

/** One row. Split out so React can skip re-rendering the 980 rows a toggle did not touch.
 *
 * `accepted` is the USER's intent, held locally, and the checkbox follows it instantly.
 * `row.accepted` is the server's account of the selection it proved — a different fact, and
 * driving the checkbox from it would make a click do nothing until a proof came back.
 * `stale` says the third column is about the PREVIOUS selection while the next one runs; a
 * verdict that silently describes a selection the user has already changed is the one thing
 * this column must never do.
 */
function Row({
  row,
  accepted,
  stale,
  onToggle,
}: {
  row: HunkRow;
  accepted: boolean;
  stale: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <li className="composer-row" style={{ height: ROW_HEIGHT }} data-testid="composer-row">
      <label className="composer-accept">
        <input
          type="checkbox"
          checked={accepted}
          onChange={() => onToggle(row.id)}
          aria-label={`accept ${row.summary}`}
        />
      </label>
      <span className="composer-where" title={row.path}>
        {row.summary}
      </span>
      <span
        className={`composer-impact${stale ? " stale" : ""}`}
        title={stale ? "from the previous selection — the new one is still being proved" : ""}
      >
        <VerdictChip verdict={row.verdict} />
        {row.divergence_count > 0 && (
          <span className="composer-divergences">
            {row.divergence_count} divergence{row.divergence_count === 1 ? "" : "s"}
          </span>
        )}
        <span className="composer-coverage" title="changed-line coverage">
          {coverageLabel(row)}
        </span>
      </span>
      {/* A row the engine could not speak about says so in words. A blank cell beside a code
          change reads as reassurance nobody produced. */}
      <span className="composer-reason">{row.reason || row.qualnames.join(", ")}</span>
    </li>
  );
}

export function ComposerView() {
  const [repoPath, setRepoPath] = useState("");
  const [base, setBase] = useState("");
  const [head, setHead] = useState("");
  const [submitted, setSubmitted] = useState<{ repo: string; base: string; head: string } | null>(
    null,
  );
  /** Which hunks the user has turned OFF. Empty means "everything", which is the state the view
   * opens in and is sent as `accepted: null`; once anything is rejected an explicit list goes
   * over the wire, because `[]` and `null` are different questions to the engine. */
  const [rejected, setRejected] = useState<ReadonlySet<string>>(new Set());
  /** Every hunk id the last answer contained. Held separately because `accepted` is part of the
   * query KEY: deriving it from the current response would make the request depend on its own
   * result, and the first toggle would have nothing to subtract from. */
  const [knownIds, setKnownIds] = useState<readonly string[]>([]);
  const [scrollTop, setScrollTop] = useState(0);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  const accepted = useMemo(
    () => (rejected.size === 0 ? null : knownIds.filter((id) => !rejected.has(id))),
    [rejected, knownIds],
  );

  const query = useComposeChange({
    repoPath: submitted?.repo ?? "",
    base: submitted?.base ?? "",
    head: submitted?.head ?? "",
    accepted,
    maxInputs: COMPOSER_INPUTS,
  });

  const rows = query.data?.hunks ?? [];
  const ids = rows.map((r) => r.id).join("\u0000");
  if (rows.length > 0 && ids !== knownIds.join("\u0000")) {
    // Render-phase state sync, the documented React pattern for "derive from props/data": the
    // alternative is an effect, which paints one frame with a stale id list and makes the first
    // toggle after a fetch subtract from the wrong set.
    setKnownIds(rows.map((r) => r.id));
  }

  const height = viewportRef.current?.clientHeight ?? 480;
  const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const visible = Math.ceil(height / ROW_HEIGHT) + OVERSCAN * 2;
  const slice = rows.slice(first, first + visible);

  function toggle(id: string) {
    setRejected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <main className="composer">
      <h1>Composer</h1>
      <p className="composer-lede">
        Every hunk, with what the engine found it does. Accepting a subset proves that subset —
        it does not reuse the whole change&rsquo;s evidence.
      </p>

      <form
        className="composer-form"
        onSubmit={(event) => {
          event.preventDefault();
          setRejected(new Set());
          setKnownIds([]);
          setSubmitted({ repo: repoPath, base, head });
        }}
      >
        <label>
          Repository
          <input value={repoPath} onChange={(e) => setRepoPath(e.target.value)} name="repo" />
        </label>
        <label>
          Base
          <input value={base} onChange={(e) => setBase(e.target.value)} name="base" />
        </label>
        <label>
          Head
          <input value={head} onChange={(e) => setHead(e.target.value)} name="head" />
        </label>
        <button type="submit" disabled={!repoPath || !base || !head}>
          Compose
        </button>
      </form>

      {query.isFetching && <p role="status">Proving the selection…</p>}
      {query.isError && (
        <p role="alert" className="composer-problem">
          {query.error instanceof Error ? query.error.message : "the composer could not run"}
        </p>
      )}
      {!query.isFetching && submitted && rows.length === 0 && !query.isError && (
        <p role="status">No hunks — nothing changed between those two revisions.</p>
      )}

      {rows.length > 0 && (
        <>
          <p className="composer-count" data-testid="composer-count">
            {rows.length} hunk{rows.length === 1 ? "" : "s"} ·{" "}
            {rows.filter((r) => !rejected.has(r.id)).length} accepted · {COMPOSER_INPUTS} inputs
            per symbol · {query.isFetching ? "re-proving…" : "proved as "}
            {!query.isFetching && <code>{query.data?.bundle_id}</code>}
          </p>
          {/* Windowed: a 1000-hunk changeset mounts ~20 nodes, not 1000. The spacer above and
              below is what keeps the scrollbar honest about how much there is. */}
          <div
            className="composer-viewport"
            ref={viewportRef}
            onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
            data-testid="composer-viewport"
          >
            <div style={{ height: rows.length * ROW_HEIGHT, position: "relative" }}>
              <ul
                className="composer-rows"
                style={{ transform: `translateY(${first * ROW_HEIGHT}px)` }}
              >
                {slice.map((row) => (
                  <Row
                    key={row.id}
                    row={row}
                    accepted={!rejected.has(row.id)}
                    stale={query.isFetching}
                    onToggle={toggle}
                  />
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
