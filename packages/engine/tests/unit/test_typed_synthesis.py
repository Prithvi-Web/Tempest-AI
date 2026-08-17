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

    def test_not_a_dataclass_gives_up(self) -> None:
        assert _render_adapter(DC.replace("@dataclass\n", ""), "m", "Box", "total") is None

    def test_unzeroable_field_annotation_gives_up(self) -> None:
        assert _render_adapter(DC.replace("name: str", "name: Widget"), "m", "Box", "total") is None

    def test_union_without_none_gives_up(self) -> None:
        # `int | str` has no mechanically-certain value — neither side is None.
        assert (
            _render_adapter(DC.replace("name: str", "name: int | str"), "m", "Box", "total") is None
        )

    def test_non_dataclass_decorator_does_not_count(self) -> None:
        src = DC.replace("@dataclass", "@register")
        assert _render_adapter(src, "m", "Box", "total") is None

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

    def test_non_dataclass_never_touches_the_sandbox(self, tmp_path: Path) -> None:
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
        assert not list(base.glob("_tempest_typed_adapter_*"))


@pytest.fixture(autouse=True)
def _dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_DEV", "1")
