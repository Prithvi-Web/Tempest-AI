"""Phase 19.1 gate pins: `python -m tempest.dev.license_check --third-party-notices`.

The gate exists because attribution maintained by discipline alone is the weaker guarantee
(v2 failure mode 10 — missing notices surface during enterprise procurement diligence, the
worst possible moment). Every check below is proven to FAIL on a tree that violates it, not
merely to pass on the real one: a gate that cannot fail is decoration.
"""

import shutil
from pathlib import Path

import pytest

from tempest.dev import license_check


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal repo tree that PASSES every check, for tests to then break one at a time."""
    (tmp_path / "LICENSE").write_text(
        "MIT License\n\nCopyright (c) 2026 Prithvi Vinay\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        'of this software and associated documentation files (the "Software"), to deal\n'
        "in the Software without restriction, including without limitation the rights\n"
        "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
        "copies of the Software, and to permit persons to whom the Software is\n"
        "furnished to do so, subject to the following conditions:\n\n"
        "The above copyright notice and this permission notice shall be included in all\n"
        "copies or substantial portions of the Software.\n\n"
        'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND\n'
    )
    (tmp_path / "THIRD_PARTY_LICENSES.md").write_text(
        "# Third-Party Licenses\n\n"
        "## LibreChat\n\n"
        "- **Upstream:** https://github.com/danny-avila/LibreChat\n"
        "- **License:** MIT\n"
        "- **Adoption status:** REFERENCE ONLY\n\n"
        "| Tempest module | Derived from | Notes |\n"
        "|---|---|---|\n"
        "| *(none)* | — | reference-only |\n\n"
        "```\nMIT License\n\nCopyright (c) 2026 LibreChat\n\nPermission is hereby granted\n```\n"
    )
    (tmp_path / "README.md").write_text(
        "# Tempest\n\n## Credits\n\nBuilt on ideas from LibreChat (MIT).\n"
    )
    for rel in ("pyproject.toml", "packages/engine/pyproject.toml"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('[project]\nname = "x"\nlicense = "MIT"\n')
    pkg = tmp_path / "package.json"
    pkg.write_text('{\n  "name": "tempest",\n  "license": "MIT"\n}\n')
    return tmp_path


class TestPassingTree:
    def test_a_complete_tree_passes(self, tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 0
        assert "zero missing notices" in capsys.readouterr().out


class TestOwnLicense:
    def test_missing_license_file_fails(self, tree: Path) -> None:
        (tree / "LICENSE").unlink()
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1

    def test_non_mit_license_fails(self, tree: Path) -> None:
        (tree / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE\nVersion 3\n")
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1

    def test_license_without_a_copyright_holder_fails(self, tree: Path) -> None:
        """An MIT text with no `Copyright (c) <year> <holder>` grants nothing to anyone."""
        body = (tree / "LICENSE").read_text().replace("Copyright (c) 2026 Prithvi Vinay", "")
        (tree / "LICENSE").write_text(body)
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1

    def test_license_missing_the_permission_grant_fails(self, tree: Path) -> None:
        body = (tree / "LICENSE").read_text().replace("Permission is hereby granted", "")
        (tree / "LICENSE").write_text(body)
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1


class TestPackageMetadata:
    """A wheel whose metadata omits the license ships unlicensed to PyPI consumers."""

    def test_pyproject_without_mit_fails(self, tree: Path) -> None:
        (tree / "packages/engine/pyproject.toml").write_text('[project]\nname = "x"\n')
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1

    def test_package_json_without_mit_fails(self, tree: Path) -> None:
        (tree / "package.json").write_text('{\n  "name": "tempest"\n}\n')
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1


class TestThirdPartyNotices:
    def test_missing_notices_file_fails(self, tree: Path) -> None:
        (tree / "THIRD_PARTY_LICENSES.md").unlink()
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1

    def test_a_named_project_without_reproduced_license_text_fails(self, tree: Path) -> None:
        """Naming a dependency without reproducing its license is the MIT obligation missed."""
        body = (tree / "THIRD_PARTY_LICENSES.md").read_text()
        body = body.split("```")[0]
        (tree / "THIRD_PARTY_LICENSES.md").write_text(body)
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1

    def test_code_derived_with_an_empty_derivation_table_fails(self, tree: Path) -> None:
        """CODE DERIVED is a claim; the table naming the modules is the fact behind it."""
        body = (tree / "THIRD_PARTY_LICENSES.md").read_text()
        body = body.replace("REFERENCE ONLY", "CODE DERIVED")
        (tree / "THIRD_PARTY_LICENSES.md").write_text(body)
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1

    def test_code_derived_with_a_real_derivation_row_passes(self, tree: Path) -> None:
        body = (tree / "THIRD_PARTY_LICENSES.md").read_text()
        body = body.replace("REFERENCE ONLY", "CODE DERIVED").replace(
            "| *(none)* | — | reference-only |",
            "| `packages/desktop/src-tauri/src/providers/mod.rs` "
            "| `api/server/services/Endpoints` @ `a1b2c3d` | endpoint schema shape |",
        )
        (tree / "THIRD_PARTY_LICENSES.md").write_text(body)
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 0

    def test_missing_attribution_in_readme_fails(self, tree: Path) -> None:
        """Every project in the notices file must be credited where users actually look."""
        (tree / "README.md").write_text("# Tempest\n\nNo credits here.\n")
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1

    def test_missing_readme_fails(self, tree: Path) -> None:
        (tree / "README.md").unlink()
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1


class TestRealRepo:
    """The gate must pass on the ACTUAL repository, not only on a fixture."""

    def test_the_real_tree_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        root = Path(__file__).resolve().parents[4]
        assert (root / "THIRD_PARTY_LICENSES.md").is_file(), "test is anchored to the wrong root"
        assert license_check.main(["--third-party-notices", "--root", str(root)]) == 0
        assert "zero missing notices" in capsys.readouterr().out


class TestCli:
    def test_flag_is_required(self) -> None:
        with pytest.raises(SystemExit):
            license_check.main([])

    def test_root_defaults_to_the_repo(self) -> None:
        """No --root means the real repository, so CI invocation needs no path wiring."""
        assert license_check.main(["--third-party-notices"]) == 0

    def test_a_tree_missing_everything_reports_every_failure_not_just_the_first(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert license_check.main(["--third-party-notices", "--root", str(tmp_path)]) == 1
        err = capsys.readouterr().err
        assert "LICENSE" in err and "THIRD_PARTY_LICENSES.md" in err

    def test_a_directory_named_license_is_not_a_license(self, tree: Path) -> None:
        (tree / "LICENSE").unlink()
        (tree / "LICENSE").mkdir()
        assert license_check.main(["--third-party-notices", "--root", str(tree)]) == 1
        shutil.rmtree(tree / "LICENSE")
