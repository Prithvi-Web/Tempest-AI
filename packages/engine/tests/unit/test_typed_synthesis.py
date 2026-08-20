"""harness/typed.py — the deterministic constructor rung, every give-up arm pinned.

The synthesizer must construct ONLY what is mechanically certain from the AST and hand
everything else to the next rung (None), because a wrong guess that survives would be a
fabricated harness. The give-up arms ARE the honesty surface here.
"""

from pathlib import Path

import pytest

from tempest.execute.sandbox import ProcessSandbox
from tempest.harness.llm import InstanceAdapter
from tempest.harness.typed import _render_adapter, synthesize_dataclass_adapter

DC = (
    "from dataclasses import dataclass\n"
    "\n"
    "@dataclass\n"
    "class Box:\n"
    "    fee: int\n"
    "    name: str\n"
    "    def total(self, xs: list[int]) -> int:\n"
    "        return sum(xs) + self.fee\n"
)


class TestRenderAdapter:
    def test_defaultless_fields_get_zero_values(self) -> None:
        code = _render_adapter(DC, "m", "Box", "total")
        assert code is not None
        assert "Box(fee=0, name='')" in code
        assert "def adapter(xs: list[int]):" in code

    def test_all_defaults_construct_bare(self) -> None:
        src = DC.replace("fee: int", "fee: int = 3").replace("name: str", "name: str = 'x'")
        code = _render_adapter(src, "m", "Box", "total")
        assert code is not None
        assert "Box().total(xs)" in code

    def test_optional_field_gets_none(self) -> None:
        src = DC.replace("name: str", "name: str | None")
        code = _render_adapter(src, "m", "Box", "total")
        assert code is not None
        assert "name=None" in code

    def test_subscripted_container_field_gets_empty(self) -> None:
        src = DC.replace("name: str", "name: dict[str, int]")
        code = _render_adapter(src, "m", "Box", "total")
        assert code is not None
        assert "name={}" in code

    def test_a_bare_class_body_now_renders_but_cannot_survive_the_probe(self) -> None:
        """CHANGED BY PHASE 19a, deliberately — this test used to assert `is None`.

        Stripping `@dataclass` from `DC` leaves a class whose `fee: int` / `name: str` are bare
        ANNOTATIONS: they create no attributes and no constructor parameters. There is no
        `__init__`, so the plain arm renders `Box()`, which is correct — `Box()` really is a
        legal call. What is not legal is `self.fee` afterwards, and that is a fact about
        EXECUTION, not about the AST.

        So the rung's answer is still "no adapter", reached by the probe instead of by a guess
        about the decorator. `TestPlainClassExecutionValidation` covers the end-to-end result;
        this asserts the split, because a render that silently returned None here would mean the
        plain arm was never entered.
        """
        code = _render_adapter(DC.replace("@dataclass\n", ""), "m", "Box", "total")
        assert code is not None
        assert "Box()." in code, "no __init__ and no dataclass fields -> a bare construction"

    def test_unzeroable_field_annotation_gives_up(self) -> None:
        assert _render_adapter(DC.replace("name: str", "name: Widget"), "m", "Box", "total") is None

    def test_union_without_none_gives_up(self) -> None:
        # `int | str` has no mechanically-certain value — neither side is None.
        assert (
            _render_adapter(DC.replace("name: str", "name: int | str"), "m", "Box", "total") is None
        )

    def test_non_dataclass_decorator_does_not_count(self) -> None:
        """An unrelated decorator must not be read as `@dataclass` — the FIELD path is still
        gated on the real decorator.

        Phase 19a changed what happens next: instead of giving up, the class falls to the plain
        arm and constructs bare. The property this test exists for is unchanged and is asserted
        directly — `@register` must never produce a field-derived constructor.
        """
        src = DC.replace("@dataclass", "@register")
        code = _render_adapter(src, "m", "Box", "total")
        assert code is not None
        assert "fee=0" not in code, "@register is not @dataclass; fields must not be read"
        assert "Box()." in code

    def test_dotted_annotation_gives_up(self) -> None:
        # `widgets.Widget` is neither a bare name, a subscripted builtin, nor a union —
        # nothing mechanical to construct.
        src = DC.replace("name: str", "name: widgets.Widget")
        assert _render_adapter(src, "m", "Box", "total") is None

    def test_missing_class_or_method_gives_up(self) -> None:
        assert _render_adapter(DC, "m", "Crate", "total") is None
        assert _render_adapter(DC, "m", "Box", "shrink") is None

    def test_unannotated_method_param_gives_up(self) -> None:
        assert _render_adapter(DC.replace("xs: list[int]", "xs"), "m", "Box", "total") is None

    def test_starargs_give_up(self) -> None:
        src = DC.replace("def total(self, xs: list[int])", "def total(self, *xs: int)")
        assert _render_adapter(src, "m", "Box", "total") is None

    def test_unparseable_source_gives_up(self) -> None:
        assert _render_adapter("def broken(:", "m", "Box", "total") is None

    def test_decorator_call_form_and_attribute_form_count(self) -> None:
        for deco in ("@dataclass(frozen=True)", "@dataclasses.dataclass"):
            src = DC.replace("@dataclass", deco)
            assert _render_adapter(src, "m", "Box", "total") is not None, deco


