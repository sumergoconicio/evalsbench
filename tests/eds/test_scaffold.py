"""
Unit tests for ``evalsbench.eds.scaffold``.

Covers:

* Validation: ``validate_domain_name`` accepts well-formed kebab/snake
  names and rejects empty strings, uppercase letters, leading dots,
  path separators, ``..`` segments, or names overflowing the 64-char
  cap.
* Tree emission: ``scaffold_domain`` writes the documented artifact
  tree (``__init__.py``, ``fixtures.py``, ``tools.py``, ``specs/``,
  ``specs/<name>_example.eds.md``) with starter content that the
  parser round-trips successfully.
* Round-trip: the generated ``.eds.md`` parses via ``EpisodeParser``
  without errors and the linter views it as a clean spec.
* Refusal semantics: re-running ``scaffold_domain`` against an
  existing populated directory must raise ``FileExistsError``.
* Testability: the optional ``base_dir`` parameter lets tests run
  inside ``tmp_path``; the default still resolves to the real
  ``evalsbench/eds/domains`` package directory.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

import pytest

from evalsbench.eds.parser import EpisodeParser
from evalsbench.eds.scaffold import (
    InvalidDomainName,
    ScaffoldPaths,
    scaffold_domain,
    validate_domain_name,
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "alpha",
        "alpha-beta",
        "alpha_beta",
        "a",
        "abc123",
        "agent-v1",
        "domain-9_b",
        "minicorp-agency",
        "x" * 64,  # maximum length
    ],
)
def test_validate_domain_name_accepts_well_formed(name: str):
    """Lowercase kebab/snake names within the size cap must be accepted."""
    assert validate_domain_name(name) == name


@pytest.mark.parametrize(
    "name,reason",
    [
        ("", "empty"),
        ("   ", "whitespace"),
        ("Demo-One", "uppercase"),
        ("_under", "leading underscore"),
        ("-dash", "leading hyphen"),
        ("9-leading-digit", "leading digit"),
        ("../escape", "path traversal"),
        ("foo/../bar", "path traversal"),
        ("foo/bar", "path separator"),
        ("foo\\bar", "path separator"),
        (".hidden", "leading dot"),
        ("a" * 65, "too long"),
    ],
)
def test_validate_domain_name_rejects_bad_inputs(name: str, reason: str):
    """Bad names must raise ``InvalidDomainName`` with the offending value."""
    with pytest.raises(InvalidDomainName) as excinfo:
        validate_domain_name(name)
    assert excinfo.value.name == name


def test_validate_domain_name_rejects_non_string():
    """A non-string must raise ``InvalidDomainName`` rather than TypeError."""
    with pytest.raises(InvalidDomainName):
        validate_domain_name(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tree emission and round-trip parsing
# ---------------------------------------------------------------------------


EXPECTED_FILES: List[str] = [
    "__init__.py",
    "fixtures.py",
    "tools.py",
    "specs",
]


def test_scaffold_domain_creates_expected_tree(tmp_path: Path):
    """Scaffolding must emit the documented artifact tree with starter content."""
    paths = scaffold_domain("alpha", base_dir=tmp_path)
    for relative in EXPECTED_FILES:
        assert (paths.package_dir / relative).exists(), (
            f"missing artifact: {relative}"
        )
    assert paths.example_spec.exists()
    assert paths.example_spec.suffix == ".md"
    assert paths.example_spec.name == "alpha_example.eds.md"
    # Every generated file must be non-empty.
    for artifact in (
        paths.init_file,
        paths.fixtures_file,
        paths.tools_file,
        paths.example_spec,
    ):
        assert artifact.read_text().strip(), f"{artifact} is empty"


def test_scaffold_round_trip_through_parser(tmp_path: Path):
    """The starter ``.eds.md`` must parse against the canonical EDS parser."""
    paths = scaffold_domain("beta", base_dir=tmp_path)
    parsed = EpisodeParser.from_markdown(paths.example_spec)
    assert parsed.spec.id, "spec id must be populated"
    assert parsed.spec.suite == "beta"
    assert parsed.section_blocks["Visible Tools"].tools
    tool_names = [tool.name for tool in parsed.section_blocks["Visible Tools"].tools]
    assert tool_names == ["beta_starter_tool"]


def test_scaffold_generated_spec_lints_clean(tmp_path: Path):
    """The starter spec must also pass the EDS linter without errors."""
    from evalsbench.eds.linter import lint_spec

    paths = scaffold_domain("gamma", base_dir=tmp_path)
    report = lint_spec(paths.example_spec)
    assert report.has_errors is False, (
        f"starter spec failed to lint: "
        f"{[m.message for m in report.results[0].messages]}"
    )


def test_scaffold_with_kebab_name_uses_underscore_tool(tmp_path: Path):
    """A kebab-case domain name must produce an underscore-safe tool name."""
    paths = scaffold_domain("finance-travel", base_dir=tmp_path)
    parsed = EpisodeParser.from_markdown(paths.example_spec)
    names = [tool.name for tool in parsed.section_blocks["Visible Tools"].tools]
    # Hyphens are illegal in tool names; underscores are not.
    assert "-" not in names[0]
    assert "_" in names[0]


def test_scaffold_tools_file_uses_mock_tool_decorator(tmp_path: Path):
    """The starter tools module must import ``@mock_tool`` and decorate a fn."""
    paths = scaffold_domain("delta", base_dir=tmp_path)
    text = paths.tools_file.read_text()
    assert "from evalsbench.eds.tools import mock_tool" in text
    assert "@mock_tool" in text
    assert "def delta_starter_tool" in text


def test_scaffold_fixtures_file_exports_default_fixture(tmp_path: Path):
    """The starter fixtures module must export ``DEFAULT_FIXTURE``."""
    paths = scaffold_domain("epsilon", base_dir=tmp_path)
    text = paths.fixtures_file.read_text()
    assert "DEFAULT_FIXTURE" in text
    assert "Tag(gedEntity)" in text or "TaggedEntity" in text
    assert "Provenance" in text


# ---------------------------------------------------------------------------
# Refusal semantics
# ---------------------------------------------------------------------------


def test_scaffold_refuses_overwrite_populated_directory(tmp_path: Path):
    """Re-running scaffold on a populated tree must raise ``FileExistsError``."""
    scaffold_domain("zeta", base_dir=tmp_path)
    with pytest.raises(FileExistsError):
        scaffold_domain("zeta", base_dir=tmp_path)


def test_scaffold_overwrite_flag_replaces_empty_directory(tmp_path: Path):
    """``overwrite=True`` must safely remove and recreate the directory."""
    target = tmp_path / "eta"
    target.mkdir()
    paths1 = scaffold_domain("eta", base_dir=tmp_path, overwrite=True)
    assert paths1.package_dir.exists()
    # The freshly-scaffolded tools module must exist (rebuilt).
    assert paths1.tools_file.exists()


def test_scaffold_overwrite_rejects_non_empty_directory(tmp_path: Path):
    """``overwrite=True`` against a populated directory must still refuse."""
    scaffold_domain("theta", base_dir=tmp_path)
    with pytest.raises(FileExistsError):
        scaffold_domain("theta", base_dir=tmp_path, overwrite=True)


# ---------------------------------------------------------------------------
# Defaults + cleanup hygiene
# ---------------------------------------------------------------------------


def test_scaffold_default_base_dir_resolves_inside_package(tmp_path: Path, monkeypatch):
    """When ``base_dir`` is omitted the scaffolder must default to the package."""
    # We monkeypatch via inspecting the resolved default to ensure it lands
    # under evalsbench/eds/domains without actually writing into it.
    from evalsbench.eds import scaffold as scaffold_mod

    fake_base = tmp_path / "domains"
    monkeypatch.setattr(
        scaffold_mod,
        "Path",
        # keep behaviour identical for everything except __file__-derived default
        Path,
    )
    # When base_dir is None, _resolve_base_dir returns Path(file).parent/'domains'.
    resolved = scaffold_mod._resolve_base_dir(None)
    assert resolved.name == "domains"
    assert resolved.parent.name == "eds"
    # The path may not exist yet on a clean checkout, so do not assert exists().


def test_scaffold_cleans_up_when_base_dir_is_tmp(tmp_path: Path):
    """The scaffolder's tree lives under tmp_path; removing tmp_path is sufficient."""
    paths = scaffold_domain("kappa", base_dir=tmp_path)
    assert paths.package_dir.is_dir()
    # Hygiene: nothing outside paths.package_dir should have been created.
    expected_children = set(tmp_path.iterdir())
    assert expected_children == {paths.package_dir}
    shutil.rmtree(tmp_path)
    assert not tmp_path.exists()
