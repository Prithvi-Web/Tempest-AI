"""Stage 1b/1c: symbol extraction from changed lines + purity/reachability classification."""

from tempest.model import ReasonCode, TargetClassification
from tempest.targets.symbols import classify_symbol, enclosing_symbols


class TestEnclosingSymbols:
    def test_changed_line_inside_function_yields_that_function(self) -> None:
        src = "def f(x):\n    return x + 1\n\n\ndef g(y):\n    return y * 2\n"
        syms = enclosing_symbols(src, {2})
        assert [s.symbol for s in syms] == ["f"]
        assert syms[0].span == (1, 2)

    def test_multiple_functions_hit(self) -> None:
        src = "def f(x):\n    return x + 1\n\n\ndef g(y):\n    return y * 2\n"
        assert [s.symbol for s in enclosing_symbols(src, {2, 6})] == ["f", "g"]

    def test_method_symbol_is_dotted(self) -> None:
        src = "class C:\n    def m(self, x):\n        return x\n"
        syms = enclosing_symbols(src, {3})
        assert [s.symbol for s in syms] == ["C.m"]

    def test_decorator_lines_belong_to_the_function(self) -> None:
        src = "def deco(fn):\n    return fn\n\n\n@deco\ndef f(x):\n    return x\n"
        assert "f" in [s.symbol for s in enclosing_symbols(src, {5})]

    def test_module_level_change_yields_no_symbol(self) -> None:
        src = "CONST = 1\n\n\ndef f(x):\n    return x\n"
        assert enclosing_symbols(src, {1}) == []

    def test_nested_function_reports_innermost_with_parent_path(self) -> None:
        src = "def outer():\n    def inner():\n        return 1\n    return inner\n"
        syms = enclosing_symbols(src, {3})
        assert [s.symbol for s in syms] == ["outer.inner"]
        assert syms[0].nested is True

    def test_async_function_found(self) -> None:
        src = "async def af(x):\n    return x\n"
        syms = enclosing_symbols(src, {2})
        assert [s.symbol for s in syms] == ["af"]
        assert syms[0].is_async is True


class TestClassification:
    def _classify(self, src: str, symbol: str) -> tuple[TargetClassification, ReasonCode | None]:
        (sym,) = [
            s
            for s in enclosing_symbols(src, set(range(1, src.count("\n") + 2)))
            if s.symbol == symbol
        ]
        c = classify_symbol(src, sym)
        return c.classification, c.reason_code

    def test_pure_arithmetic_function_is_pure_candidate(self) -> None:
        cls, reason = self._classify("def f(x, y):\n    return x * y + 1\n", "f")
        assert cls is TargetClassification.PURE_CANDIDATE
        assert reason is None

    def test_time_call_is_impure_recordable(self) -> None:
        src = "import time\n\n\ndef f():\n    return time.time()\n"
        cls, _ = self._classify(src, "f")
        assert cls is TargetClassification.IMPURE_RECORDABLE

    def test_open_call_is_impure_recordable(self) -> None:
        src = "def f(p):\n    with open(p) as fh:\n        return fh.read()\n"
        cls, _ = self._classify(src, "f")
        assert cls is TargetClassification.IMPURE_RECORDABLE

    def test_random_module_is_impure_recordable(self) -> None:
        src = "import random\n\n\ndef f():\n    return random.random()\n"
        cls, _ = self._classify(src, "f")
        assert cls is TargetClassification.IMPURE_RECORDABLE

    def test_requests_attribute_chain_is_impure_recordable(self) -> None:
        src = "import requests\n\n\ndef f(u):\n    return requests.get(u).status_code\n"
        cls, _ = self._classify(src, "f")
        assert cls is TargetClassification.IMPURE_RECORDABLE

    def test_global_mutation_is_impure_recordable(self) -> None:
        src = "COUNT = 0\n\n\ndef f():\n    global COUNT\n    COUNT += 1\n    return COUNT\n"
        cls, _ = self._classify(src, "f")
        assert cls is TargetClassification.IMPURE_RECORDABLE

    def test_nested_function_is_unreachable_with_reason(self) -> None:
        src = "def outer():\n    def inner():\n        return 1\n    return inner\n"
        cls, reason = self._classify(src, "outer.inner")
        assert cls is TargetClassification.UNREACHABLE
        assert reason is ReasonCode.TARGET_UNREACHABLE

    def test_instance_method_is_unreachable_in_v1(self) -> None:
        src = "class C:\n    def m(self, x):\n        return x + 1\n"
        cls, reason = self._classify(src, "C.m")
        assert cls is TargetClassification.UNREACHABLE
        assert reason is ReasonCode.TARGET_UNREACHABLE

    def test_staticmethod_is_pure_candidate(self) -> None:
        src = "class C:\n    @staticmethod\n    def s(x):\n        return x + 1\n"
        cls, _ = self._classify(src, "C.s")
        assert cls is TargetClassification.PURE_CANDIDATE

    def test_generator_is_unreachable_in_v1(self) -> None:
        src = "def gen(n):\n    yield n\n"
        cls, reason = self._classify(src, "gen")
        assert cls is TargetClassification.UNREACHABLE
        assert reason is ReasonCode.TARGET_UNREACHABLE

    def test_async_function_is_provable(self) -> None:
        # ADR-0026: the worker awaits coroutine functions via asyncio.run — async targets
        # classify like any other callable instead of the old honest UNREACHABLE.
        src = "async def af(x: int) -> int:\n    return x\n"
        cls, reason = self._classify(src, "af")
        assert cls is TargetClassification.PURE_CANDIDATE
        assert reason is None

    def test_calling_local_pure_helper_stays_pure(self) -> None:
        src = "def helper(x):\n    return x + 1\n\n\ndef f(x):\n    return helper(x) * 2\n"
        cls, _ = self._classify(src, "f")
        assert cls is TargetClassification.PURE_CANDIDATE

    def test_print_stays_pure_candidate_stdout_is_observed(self) -> None:
        src = "def f(x):\n    print(x)\n    return x\n"
        cls, _ = self._classify(src, "f")
        assert cls is TargetClassification.PURE_CANDIDATE

    def test_unreachable_reason_message_is_actionable(self) -> None:
        src = "class C:\n    def m(self, x):\n        return x + 1\n"
        (sym,) = list(enclosing_symbols(src, {3}))
        c = classify_symbol(src, sym)
        assert c.reason_detail is not None
        assert "instance" in c.reason_detail.lower()