class TestExecutionValidation:
    def _roots(self, tmp_path: Path, src: str) -> tuple[Path, Path]:
        base, head = tmp_path / "base", tmp_path / "head"
        for root in (base, head):
            root.mkdir()
            (root / "m.py").write_text(src, encoding="utf-8")
        return base, head

    def test_validated_adapter_comes_back(self, tmp_path: Path) -> None:
        base, head = self._roots(tmp_path, DC)
        got = synthesize_dataclass_adapter(
            base_root=base,
            head_root=head,
            module="m",
            owner_class="Box",
            method="total",
            head_source=DC,
            sandbox=ProcessSandbox(),
        )
        assert isinstance(got, InstanceAdapter)
        assert (base / f"{got.module}.py").exists() and (head / f"{got.module}.py").exists()

    def test_post_init_rejecting_zero_values_falls_through(self, tmp_path: Path) -> None:
        src = DC.replace(
            "    def total",
            "    def __post_init__(self) -> None:\n"
            "        if self.fee == 0:\n"
            "            raise ValueError('fee required')\n"
            "    def total",
        )
        base, head = self._roots(tmp_path, src)
        got = synthesize_dataclass_adapter(
            base_root=base,
            head_root=head,
            module="m",
            owner_class="Box",
            method="total",
            head_source=src,
            sandbox=ProcessSandbox(),
        )
        assert got is None  # the guess did not fit — the next rung gets its turn

    def test_a_plain_class_now_DOES_reach_the_sandbox_and_is_refused_there(
        self, tmp_path: Path
    ) -> None:
        """CHANGED BY PHASE 19a — this test used to be `test_non_dataclass_never_touches_the
        _sandbox` and asserted no adapter file was ever written.

        Spending a sandbox probe on every plain class is the deliberate cost of the phase: it is
        what turns 112 `TARGET_UNREACHABLE` targets from "needs an API key" into "attempted for
        free". The refusal is still total — no adapter comes back, and nothing is left behind.
        """
        src = DC.replace("@dataclass\n", "")
        base, head = self._roots(tmp_path, src)
        got = synthesize_dataclass_adapter(
            base_root=base,
            head_root=head,
            module="m",
            owner_class="Box",
            method="total",
            head_source=src,
            sandbox=ProcessSandbox(),
        )
        assert got is None
        assert not list(base.glob("_tempest_typed_adapter_*")), "refused attempts leave no litter"


@pytest.fixture(autouse=True)
def _dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_DEV", "1")


# ── Phase 19a: the keyless rung widens from dataclasses to PLAIN classes ──────────────────
#
# Why: `docs/METRICS.md` records 130 UNPROVEN of 198 real-world targets, and **112 of them are
# `TARGET_UNREACHABLE`** — 86% of everything unproven, an order of magnitude above the next
# bucket. Every one is an instance method, and until now every one fell past this rung (which
# only understood `@dataclass`) to the LLM rung, which is key-gated. So the engine-first answer
# to QV1 ran straight into QV2 — who pays — for no reason except that a constructor was never
# attempted. A plain class whose `__init__` is mechanically satisfiable is exactly as
# constructible as a dataclass whose fields are.
#
# The honesty property is unchanged and is what makes this safe: acceptance is EXECUTION on
# BASE in the sandbox, so a wrong guess is refused and falls through to the next rung. Nothing
# is ever blessed by rendering alone.

