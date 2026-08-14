# Run Bundle Schema — v1

A run bundle is the single source of truth for one `tempest prove` execution (Law L7: every run
is a self-contained, replayable artifact). One producer (`tempest.bundle.bundle.write_bundle`),
many renderers (CLI report, API ingestion, dashboard). `schema_version` is an integer; readers
refuse newer-than-known versions with an actionable error, and every schema change bumps it with
a migration path.

## Layout

```
<run-dir>/
├── manifest.json        # RunManifest
├── targets.json         # list[TargetRecord]
└── repros/
    └── <module>_<qualname>_<n>.py   # standalone, executable reproduction scripts
<run-dir>.tempest.zip    # the same three groups, zipped for upload/transport
```

## manifest.json (RunManifest)

| field | type | meaning |
|---|---|---|
| `schema_version` | int | bundle schema version (this document: **1**) |
| `engine_version` | str | tempest engine that produced the bundle |
| `repo` | str | repository name |
| `base_sha` / `head_sha` | str | full 40-char revisions compared |
| `created_at` | str | ISO-8601 UTC |
| `verdict` | Verdict | run-level verdict (precedence: ERROR > DIVERGENT > EQUIVALENT_UNDER_BUDGET > UNPROVEN) |
| `base_deps` / `head_deps` | str | lockfile fingerprint per side (`no-lockfile` when absent); a mismatch is surfaced in every renderer — dependency-induced divergence is a finding, not noise |
| `budget_max_inputs` | int | per-target input budget the run used |

## targets.json (TargetRecord[])

| field | type |
|---|---|
| `file_path`, `module`, `qualname` | str |
| `lang` | `PYTHON \| TYPESCRIPT` |
| `classification` | `PURE_CANDIDATE \| IMPURE_RECORDABLE \| UNREACHABLE` |
| `verdict` | `DIVERGENT \| EQUIVALENT_UNDER_BUDGET \| UNPROVEN \| ERROR` |
| `reason_code` | ReasonCode \| null — required when UNPROVEN |
| `reason_detail` | str \| null — always actionable prose |
| `inputs_run`, `equivalent_inputs`, `unprovable_inputs` | int |
| `changed_line_coverage` | float 0..1 — fraction of the symbol's changed lines actually executed |
| `divergences` | DivergenceRecord[] |

### DivergenceRecord

| field | type |
|---|---|
| `divergence_class` | one of the nine `DivergenceClass` values |
| `severity` | `LOW \| NORMAL \| HEADLINE` |
| `detail` | str |
| `args_literal`, `kwargs_literal` | str — the first observed diverging input (extended literal transport: Python literals + `nan`/`inf`) |
| `minimized_args`, `minimized_kwargs` | str — **required**; the writer refuses bundles without them |
| `shrink_path` | str[] — the accepted reduction steps |
| `base_summary`, `head_summary` | str — human-readable observed behavior per side |
| `repro_filename` | str — **required**; must exist under `repros/` |

## Integrity rules (enforced in `write_bundle`, mirrored as DB constraints in Phase 4)

1. Every divergence has a minimized input and a repro script, or the bundle is not written.
2. Every referenced `repro_filename` exists in the bundle.
3. Readers reject `schema_version` newer than they understand.
