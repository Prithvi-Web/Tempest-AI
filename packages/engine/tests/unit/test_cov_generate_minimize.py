"""Value-pool fallbacks for annotations with no curated edges, the minimizer's behavior on an
irreducible input (every shrink loses the divergence → the original survives untouched), and
adapter cache-key hashing across real src/package layouts."""

import hashlib
from pathlib import Path

from tempest.compare.canonical import parse_input_literal
from tempest.compare.compare import Diverged
from tempest.generate.strategies import parse_annotation, values_for
from tempest.harness.synth import _file_hash
from tempest.minimize.ddmin import minimize_input
from tempest.model import DivergenceClass, Severity


class TestValuePoolFallbacks:
    def test_bare_annotation_without_edges_still_serves_mined_values(self) -> None:
        ann = parse_annotation("Any")
        assert ann is object
        pool = values_for(ann, seed=0, mined=[3, "probe"])
        assert 3 in pool and "probe" in pool
        for value in pool:  # the transport invariant: every value survives repr → parse
            assert parse_input_literal(repr(value)) == value

    def test_dict_with_wrong_arity_still_yields_transportable_dicts(self) -> None:
        # dict[str] has no curated edge-case entry (wrong arity), so the pool comes purely
        # from type-derived generation — and must still uphold the transport invariant.
        ann = parse_annotation("dict[str]")
        assert ann is not None
        pool = values_for(ann, seed=0, mined=[])
        assert pool, "a malformed dict annotation must not silence generation entirely"
        for value in pool:
            assert isinstance(value, dict)
            assert parse_input_literal(repr(value)) == value


class TestIrreducibleInput:
    def test_input_where_every_shrink_loses_the_divergence_is_kept(self) -> None:
        original_args = "(1, b'', b'x', {}, set(), None)"

        def rerun(args_literal: str, kwargs_literal: str) -> Diverged | None:
            # Real decision procedure: only the exact original input diverges; every
            # structurally smaller candidate the minimizer proposes does not.
            if (args_literal, kwargs_literal) == (original_args, "{}"):
                return Diverged(DivergenceClass.RETURN_VALUE, Severity.NORMAL, "differs")
            return None

        result = minimize_input(rerun, original_args, "{}")
        assert result is not None
        assert result.args_literal == original_args, "a failed shrink must never be accepted"
        assert result.kwargs_literal == "{}"
        assert result.shrink_path == ()
        assert result.attempts_used > 1, "the shrink candidates were really tried"


class TestAdapterFileHash:
    def test_module_resolved_under_src_layout(self, tmp_path: Path) -> None:
        mod = tmp_path / "src" / "pkg" / "mod.py"
        mod.parent.mkdir(parents=True)
        mod.write_text("X = 1\n")
        expected = hashlib.sha256(mod.read_bytes()).hexdigest()[:16]
        assert _file_hash(tmp_path, "pkg.mod") == expected

    def test_package_init_is_the_hashed_file(self, tmp_path: Path) -> None:
        init = tmp_path / "pkg" / "__init__.py"
        init.parent.mkdir()
        init.write_text("Y = 2\n")
        expected = hashlib.sha256(init.read_bytes()).hexdigest()[:16]
        assert _file_hash(tmp_path, "pkg") == expected

    def test_unresolvable_module_hashes_as_missing(self, tmp_path: Path) -> None:
        assert _file_hash(tmp_path, "nowhere.at.all") == "missing-file"
