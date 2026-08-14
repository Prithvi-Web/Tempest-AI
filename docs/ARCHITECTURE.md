# Tempest AI — Engine Architecture

Nine stages, one-directional data flow. Each stage is a separate module in
`packages/engine/src/tempest/` with a typed interface and its own tests.

```
 diff → [1 Target Selection] → [2 Environment Reproduction] → [3 Harness Synthesis]
      → [4 Determinism Layer] → [5 Input Generation] → [6 Dual Execution]
      → [7 Observation & Comparison] → [8 Delta Minimization] → [9 Report Assembly]
```

Shared vocabulary lives in `tempest/model.py` (frozen dataclasses / enums):
`Verdict`, `DivergenceClass`, `ReasonCode`, `TargetClassification`, `Stage`. The API's Pydantic
schemas mirror these enums (single Python source; OpenAPI exports them to TS — CLAUDE.md §9).

---

## Stage 1 — Target Selection (`tempest/targets/`)

Parse the diff, build import/call graphs for base and head, classify changed symbols.

```python
@dataclass(frozen=True)
class ChangedSymbol:
    symbol: str                # dotted path, e.g. "pkg.mod.fn" or "pkg.mod.Cls.method"
    file_path: str             # repo-relative
    lang: Lang                 # PYTHON | TYPESCRIPT
    classification: TargetClassification   # PURE_CANDIDATE | IMPURE_RECORDABLE | UNREACHABLE
    changed_lines: frozenset[int]          # head-side line numbers changed inside the symbol
    reason_code: ReasonCode | None         # set iff UNREACHABLE
    callers: tuple[str, ...]   # transitive callers up to depth k (default 2)

def select_targets(repo: Path, base_ref: str, head_ref: str, *, depth: int = 2) -> TargetSelection
```

Python analysis: `ast` for structure + a lightweight import-graph resolver; purity classification
by scanning the symbol's call/attribute surface against the IO allowlist (`targets/io_surface.py`).
`UNREACHABLE` targets flow straight to the bundle as `UNPROVEN` — never dropped.

## Stage 2 — Environment Reproduction (`tempest/envrepro/`)

```python
@dataclass(frozen=True)
class MaterializedEnv:
    revision: str              # sha
    worktree: Path             # git worktree checkout
    python: Path               # pinned interpreter
    env: Mapping[str, str]     # normalized: LC_ALL=C.UTF-8, TZ=UTC, PYTHONHASHSEED=0
    deps_fingerprint: str      # lockfile hash; base≠head fingerprint is reported, not hidden

def materialize(repo: Path, ref: str, cache: Path) -> MaterializedEnv
```

`git worktree add --detach` per revision; installer detection (uv lockfile → uv sync; else pip
hash-pinned); interpreter resolved from `.python-version`/`pyproject.toml`. Both revisions always
run under identical env/locale/seed settings.

## Stage 3 — Harness Synthesis (`tempest/harness/`)

```python
class AdapterSynthesizer(Protocol):
    def propose(self, target: ChangedSymbol, ctx: SynthesisContext, attempt: int) -> AdapterSource: ...

@dataclass(frozen=True)
class ValidatedAdapter:
    target: ChangedSymbol
    source: str                # the adapter module code
    cache_key: str             # (symbol, file-hash)
    validated_by_execution: bool   # always True for accepted adapters

def synthesize(target, envs, synthesizers: Sequence[AdapterSynthesizer]) -> ValidatedAdapter | SynthesisFailure
```

Synthesizers are tried in order: `TypeDrivenSynthesizer` (deterministic, from type hints/usage
inference — keeps the CLI fully offline) then optional `LLMSynthesizer` (only if `ANTHROPIC_API_KEY`
present — ADR-0006). **Acceptance is by execution only**: the adapter must invoke the target once
without raising in adapter code (target exceptions are legitimate observations). Three failures →
`UNPROVEN(HARNESS_SYNTHESIS_FAILED)` with attempts attached. Cache per `(symbol, file-hash)`.

## Stage 4 — Determinism Layer (`tempest/determinism/`) — THE MOAT

```python
@dataclass(frozen=True)
class Interaction:
    surface: Surface           # CLOCK | RANDOM | FS | NET | PROC | ENV
    call: str                  # normalized call signature
    ordinal: int               # per-(surface, call) sequence number
    payload: bytes             # canonical-encoded result to replay
    fingerprint: str           # content address

class Cassette:                # ordered ledger; append-only in record, cursor in replay
    def record(self, i: Interaction) -> None
    def replay(self, surface: Surface, call: str) -> Interaction   # raises CassetteMiss
    def ledger(self) -> tuple[Interaction, ...]
```

