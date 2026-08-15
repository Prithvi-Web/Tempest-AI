"""Classification honesty edges: a symbol the classifier cannot locate must never be blessed
as pure, from-imports must reach the IO allowlist, and IO through a same-module callee makes
the caller impure. Plus the git-diff failure path over a real (non-)repository."""

from pathlib import Path

import pytest

from tempest.model import TargetClassification
from tempest.targets.diff import DiffError, changed_files
from tempest.targets.symbols import SymbolSpan, classify_symbol, enclosing_symbols


def _span(src: str, line: int) -> SymbolSpan:
    (sym,) = enclosing_symbols(src, {line})
    return sym


class TestUnlocatableSymbol:
    def test_symbol_with_a_stale_span_is_never_provably_pure(self) -> None:
        # A span that matches no def in this source (e.g. drifted between revisions): the
        # classifier must fail closed — impure (recordable), never PURE_CANDIDATE.
        src = "def f():\n    return 1\n"
        stale = SymbolSpan(
            symbol="f",
            span=(5, 9),
            nested=False,
            is_async=False,
            is_generator=False,
            owner_class=None,
            is_static=False,
            is_classmethod=False,
        )
        classified = classify_symbol(src, stale)
        assert classified.classification is TargetClassification.IMPURE_RECORDABLE


class TestFromImportAliases:
    def test_aliased_from_import_reaching_io_module_is_impure(self) -> None:
        src = "from os.path import join as pj\n\ndef f(x):\n    return pj(x, 'leaf')\n"
        classified = classify_symbol(src, _span(src, 4))
        assert classified.classification is TargetClassification.IMPURE_RECORDABLE

    def test_plain_from_import_reaching_io_module_is_impure(self) -> None:
        src = "from pathlib import Path\n\ndef f(x):\n    return Path(x).name\n"
        classified = classify_symbol(src, _span(src, 4))
        assert classified.classification is TargetClassification.IMPURE_RECORDABLE


class TestTransitiveIo:
    _SRC = (
        "def helper(p):\n"
        "    return open(p).read()\n"
        "\n"
        "def caller(p):\n"
        "    return helper(p)\n"
        "\n"
        "def pure_helper(x):\n"
        "    return x + 1\n"
        "\n"
        "def pure_caller(x):\n"
        "    return pure_helper(x)\n"
    )

    def test_io_through_a_same_module_callee_makes_the_caller_impure(self) -> None:
        classified = classify_symbol(self._SRC, _span(self._SRC, 5))
        assert classified.classification is TargetClassification.IMPURE_RECORDABLE

    def test_pure_call_chain_stays_a_pure_candidate(self) -> None:
        # The contrast case: the transitive scan must not mark every call impure.
        classified = classify_symbol(self._SRC, _span(self._SRC, 11))
        assert classified.classification is TargetClassification.PURE_CANDIDATE


class TestDiffFailure:
    def test_git_diff_failure_raises_diff_error_with_stderr(self, tmp_path: Path) -> None:
        with pytest.raises(DiffError, match="git diff failed"):
            changed_files(tmp_path, "base", "head")  # tmp_path is not a git repository