PLAIN = (
    "class Meter:\n"
    "    def __init__(self, fee: int, name: str = 'x'):\n"
    "        self.fee = fee\n"
    "        self.name = name\n"
    "    def total(self, xs: list[int]) -> int:\n"
    "        return sum(xs) + self.fee\n"
)


class TestPlainClassConstructorDerivation:
    """States enumerated before the tests (trap 43): no `__init__` at all · `__init__(self)` ·
    every parameter defaulted · an annotated defaultless parameter · a mix · an UNANNOTATED
    defaultless parameter · `*args`/`**kwargs` only · an unzeroable annotation · `X | None` ·
    keyword-only · positional-only · an `async def __init__` · inherited `__init__` the AST
    cannot see · a dataclass, which must keep taking the dataclass path unchanged.
    """

    def test_an_annotated_defaultless_parameter_gets_its_zero(self) -> None:
        code = _render_adapter(PLAIN, "m", "Meter", "total")
        assert code is not None
        assert "Meter(fee=0)" in code, "the defaulted `name` is left to its default"
        assert "def adapter(xs: list[int]):" in code

    def test_a_class_with_no_init_at_all_constructs_bare(self) -> None:
        src = "class Meter:\n    def total(self, xs: list[int]) -> int:\n        return sum(xs)\n"
        code = _render_adapter(src, "m", "Meter", "total")
        assert code is not None
        assert "Meter().total(xs)" in code

    def test_an_init_taking_only_self_constructs_bare(self) -> None:
        src = PLAIN.replace("def __init__(self, fee: int, name: str = 'x'):", "def __init__(self):")
        code = _render_adapter(src, "m", "Meter", "total")
        assert code is not None
        assert "Meter()." in code

    def test_every_parameter_defaulted_constructs_bare(self) -> None:
        src = PLAIN.replace("fee: int, name: str = 'x'", "fee: int = 3, name: str = 'x'")
        code = _render_adapter(src, "m", "Meter", "total")
        assert code is not None
        assert "Meter()." in code

    def test_an_unannotated_defaultless_parameter_gives_up(self) -> None:
        """Nothing to go on. This is the give-up arm that keeps the rung honest — the LLM rung
        exists precisely for the cases the AST cannot decide."""
        src = PLAIN.replace("fee: int,", "fee,")
        assert _render_adapter(src, "m", "Meter", "total") is None

    def test_an_unzeroable_annotation_gives_up(self) -> None:
        src = PLAIN.replace("fee: int,", "fee: Widget,")
        assert _render_adapter(src, "m", "Meter", "total") is None

    def test_an_optional_annotation_gets_none(self) -> None:
        src = PLAIN.replace("fee: int,", "fee: int | None,")
        code = _render_adapter(src, "m", "Meter", "total")
        assert code is not None
        assert "Meter(fee=None)" in code

    def test_star_args_and_kwargs_are_simply_omitted(self) -> None:
        """Both are optional by definition, so a bare call satisfies them."""
        src = PLAIN.replace(
            "def __init__(self, fee: int, name: str = 'x'):", "def __init__(self, *args, **kwargs):"
        )
        code = _render_adapter(src, "m", "Meter", "total")
        assert code is not None
        assert "Meter()." in code

    def test_a_keyword_only_defaultless_parameter_is_passed_by_keyword(self) -> None:
        src = PLAIN.replace(
            "def __init__(self, fee: int, name: str = 'x'):", "def __init__(self, *, fee: int):"
        )
        code = _render_adapter(src, "m", "Meter", "total")
        assert code is not None
        assert "Meter(fee=0)" in code

    def test_a_positional_only_parameter_is_passed_positionally(self) -> None:
        """`__init__(self, fee: int, /)` cannot accept `fee=0` — passing it by keyword raises
        TypeError, so the rendered call would fail the probe for a reason that is our bug."""
        src = PLAIN.replace(
            "def __init__(self, fee: int, name: str = 'x'):", "def __init__(self, fee: int, /):"
        )
        code = _render_adapter(src, "m", "Meter", "total")
        assert code is not None
        assert "Meter(0)" in code
        assert "fee=0" not in code

    def test_positional_only_and_keyword_parameters_keep_their_order(self) -> None:
        src = PLAIN.replace(
            "def __init__(self, fee: int, name: str = 'x'):",
            "def __init__(self, fee: int, /, size: int):",
        )
        code = _render_adapter(src, "m", "Meter", "total")
        assert code is not None
        assert "Meter(0, size=0)" in code

    def test_an_async_init_gives_up(self) -> None:
        """`async def __init__` cannot be called to produce an instance."""
        src = PLAIN.replace(
            "    def __init__(self, fee: int, name: str = 'x'):",
            "    async def __init__(self, fee: int, name: str = 'x'):",
        )
        assert _render_adapter(src, "m", "Meter", "total") is None

    def test_a_dataclass_still_takes_the_dataclass_path(self) -> None:
        """No behaviour change for the rows this rung already handled. The dataclass path reads
        FIELDS; the plain path reads `__init__`. A dataclass has no explicit `__init__`, so
        routing it through the plain path would construct `Box()` and lose every field."""
        code = _render_adapter(DC, "m", "Box", "total")
        assert code is not None
        assert "Box(fee=0, name='')" in code

    def test_a_dataclass_with_an_explicit_init_uses_that_init(self) -> None:
        """`@dataclass(init=False)` with a hand-written `__init__` is a real shape: the generated
        constructor does not exist, so reading the fields would be wrong."""
        src = (
            "from dataclasses import dataclass\n"
            "\n"
            "@dataclass(init=False)\n"
            "class Box:\n"
            "    fee: int\n"
            "    name: str\n"
            "    def __init__(self, fee: int = 7):\n"
            "        self.fee = fee\n"
            "        self.name = 'z'\n"
            "    def total(self, xs: list[int]) -> int:\n"
            "        return sum(xs) + self.fee\n"
        )
        code = _render_adapter(src, "m", "Box", "total")
        assert code is not None
        assert "Box()." in code, "every parameter of the explicit __init__ has a default"

    def test_the_method_param_rules_are_unchanged_for_plain_classes(self) -> None:
        """The receiver is a new question; the METHOD's parameters are judged exactly as before."""
        assert _render_adapter(PLAIN.replace("xs: list[int]", "xs"), "m", "Meter", "total") is None
        assert (
            _render_adapter(
                PLAIN.replace("def total(self, xs: list[int])", "def total(self, *xs: int)"),
                "m",
                "Meter",
                "total",
            )
            is None
        )