Record mode runs base once to fill the cassette; replay mode feeds base and head from the identical
cassette. Shims (`determinism/shims/{clock,random,fs,net,proc}.py`) are installed inside the target
process before user code imports, via an injected bootstrap (`sitecustomize`-equivalent).
A **cassette miss is `DIVERGENT`** (head did something new), not an error. A surface we cannot
intercept (ctypes FFI, native addon) → `UNPROVEN(UNINTERCEPTABLE_EFFECT)` naming the surface.

## Stage 5 — Input Generation (`tempest/generate/`)

```python
@dataclass(frozen=True)
class CandidateInput:
    args: tuple[object, ...]
    kwargs: Mapping[str, object]
    provenance: Provenance     # TYPE_DERIVED | CORPUS_MINED | MUTATED
    covered_arcs: frozenset[Arc] | None    # filled after execution feedback

def generate(target, adapter, budget: Budget) -> Iterator[CandidateInput]
```

Three merged sources: Hypothesis `from_type` strategies; corpus mining of literals from tests/
docstrings/call sites; coverage-guided mutation keyed by branch-arc sets (coverage.py arcs).
Scheduler weights inputs that reach **changed lines**; `changed_line_coverage` is reported per
target. Budgets: `max_inputs` (300), `max_wall_seconds` (30), global run budget.

## Stage 6 — Dual Execution (`tempest/execute/`)

```python
@dataclass(frozen=True)
class Observation:
    return_value: CanonicalValue | None
    raised: RaisedInfo | None          # type, normalized message, module
    effects: tuple[EffectEntry, ...]   # ordered ledger interactions
    stdout: str; stderr: str           # normalized
    exit_status: int
    timing: Timing                     # wall_ns, cpu_ns — recorded, NEVER compared

def run_pair(inp, base_env, head_env, adapter, cassette, sandbox: Sandbox) -> tuple[Observation, Observation]
```

Always **separate processes** per revision (module state must not leak). Sandbox backends:
`DockerSandbox` (production: no network, RO rootfs + scratch mount, memory/wall limits, non-root,
seccomp) and `ProcessSandbox` (first-party test fixtures only — ADR-0003). No Docker at runtime →
`UNPROVEN(SANDBOX_UNAVAILABLE)`. Crash / hang (per-input timeout) / OOM are observations.

## Stage 7 — Observation & Comparison (`tempest/compare/`)

```python
def compare(base: Observation, head: Observation, cfg: EquivalenceConfig) -> Divergence | None
```

Canonical serialization: key-sorted dicts, order-normalized sets, NaN==NaN, `-0.0` vs `0.0` as a
distinct low-severity class, configurable float tolerance (default exact). Unserializable values →
structural fingerprint; if neither side fingerprints, that input is `UNPROVEN`, not silently equal.
Exception messages normalized by `compare/normalize.py` — one audited ruleset file with tests
proving each rule does not mask a known real difference. Divergences carry a `DivergenceClass`:
`RETURN_VALUE | EXCEPTION_TYPE | EXCEPTION_MESSAGE | EFFECT_SEQUENCE | EFFECT_ARGUMENTS |
CASSETTE_MISS | CRASH | HANG | OUTPUT_STREAM`. Timing never contributes to a verdict.

## Stage 8 — Delta Minimization (`tempest/minimize/`)

```python
def minimize(div: Divergence, rerun: Callable[[CandidateInput], Divergence | None]) -> MinimizedRepro
```

Structural ddmin over the input tree (drop keys, shrink lists, truncate strings, numbers → 0) +
Hypothesis shrinkers when generator-born. Invariant (property-tested): every reduction still
reproduces the **same `DivergenceClass`**. Output includes a standalone repro script (single file,
cassette inlined/referenced) — the product artifact.

## Stage 9 — Report Assembly (`tempest/bundle/`)

```python
def write_bundle(run: RunResult, out_dir: Path) -> BundlePaths   # dir + .tempest.zip
def read_bundle(path: Path) -> RunResult                         # total inverse; round-trip tested
```

`manifest.json` (schema_version int, engine_version, container metadata), per-target results,
cassettes, minimized repros, coverage. One producer, many renderers: the CLI's terminal report and
the API's ingestion both consume this bundle byte-for-byte. Schema documented in `docs/BUNDLE_SCHEMA.md`.

---

## Process topology

- **CLI** (`tempest/cli/`): typer app orchestrating stages 1→9 locally; fully offline.
- **ts-sidecar**: long-lived Node process, JSON-RPC 2.0 over stdio; serves stage-1 analysis,
  type→arbitrary compilation, and Node-side execution bootstrap for TS targets.
- **API** (`packages/api`): FastAPI ingesting bundles into Postgres/MinIO; arq workers; SSE events.
- **Web** (`packages/web`): renders bundles via generated client only. No re-derived verdict logic.
