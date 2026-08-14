"""The normalization ruleset (compare/normalize.py) — every rule must have a test proving it
masks the volatile thing AND a test proving it does not mask a known real difference
(master spec §14.6: cassette/message over-normalization hides real divergence)."""

from tempest.compare.normalize import RULES, normalize_message


class TestMemoryAddresses:
    def test_hex_addresses_are_masked(self) -> None:
        a = normalize_message("<Foo object at 0x7f9a2c3d4e50>")
        b = normalize_message("<Foo object at 0x105ab2f90>")
        assert a == b

    def test_different_type_names_still_differ(self) -> None:
        a = normalize_message("<Foo object at 0x7f9a2c3d4e50>")
        b = normalize_message("<Bar object at 0x7f9a2c3d4e50>")
        assert a != b


class TestTempPaths:
    def test_tmp_paths_are_masked(self) -> None:
        a = normalize_message("No such file: /tmp/tmpabc123/data.json")
        b = normalize_message("No such file: /tmp/tmpxyz789/data.json")
        assert a == b

    def test_macos_var_folders_paths_are_masked(self) -> None:
        a = normalize_message("cannot open /var/folders/ab/T/tmp1/x")
        b = normalize_message("cannot open /private/var/folders/zz/T/tmp2/x")
        assert a == b

    def test_ordinary_project_paths_are_not_masked(self) -> None:
        a = normalize_message("No such file: src/app/data.json")
        b = normalize_message("No such file: src/app/other.json")
        assert a != b


class TestTimestamps:
    def test_iso_timestamps_are_masked(self) -> None:
        a = normalize_message("failed at 2026-08-13T19:33:06.123456Z")
        b = normalize_message("failed at 2025-01-01T00:00:00Z")
        assert a == b

    def test_space_separated_datetimes_are_masked(self) -> None:
        a = normalize_message("failed at 2026-08-13 19:33:06")
        b = normalize_message("failed at 2020-02-02 02:02:02")
        assert a == b

    def test_plain_numbers_are_never_masked(self) -> None:
        a = normalize_message("expected 5 rows, got 6")
        b = normalize_message("expected 5 rows, got 7")
        assert a != b

    def test_version_like_numbers_are_not_masked(self) -> None:
        a = normalize_message("requires 2.1.3")
        b = normalize_message("requires 2.1.4")
        assert a != b


class TestRuleset:
    def test_every_rule_is_named_and_documented(self) -> None:
        assert len(RULES) >= 3
        names = [r.name for r in RULES]
        assert len(set(names)) == len(names)
        for rule in RULES:
            assert rule.rationale, f"rule {rule.name} must state why it cannot mask a real diff"

    def test_genuinely_different_messages_survive_normalization(self) -> None:
        assert normalize_message("division by zero") != normalize_message("list index out of range")