class TestPlainClassExecutionValidation:
    def _roots(self, tmp_path: Path, src: str) -> tuple[Path, Path]:
        base, head = tmp_path / "base", tmp_path / "head"
        for root in (base, head):
            root.mkdir()
            (root / "m.py").write_text(src, encoding="utf-8")
        return base, head

    def _synth(self, tmp_path: Path, src: str, cls: str = "Meter") -> object:
        base, head = self._roots(tmp_path, src)
        return synthesize_dataclass_adapter(
            base_root=base,
            head_root=head,
            module="m",
            owner_class=cls,
            method="total",
            head_source=src,
            sandbox=ProcessSandbox(),
        )

    def test_a_constructible_plain_class_now_reaches_a_validated_adapter(
        self, tmp_path: Path
    ) -> None:
        """The whole point of the phase: this used to be `UNPROVEN(TARGET_UNREACHABLE)` unless
        the user had configured and paid for an API key."""
        got = self._synth(tmp_path, PLAIN)
        assert isinstance(got, InstanceAdapter)

    def test_an_init_that_rejects_its_zero_values_falls_through(self, tmp_path: Path) -> None:
        """Same shape as the dataclass `__post_init__` case: the guess did not fit, so the next
        rung gets its turn. Refused by EXECUTION, never by reading."""
        src = PLAIN.replace(
            "        self.fee = fee\n",
            "        if fee == 0:\n            raise ValueError('fee required')\n"
            "        self.fee = fee\n",
        )
        assert self._synth(tmp_path, src) is None

    def test_an_inherited_init_the_ast_cannot_see_is_settled_by_the_probe(
        self, tmp_path: Path
    ) -> None:
        """The AST sees no `__init__` on the subclass and renders `Sub()`. Whether that is legal
        depends on a base class in another statement — which is why acceptance is execution."""
        src = (
            "class Base:\n"
            "    def __init__(self, need: int):\n"
            "        self.need = need\n"
            "class Meter(Base):\n"
            "    def total(self, xs: list[int]) -> int:\n"
            "        return sum(xs) + self.need\n"
        )
        assert self._synth(tmp_path, src) is None, "Meter() raises TypeError; the probe catches it"

    def test_a_rejected_guess_leaves_no_adapter_file_behind(self, tmp_path: Path) -> None:
        """Widening this rung means attempting far more classes, most of which will be refused.
        A refused attempt must not leave a module in the base and head worktrees: those trees are
        what the differential runner executes and what coverage is attributed against, and
        `.tempest` shadow worktrees are real git worktrees a user can inspect.
        """
        src = PLAIN.replace(
            "        self.fee = fee\n",
            "        raise ValueError('never constructible')\n",
        )
        base, head = self._roots(tmp_path, src)
        got = synthesize_dataclass_adapter(
            base_root=base,
            head_root=head,
            module="m",
            owner_class="Meter",
            method="total",
            head_source=src,
            sandbox=ProcessSandbox(),
        )
        assert got is None
        assert not list(base.glob("_tempest_typed_adapter_*")), "base worktree polluted"
        assert not list(head.glob("_tempest_typed_adapter_*")), "head worktree polluted"

    def test_an_accepted_adapter_is_kept_because_the_differential_run_needs_it(
        self, tmp_path: Path
    ) -> None:
        base, head = self._roots(tmp_path, PLAIN)
        got = synthesize_dataclass_adapter(
            base_root=base,
            head_root=head,
            module="m",
            owner_class="Meter",
            method="total",
            head_source=PLAIN,
            sandbox=ProcessSandbox(),
        )
        assert isinstance(got, InstanceAdapter)
        assert (base / f"{got.module}.py").exists()
        assert (head / f"{got.module}.py").exists()


