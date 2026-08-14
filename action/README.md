# Tempest AI — GitHub Action

Runs `tempest prove` on a pull request: executes the base and head revisions side by side under
identical, deterministic conditions and reports concrete inputs where observable behavior
diverges — each with a minimized input and a standalone repro script. The output is evidence,
not opinion.

## Check policy (Law L2 — honest verdicts)

| Verdict | Check | Surface |
|---|---|---|
| `DIVERGENT` | **fails** | error annotation + PR comment with minimized inputs and repro scripts |
| `ERROR` | **fails** | Tempest's own failure — never blamed on the change |
| `UNPROVEN` | passes, **loudly** | one `::warning` annotation per unexercised target, with its machine-readable reason code |
| `EQUIVALENT_UNDER_BUDGET` | passes | the wording states what was exercised; it never claims the change is "correct" |

`UNPROVEN` is deliberately not a failure: Tempest refusing to bless a change it could not run is
the honest outcome, not a broken build. It is also deliberately impossible to miss.

## Usage

```yaml
name: tempest
on:
  pull_request:

permissions:
  contents: read
  pull-requests: write   # for the PR comment

jobs:
  prove:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0            # tempest materializes the base ref locally
      - uses: OWNER/tempest/action@main
        with:
          base: ${{ github.event.pull_request.base.sha }}
          head: ${{ github.event.pull_request.head.sha }}
```

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `base` | (required) | Base (pre-change) git ref |
| `head` | `HEAD` | Head (post-change) git ref |
| `max-inputs` | *(empty)* | Per-target input budget. Empty → 300, or `[budgets].max_inputs` from `tempest.toml` |
| `float-tolerance` | *(empty)* | Opt-in relative float tolerance. Empty → exact comparison, or `[compare].float_rel_tol` from `tempest.toml` |
| `repo` | workspace | Path to the repository under test |
| `comment` | `true` | Post/update the PR comment (`false`: only generate it) |
| `build-sandbox-image` | `true` | Build the `tempest-sandbox` Docker image before proving |
| `artifact-name` | `tempest-run-bundle` | Name of the uploaded run-bundle artifact |
| `github-token` | `github.token` | Token for the PR comment (`pull-requests: write`) |

Precedence everywhere: **workflow input > `tempest.toml` > built-in default.**

## Outputs

| Output | Meaning |
|---|---|
| `verdict` | `DIVERGENT` \| `EQUIVALENT_UNDER_BUDGET` \| `UNPROVEN` \| `ERROR` |
| `bundle-path` | Run-bundle directory (`manifest.json`, `targets.json`, `repros/`) |
| `comment-path` | The generated GitHub-flavored-markdown comment |

## `tempest.toml` (optional, at the repo root)

```toml
[budgets]
max_inputs = 300          # per-target input budget
max_wall_seconds = 30.0   # per-target wall-clock budget

[compare]
float_rel_tol = 1e-9      # opt-in; default is exact comparison

[ignore]
globs = ["generated/*", "*_pb2.py"]   # changed files to exclude from the diff walk
                                      # (case-sensitive fnmatch; `*` crosses `/`)
```

Unknown keys fail the run immediately with a message listing every offender and the valid
vocabulary — a silently ignored typo would bless the wrong run.

## The PR comment

One comment per PR, updated in place on every run (found via the `<!-- tempest-report -->`
marker on its first line). It contains the verdict headline, a per-target table, every
divergence with its minimized input and a collapsible repro script, and a prominent
**Not proven** section listing each unexercised target with its reason code.

## The run bundle artifact

Every run — pass or fail — uploads the self-contained bundle (Law L7): `manifest.json`,
`targets.json`, standalone scripts under `repros/`, and the transport zip. A divergence you
cannot re-run yourself is worthless; download the artifact and run any repro script directly.

## Sandboxing

User-repo code executes only inside the `tempest-sandbox` Docker container (no network,
read-only rootfs, memory/pids limits, non-root, seccomp). If Docker is unavailable the run does
not fall back to unsandboxed execution: affected targets report
`UNPROVEN(SANDBOX_UNAVAILABLE)` (ADR-0003). Repos carrying Tempest's own first-party fixture
marker use the in-process sandbox when `TEMPEST_DEV=1` is set (ADR-0008) — that path exists for
Tempest's self-test, not for user repos.
