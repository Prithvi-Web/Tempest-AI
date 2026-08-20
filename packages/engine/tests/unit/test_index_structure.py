"""The structural index: what a symbol is, where it lives, and who calls whom (Phase 22).

States enumerated before the tests (trap 43): a module of plain functions · classes with methods ·
async functions · decorated functions · nested functions · a file that does not parse · a file
that is not valid UTF-8 · an ignored file · a file that changed · a file that did not change · a
file that was deleted · two symbols sharing a name · a call to something not indexed.
"""

from __future__ import annotations

from pathlib import Path

from tempest.index import structure
from tempest.index.store import index_for, symbol_rows


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Paths are written literally — no clever encoding of `/` as `__`, which is how a fixture
    ends up building something other than what it claims (see `test_module_load_probe`)."""
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


class TestParsing:
    def test_top_level_functions_classes_and_methods_are_symbols(self) -> None:
        source = (
            "def total(xs):\n"
            '    """Adds."""\n'
            "    return sum(xs)\n\n\n"
            "class Money:\n"
            '    """A money value."""\n\n'
            "    def cents(self):\n"
            "        return 1\n"
        )
        parsed = {p.qualname: p for p in structure.parse_symbols(source, "m")}
        assert set(parsed) == {"total", "Money", "Money.cents"}
        assert parsed["total"].kind == "function"
        assert parsed["Money"].kind == "class"
        assert parsed["Money.cents"].kind == "method"
        assert parsed["total"].doc == "Adds."
        assert parsed["total"].signature == "(xs)"

    def test_an_async_function_says_so(self) -> None:
        parsed = structure.parse_symbols("async def fetch(url):\n    return url\n", "m")
        assert parsed[0].kind == "async function"

    def test_a_decorated_function_spans_its_decorators(self) -> None:
        """The span is the citation. A span starting below the decorator points a reader at the
        second line of the thing they asked about."""
        source = "import functools\n\n\n@functools.cache\ndef total(xs):\n    return sum(xs)\n"
        parsed = structure.parse_symbols(source, "m")
        assert parsed[0].line_start == 4

    def test_a_nested_function_is_not_its_own_symbol_but_its_calls_count(self) -> None:
        """Nested defs are not importable and the engine cannot target them, so offering them as
        answers would offer something nothing else in the product can act on."""
        source = "def outer(xs):\n    def inner(y):\n        return helper(y)\n    return inner\n"
        parsed = structure.parse_symbols(source, "m")
        assert [p.qualname for p in parsed] == ["outer"]
        assert "helper" in {name for name, _line in parsed[0].calls}

    def test_a_file_that_does_not_parse_yields_nothing_rather_than_raising(self) -> None:
        assert structure.parse_symbols("def broken(:\n", "m") == []

    def test_attribute_calls_are_recorded_by_their_final_name(self) -> None:
        source = "def go(client):\n    return client.charge(1)\n"
        parsed = structure.parse_symbols(source, "m")
        assert ("charge", 2) in parsed[0].calls


class TestBuilding:
    def test_symbols_calls_and_spans_land_in_the_store(self, tmp_path: Path) -> None:
        root = _repo(
            tmp_path,
            {
                "money.py": "def parse(text):\n    return int(text)\n",
                "charge.py": "def charge(text):\n    return parse(text)\n",
            },
        )
        with index_for(root) as conn:
            stats = structure.build(conn, root)
            assert stats.symbols == 2
            rows = {r.qualname: r for r in symbol_rows(conn)}
            assert rows["parse"].path == "money.py"
            assert rows["charge"].span == "charge.py:1-2"
            resolved = conn.execute(
                "SELECT callee, callee_id FROM calls WHERE caller_id = ?", (rows["charge"].id,)
            ).fetchall()
            assert resolved == [("parse", rows["parse"].id)]

    def test_an_unchanged_file_is_not_reparsed(self, tmp_path: Path) -> None:
        """The whole reason a repository-sized index is affordable. Hashing beats parsing by
        orders of magnitude, and Phase 26's on-save re-index depends on it."""
        root = _repo(tmp_path, {"a.py": "def f():\n    return 1\n"})
        with index_for(root) as conn:
            assert structure.build(conn, root).files_reparsed == 1
            assert structure.build(conn, root).files_reparsed == 0

    def test_a_changed_file_is_reparsed_and_its_old_symbols_go(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"a.py": "def old():\n    return 1\n"})
        with index_for(root) as conn:
            structure.build(conn, root)
            (root / "a.py").write_text("def new():\n    return 2\n", encoding="utf-8")
            stats = structure.build(conn, root)
            assert stats.files_reparsed == 1
            assert [r.qualname for r in symbol_rows(conn)] == ["new"]

    def test_a_deleted_file_takes_its_symbols_with_it(self, tmp_path: Path) -> None:
        """An index that remembers deleted code answers "where is this defined?" with a path that
        does not exist — which is worse than not answering."""
        root = _repo(
            tmp_path, {"a.py": "def f():\n    return 1\n", "b.py": "def g():\n    return 2\n"}
        )
        with index_for(root) as conn:
            structure.build(conn, root)
            (root / "b.py").unlink()
            structure.build(conn, root)
            assert [r.qualname for r in symbol_rows(conn)] == ["f"]

    def test_a_file_that_cannot_be_read_is_reported_not_skipped(self, tmp_path: Path) -> None:
        """A symbol silently missing from the index makes every "never exercised" answer quietly
        wrong, which is the one failure mode this feature must not have."""
        root = _repo(tmp_path, {"a.py": "def f():\n    return 1\n"})
        (root / "bad.py").write_bytes(b"\xff\xfe\x00 def f():")
        with index_for(root) as conn:
            stats = structure.build(conn, root)
            assert stats.unreadable == ("bad.py",)

    def test_an_ignored_path_is_not_indexed(self, tmp_path: Path) -> None:
        root = _repo(
            tmp_path,
            {"a.py": "def f():\n    return 1\n", "vendor/b.py": "def g():\n    return 2\n"},
        )
        (root / "tempest.toml").write_text('[ignore]\nglobs = ["vendor/*"]\n', encoding="utf-8")
        with index_for(root) as conn:
            structure.build(conn, root)
            assert [r.qualname for r in symbol_rows(conn)] == ["f"]

    def test_the_index_never_indexes_its_own_directory(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"a.py": "def f():\n    return 1\n"})
        (root / ".tempest").mkdir(exist_ok=True)
        (root / ".tempest" / "junk.py").write_text(
            "def hidden():\n    return 1\n", encoding="utf-8"
        )
        with index_for(root) as conn:
            structure.build(conn, root)
            assert [r.qualname for r in symbol_rows(conn)] == ["f"]

    def test_an_ambiguous_callee_is_left_unresolved_rather_than_guessed(
        self, tmp_path: Path
    ) -> None:
        """Two functions named `run` make `run(...)` genuinely undecidable from the call site. A
        call graph that picks one will eventually tell somebody their function has a caller it
        does not have."""
        root = _repo(
            tmp_path,
            {
                "a.py": "def run():\n    return 1\n",
                "b.py": "def run():\n    return 2\n",
                "c.py": "def go():\n    return run()\n",
            },
        )
        with index_for(root) as conn:
            structure.build(conn, root)
            rows = conn.execute("SELECT callee, callee_id FROM calls").fetchall()
            assert rows == [("run", None)]

    def test_a_call_to_something_outside_the_index_keeps_its_name(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"a.py": "def f(xs):\n    return sorted(xs)\n"})
        with index_for(root) as conn:
            structure.build(conn, root)
            assert conn.execute("SELECT callee, callee_id FROM calls").fetchall() == [
                ("sorted", None)
            ]


class TestFileSelection:
    def test_a_repo_with_an_unreadable_config_still_indexes(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"a.py": "def f():\n    return 1\n"})
        (root / "tempest.toml").write_text("not [ valid toml", encoding="utf-8")
        assert [p.name for p in structure.python_files(root)] == ["a.py"]

    def test_pycache_is_never_a_source_of_symbols(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"a.py": "def f():\n    return 1\n"})
        cache = root / "__pycache__"
        cache.mkdir()
        (cache / "a.py").write_text("def ghost():\n    return 1\n", encoding="utf-8")
        assert [p.name for p in structure.python_files(root)] == ["a.py"]


class TestDigest:
    def test_identical_text_hashes_identically_and_different_text_does_not(self) -> None:
        assert structure.digest_of("a") == structure.digest_of("a")
        assert structure.digest_of("a") != structure.digest_of("b")
