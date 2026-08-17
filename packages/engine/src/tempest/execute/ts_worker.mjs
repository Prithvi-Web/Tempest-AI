/**
 * The TypeScript execution worker (wave 1, ADR-0028) — the JS twin of `_worker.py`'s
 * invocation core. One process per batch: imports the target `.ts` module via Node's
 * native type stripping (erasable syntax only — offsets and line numbers are preserved,
 * which is what makes per-input V8 coverage honest), invokes the exported target once per
 * input, and emits ONE JSON observation line per input on stdout.
 *
 * Contract notes mirroring the Python worker:
 * - A throw by the target is a LEGITIMATE observation ({raised}), never a worker failure.
 * - Values that cannot be canonicalized are reported `unrepresentable`, never guessed.
 * - Per-input executed lines come from the in-process V8 inspector (precise coverage
 *   deltas), scoped to the target file.
 * - Target console output is captured per input into `stdout`/`stderr` observations.
 */

import { readFileSync } from "node:fs";
import { Session } from "node:inspector";
import { pathToFileURL } from "node:url";

const MAX_DEPTH = 8;
const MAX_ITEMS = 256;

function canonicalize(value, depth = 0) {
  if (depth > MAX_DEPTH) return { __tempest__: "depth-capped" };
  if (value === null) return null;
  if (value === undefined) return { __tempest__: "undefined" };
  const t = typeof value;
  if (t === "number") {
    if (Number.isNaN(value)) return { __tempest__: "nan" };
    if (value === Infinity) return { __tempest__: "inf" };
    if (value === -Infinity) return { __tempest__: "-inf" };
    if (Object.is(value, -0)) return { __tempest__: "negzero" };
    return value;
  }
  if (t === "string" || t === "boolean") return value;
  if (t === "bigint") return { __tempest__: "bigint", v: value.toString() };
  if (t === "function") throw new Unrepresentable(`function ${value.name || "(anonymous)"}`);
  if (t === "symbol") throw new Unrepresentable(String(value));
  if (Array.isArray(value)) {
    if (value.length > MAX_ITEMS) throw new Unrepresentable(`array of ${value.length}`);
    return value.map((v) => canonicalize(v, depth + 1));
  }
  if (value instanceof Date) return { __tempest__: "date", v: value.toISOString() };
  if (value instanceof Map) {
    const entries = [...value.entries()].map(([k, v]) => [
      canonicalize(k, depth + 1),
      canonicalize(v, depth + 1),
    ]);
    entries.sort((a, b) => JSON.stringify(a[0]).localeCompare(JSON.stringify(b[0])));
    return { __tempest__: "map", v: entries };
  }
  if (value instanceof Set) {
    const items = [...value].map((v) => canonicalize(v, depth + 1));
    items.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    return { __tempest__: "set", v: items };
  }
  if (value instanceof Error) {
    return { __tempest__: "error", type: value.constructor.name, message: String(value.message) };
  }
  const proto = Object.getPrototypeOf(value);
  if (proto === Object.prototype || proto === null) {
    const keys = Object.keys(value).sort();
    if (keys.length > MAX_ITEMS) throw new Unrepresentable(`object of ${keys.length} keys`);
    const out = {};
    for (const k of keys) out[k] = canonicalize(value[k], depth + 1);
    return out;
  }
  throw new Unrepresentable(`instance of ${proto?.constructor?.name ?? "unknown class"}`);
}

class Unrepresentable extends Error {}

function decodeArg(arg) {
  if (arg !== null && typeof arg === "object") {
    if (!Array.isArray(arg) && typeof arg.__tempest_special__ === "string") {
      switch (arg.__tempest_special__) {
        case "NaN":
          return NaN;
        case "Infinity":
          return Infinity;
        case "-Infinity":
          return -Infinity;
        case "undefined":
          return undefined;
        default:
          return arg;
      }
    }
    if (Array.isArray(arg)) return arg.map(decodeArg);
    const out = {};
    for (const [k, v] of Object.entries(arg)) out[k] = decodeArg(v);
    return out;
  }
  return arg;
}

// ── in-process V8 precise coverage, delta per input ────────────────────────────────────
const session = new Session();
session.connect();
function post(method, params) {
  return new Promise((resolve, reject) => {
    session.post(method, params, (err, result) => (err ? reject(err) : resolve(result)));
  });
}