class TestKeywordOnlyConstructorParameters:
    """The kw-only arm has its own default/annotation rules, and `kw_defaults` aligns 1:1 with
    `kwonlyargs` rather than right-aligning like `defaults` — a different shape, so a different
    set of states (trap 43). The positional arm's tests say nothing about any of these.
    """

    def _init(self, params: str) -> str:
        return PLAIN.replace(
            "def __init__(self, fee: int, name: str = 'x'):", f"def __init__({params}):"
        )

    def test_a_defaulted_keyword_only_parameter_needs_nothing(self) -> None:
        code = _render_adapter(self._init("self, *, fee: int = 3"), "m", "Meter", "total")
        assert code is not None
        assert "Meter()." in code

    def test_an_unannotated_keyword_only_parameter_gives_up(self) -> None:
        assert _render_adapter(self._init("self, *, fee"), "m", "Meter", "total") is None

    def test_an_unzeroable_keyword_only_annotation_gives_up(self) -> None:
        assert _render_adapter(self._init("self, *, fee: Widget"), "m", "Meter", "total") is None

    def test_a_mix_of_defaulted_and_defaultless_keyword_only_parameters(self) -> None:
        """`kw_defaults` carries None for the ones without a default, in position — reading it as
        a right-aligned list (the rule for positional defaults) would pair the wrong values."""
        code = _render_adapter(
            self._init("self, *, fee: int, scale: int = 2, name: str"), "m", "Meter", "total"
        )
        assert code is not None
        assert "fee=0" in code and "name=''" in code
        assert "scale" not in code, "a defaulted parameter is left to its default"


def test_a_class_that_cannot_be_rendered_never_reaches_the_sandbox(tmp_path: Path) -> None:
    """The cheap give-up. A receiver the AST cannot decide is refused before a probe is spawned —
    widening this rung to every plain class made that path the common one, and paying a sandbox
    spawn per hopeless class would be a real cost on a large repository."""
    src = PLAIN.replace("fee: int,", "fee,")  # unannotated: nothing to derive a value from
    base, head = tmp_path / "base", tmp_path / "head"
    for root in (base, head):
        root.mkdir()
        (root / "m.py").write_text(src, encoding="utf-8")
    got = synthesize_dataclass_adapter(
        base_root=base,
        head_root=head,
        module="m",
        owner_class="Meter",
        method="total",
        head_source=src,
        sandbox=ProcessSandbox(),
    )
    assert got is None
    assert not list(base.glob("_tempest_typed_adapter_*")), "no shim written at all"
    assert not list(head.glob("_tempest_typed_adapter_*"))
