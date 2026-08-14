"""The CI comment renderer: byte-exact GFM (golden), honest headlines for every verdict shape,
and the `tempest ci-comment` CLI end-to-end on a bundle written to disk.

Deterministic output is the contract: the same bundle must render the same bytes, because CI
diffs and updates a single PR comment in place."""

import re
from dataclasses import replace
from pathlib import Path

from typer.testing import CliRunner

from tempest.bundle.bundle import RunBundle, write_bundle
from tempest.cli.ci_comment import COMMENT_MARKER, render_ci_comment
from tempest.cli.main import app
from tempest.model import Severity, Verdict

from .test_bundle import _bundle, _divergence, _target, _unproven_target

runner = CliRunner()

GOLDEN_DIVERGENT = """\
<!-- tempest-report -->
## Tempest verdict: `DIVERGENT`

1 divergence(s) across 1 target(s). Here they are. Here is the smallest one.

`pyfix` · `aaaaaaaaaaaa..bbbbbbbbbbbb` · engine 0.1.0 · budget 300 inputs/target

| target | classification | verdict | inputs | changed-line cov | divergences |
| --- | --- | --- | ---: | ---: | ---: |
| `m.clamp` | PURE_CANDIDATE | **DIVERGENT** | 42 | 100% | 1 |
| `n.closure.inner` | UNREACHABLE | UNPROVEN | 0 | 0% | 0 |

### Divergence 1 — `m.clamp` · RETURN_VALUE

return values differ

Minimized input:

```python
args:   (0,)
kwargs: {}
```

Found via `args (-7,) · kwargs {}`, shrunk in 1 step(s).

| revision | observed |
| --- | --- |
| base (`aaaaaaaaaaaa`) | returned 0 |
| head (`bbbbbbbbbbbb`) | returned 1 |

<details>
<summary>Reproduction script — <code>repros/clamp_0.py</code></summary>

```python
#!/usr/bin/env python3
print('repro')
```

</details>

### ⚠ Not proven — 1 target(s) were NOT exercised

Nothing below is blessed. Every row is a claim Tempest refused to make; each reason is actionable.

| target | reason code | what blocked it |
| --- | --- | --- |
| `n.closure.inner` | `TARGET_UNREACHABLE` | `inner` is a closure |

---

Every claim above is backed by the run bundle: minimized inputs, captured observations, and \
standalone repro scripts under `repros/`. Download the workflow's run-bundle artifact to replay \
them.
"""


class TestGolden:
    def test_divergent_bundle_renders_exactly(self) -> None:
        assert render_ci_comment(_bundle()) == GOLDEN_DIVERGENT

    def test_rendering_is_deterministic_across_a_disk_round_trip(self, tmp_path: Path) -> None:
        bundle = _bundle()
        write_bundle(bundle, tmp_path / "run1")
        from tempest.bundle.bundle import read_bundle

        assert render_ci_comment(read_bundle(tmp_path / "run1")) == render_ci_comment(bundle)

    def test_comment_starts_with_the_update_marker(self) -> None:
        assert render_ci_comment(_bundle()).startswith(COMMENT_MARKER + "\n")


class TestVerdictShapes:
    def test_equivalent_bundle_states_the_caveat(self) -> None:
        base = _bundle()
        bundle = RunBundle(
            manifest=replace(base.manifest, verdict=Verdict.EQUIVALENT_UNDER_BUDGET),
            targets=(_target(()),),
            repro_scripts={},
        )
        out = render_ci_comment(bundle)
        assert "`EQUIVALENT_UNDER_BUDGET`" in out
        assert "This is not “correct” — it is what was exercised." in out
        assert "### Divergence" not in out
        assert "Not proven" not in out

    def test_all_unproven_bundle_blesses_nothing_and_lists_reasons(self) -> None:
        base = _bundle()
        bundle = RunBundle(
            manifest=replace(base.manifest, verdict=Verdict.UNPROVEN),
            targets=(_unproven_target(),),
            repro_scripts={},
        )
        out = render_ci_comment(bundle)
        assert "Nothing could be exercised. Nothing is blessed." in out
        assert "### ⚠ Not proven — 1 target(s) were NOT exercised" in out
        assert "`TARGET_UNREACHABLE`" in out
        assert "`inner` is a closure" in out

    def test_error_bundle_owns_the_failure(self) -> None:
        base = _bundle()
        errored = replace(
            _unproven_target(),
            verdict=Verdict.ERROR,
            reason_code=None,
            reason_detail="worker crashed: SIGKILL",
        )
        bundle = RunBundle(
            manifest=replace(base.manifest, verdict=Verdict.ERROR),
            targets=(errored,),
            repro_scripts={},
        )
        out = render_ci_comment(bundle)
        assert "Tempest itself failed — see the internal trace." in out
        assert "### Tempest error — 1 target(s)" in out
        assert "worker crashed: SIGKILL" in out
        assert "not a statement about the change" in out

    def test_empty_bundle_admits_nothing_was_found(self) -> None:
        base = _bundle()
        bundle = RunBundle(
            manifest=replace(base.manifest, verdict=Verdict.UNPROVEN),
            targets=(),
            repro_scripts={},
        )
        out = render_ci_comment(bundle)
        assert "No differential targets were found" in out
        assert "nothing is blessed" in out

    def test_dependency_mismatch_is_surfaced(self) -> None:
        base = _bundle()
        bundle = RunBundle(
            manifest=replace(base.manifest, head_deps="uv.lock:deadbeef"),
            targets=base.targets,
            repro_scripts=base.repro_scripts,
        )
        out = render_ci_comment(bundle)
        assert "Dependencies changed between revisions" in out
        assert "a real finding, not noise" in out

    def test_low_severity_divergence_is_annotated(self) -> None:
        base = _bundle()
        low = replace(_divergence(), severity=Severity.LOW)
        bundle = RunBundle(
            manifest=base.manifest, targets=(_target((low,)),), repro_scripts=base.repro_scripts
        )
        assert "(low severity)" in render_ci_comment(bundle)

    def test_table_cells_survive_pipes_and_newlines_in_prose(self) -> None:
        base = _bundle()
        spiky = replace(_unproven_target(), reason_detail="uses `a | b`\nacross two lines")
        bundle = RunBundle(
            manifest=replace(base.manifest, verdict=Verdict.UNPROVEN),
            targets=(spiky,),
            repro_scripts={},
        )
        out = render_ci_comment(bundle)
        assert "uses `a \\| b`<br>across two lines" in out


class TestLawL2:
    def test_the_forbidden_word_never_appears(self) -> None:
        shapes = [_bundle()]
        base = _bundle()
        for verdict in Verdict:
            shapes.append(
                RunBundle(
                    manifest=replace(base.manifest, verdict=verdict),
                    targets=base.targets,
                    repro_scripts=base.repro_scripts,
                )
            )
        for bundle in shapes:
            assert not re.search(r"\bSAFE\b", render_ci_comment(bundle))


class TestCliEndToEnd:
    def test_ci_comment_renders_a_bundle_from_disk(self, tmp_path: Path) -> None:
        bundle = _bundle()
        write_bundle(bundle, tmp_path / "run1")
        result = runner.invoke(app, ["ci-comment", "--bundle", str(tmp_path / "run1")])
        assert result.exit_code == 0, result.output
        assert result.output == GOLDEN_DIVERGENT

    def test_missing_bundle_dir_is_an_actionable_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["ci-comment", "--bundle", str(tmp_path / "nope")])
        assert result.exit_code == 2
        assert "not a run bundle" in result.stderr
        assert "manifest.json" in result.stderr