function offsetsToLineStarts(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i += 1) if (text[i] === "\n") starts.push(i + 1);
  return starts;
}

function lineOfOffset(starts, offset) {
  let lo = 0;
  let hi = starts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid] <= offset) lo = mid;
    else hi = mid - 1;
  }
  return lo + 1; // 1-indexed
}

function executedLines(coverage, targetUrl, lineStarts, textLength) {
  // V8 block coverage nests ranges outer-first; an inner count-0 range voids the lines it
  // FULLY contains (a partially-contained line still ran up to the branch — keeping it is
  // the conservative, honest reading for changed-line coverage).
  const lines = new Set();
  const dead = [];
  for (const script of coverage.result) {
    if (script.url !== targetUrl) continue;
    for (const fn of script.functions) {
      for (const range of fn.ranges) {
        const startLine = lineOfOffset(lineStarts, range.startOffset);
        const endLine = lineOfOffset(lineStarts, Math.max(range.startOffset, range.endOffset - 1));
        if (range.count > 0) {
          for (let line = startLine; line <= endLine; line += 1) lines.add(line);
        } else {
          dead.push(range);
        }
      }
    }
  }
  for (const range of dead) {
    const first = lineOfOffset(lineStarts, range.startOffset);
    const last = lineOfOffset(lineStarts, Math.max(range.startOffset, range.endOffset - 1));
    for (let line = first; line <= last; line += 1) {
      const lineStart = lineStarts[line - 1];
      const lineEnd = line < lineStarts.length ? lineStarts[line] - 1 : textLength;
      if (range.startOffset <= lineStart && range.endOffset >= lineEnd) lines.delete(line);
    }
  }
  return [...lines].sort((a, b) => a - b);
}

// ── main ───────────────────────────────────────────────────────────────────────────────
const jobPath = process.argv[2];
const job = JSON.parse(readFileSync(jobPath, "utf8"));
const targetUrl = pathToFileURL(job.target_file).href;
const targetText = readFileSync(job.target_file, "utf8");
const lineStarts = offsetsToLineStarts(targetText);

const realWrite = process.stdout.write.bind(process.stdout);
function emit(payload) {
  realWrite(`${JSON.stringify(payload)}\n`);
}

let mod;
try {
  mod = await import(targetUrl);
} catch (err) {
  emit({ fatal: "import", error: `${err?.constructor?.name ?? "Error"}: ${err?.message ?? err}` });
  process.exit(3);
}
const fn = mod[job.export_name];
if (typeof fn !== "function") {
  emit({ fatal: "import", error: `export \`${job.export_name}\` is not a function` });
  process.exit(3);
}

await post("Profiler.enable");
await post("Profiler.startPreciseCoverage", { callCount: false, detailed: true });
await post("Profiler.takePreciseCoverage"); // drain import-time coverage — per-input deltas only

for (let index = 0; index < job.inputs.length; index += 1) {
  const args = job.inputs[index].map(decodeArg);
  let outBuf = "";
  let errBuf = "";
  const stdoutWrite = process.stdout.write;
  const stderrWrite = process.stderr.write;
  process.stdout.write = (chunk) => ((outBuf += String(chunk)), true);
  process.stderr.write = (chunk) => ((errBuf += String(chunk)), true);

  let raised = null;
  let returnPresent = false;
  let returnCanon = null;
  let unrepresentable = null;
  try {
    let result = fn(...args);
    if (result !== null && typeof result?.then === "function") result = await result;
    try {
      returnCanon = canonicalize(result);
      returnPresent = true;
    } catch (unrep) {
      unrepresentable = unrep.message;
    }
  } catch (err) {
    raised = {
      type: err?.constructor?.name ?? "Error",
      message: String(err?.message ?? err),
    };
  } finally {
    process.stdout.write = stdoutWrite;
    process.stderr.write = stderrWrite;
  }

  const coverage = await post("Profiler.takePreciseCoverage");
  emit({
    index,
    outcome: "COMPLETED",
    return_present: returnPresent,
    return_canon: returnCanon,
    raised,
    unrepresentable,
    stdout: outBuf,
    stderr: errBuf,
    executed_lines: executedLines(coverage, targetUrl, lineStarts, targetText.length),
  });
}
process.exit(0);
