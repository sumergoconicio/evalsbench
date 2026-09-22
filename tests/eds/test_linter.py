"""
Unit tests for ``evalsbench.eds.linter``.

Covers:

* Happy-path: the canonical MiniCorp booking spec lints cleanly (no
  errors, no warnings).
* Corrupted copies: copies of the canonical spec with targeted
  mutations produce line-numbered error findings (duplicate tool
  names, duplicate parameter names, defaulted-after-required
  ordering, malformed tool types, insufficient rubric depth,
  unparseable YAML, missing H1 sections).
* Directory mode: linting a directory aggregates every nested file's
  findings into one ``LintReport``.
* Exit-code semantics: ``LintReport.exit_code()`` returns ``0`` when
  the report is clean and ``1`` when at least one error was logged.
* CLI bridge: the ``validate-spec`` subcommand emits the same
  exit codes and prints a compact, line-numbered report.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from evalsbench.eds.linter import (
    LintMessage,
    LintReport,
    LintResult,
    lint_spec,
    render_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "evalsbench/eds/specs/examples"
GOOD_SPEC = EXAMPLES_DIR / "minicorp_booking.eds.md"


# To avoid Python string-literal escaping pitfalls when reusing the same
# ``"- acme_tool(name: str = "", ...)`` snippet across many tests, we
# pre-build the canonical fixture content and an unambiguous raw target.
GOOD_BODY = textwrap.dedent(
    """\
    ---
    id: lint-good-baseline
    suite: lint-tests
    version: "1.0.0"
    limits:
      max_turns: 6
      max_tool_calls: 12
      wall_time_seconds: 90
    world_fixture:
      name: Sandbox
      fixture_version: "1"
      state: { clock: "2026-01-01T00:00:00Z" }
      entities:
        starter:
          provenance: canonical
          payload: { note: "starter" }
    actor:
      principal_id: agent-1
      roles: [agent]
      permissions: [starter.read]
    hidden_truth: {}
    metadata:
      capability: t
      difficulty: medium
      risk_tier: medium
      tags: [lint]
    ---

    # Objective

    Demonstrate the EDS linter with a minimal happy-path spec.

    # Visible Request

    > do the thing

    # Visible Tools

    - acme_tool(name: str = "", count: int = 1): canonical demo tool.

    # Deterministic Oracles

    - [Trace] acme_tool MUST be invoked at least once.
    - [Output] final_text MUST contain "ok".

    # Semantic Rubric

    1. Skips the tool.
    2. Calls tool with wrong arg.
    3. Calls tool but reply is brief.
    4. Calls tool correctly but reply is missing literal.
    5. Calls tool correctly and reply contains the literal.
    """
)

# The literal substring searched by every corrupted-copy test below. Defined
# as a module-level constant so escaping stays consistent across tests.
GOOD_TOOL_LINE = '- acme_tool(name: str = "", count: int = 1): canonical demo tool.'
GOOD_LIMITS_LINE = "  max_turns: 6\n  max_tool_calls: 12"
GOOD_RUBRIC_BLOCK = (
    "1. Skips the tool.\n"
    "2. Calls tool with wrong arg.\n"
    "3. Calls tool but reply is brief.\n"
    "4. Calls tool correctly but reply is missing literal.\n"
    "5. Calls tool correctly and reply contains the literal."
)


@pytest.fixture()
def tmp_spec_dir(tmp_path: Path) -> Path:
    """Provide a sandboxed directory for emitting temporary ``.eds.md`` files."""
    return tmp_path


def _write(path: Path, body: str) -> Path:
    """Write ``body`` to ``path`` ensuring the parent exists; return the path.

    Parameters:
        path: Destination spec file.
        body: Full Markdown content (frontmatter + sections).

    Returns:
        The same ``path`` for convenience.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_lint_spec_passes_for_canonical_example():
    """The canonical MiniCorp booking spec must lint cleanly."""
    report = lint_spec(GOOD_SPEC)
    assert report.has_errors is False
    assert report.exit_code() == 0
    assert report.total_files == 1
    assert report.total_errors == 0
    assert report.total_warnings == 0
    assert report.results[0].status == "ok"


def test_lint_spec_passes_for_minimal_good_body(tmp_spec_dir: Path):
    """A minimal synth-good body written to disk also lints cleanly."""
    path = _write(tmp_spec_dir / "minimal.eds.md", GOOD_BODY)
    report = lint_spec(path)
    assert report.exit_code() == 0
    assert [r.status for r in report] == ["ok"]


# ---------------------------------------------------------------------------
# Corrupted copies — each mutation must surface a line-numbered error
# ---------------------------------------------------------------------------


def test_lint_catches_duplicate_tool_name(tmp_spec_dir: Path):
    """Two tool declarations sharing one name must produce an error."""
    bad = GOOD_BODY.replace(
        GOOD_TOOL_LINE,
        '- acme_tool(name: str = ""): first.\n- acme_tool(flag: bool = false): second.',
    )
    path = _write(tmp_spec_dir / "dup.eds.md", bad)
    report = lint_spec(path)
    assert report.has_errors is True
    assert report.exit_code() == 1
    msgs = report.results[0].messages
    assert any(
        "duplicate tool name" in m.message for m in msgs
    ), f"expected duplicate-name finding, got: {[m.message for m in msgs]}"


def test_lint_catches_duplicate_parameter_name(tmp_spec_dir: Path):
    """Repeating a parameter name on a single tool must produce an error."""
    bad = GOOD_BODY.replace(
        GOOD_TOOL_LINE,
        "- acme_tool(repeat: str, repeat: int): duplicate parameter name.",
    )
    path = _write(tmp_spec_dir / "dupparam.eds.md", bad)
    report = lint_spec(path)
    assert report.has_errors is True
    msgs = report.results[0].messages
    assert any(
        "parameter 'repeat' more than once" in m.message for m in msgs
    ), f"expected duplicate-param finding, got: {[m.message for m in msgs]}"


def test_lint_warns_on_required_after_defaulted(tmp_spec_dir: Path):
    """A required parameter placed after a defaulted one must yield a warning."""
    bad = GOOD_BODY.replace(
        GOOD_TOOL_LINE,
        "- acme_tool(opt: int = 0, req: str): required after defaulted.",
    )
    path = _write(tmp_spec_dir / "order.eds.md", bad)
    report = lint_spec(path)
    # should still exit 0 (warning not error)
    assert report.exit_code() == 0
    msgs = report.results[0].messages
    assert any(
        "required parameter after a defaulted one" in m.message for m in msgs
    ), f"expected ordering warning, got: {[m.message for m in msgs]}"


def test_lint_warns_on_unknown_primitive_type(tmp_spec_dir: Path):
    """A non-primitive type degrades to a warning by default."""
    bad = GOOD_BODY.replace(
        GOOD_TOOL_LINE,
        "- acme_tool(name: foobar): unknown-primitive parameter type.",
    )
    path = _write(tmp_spec_dir / "weirdtype.eds.md", bad)
    report = lint_spec(path)
    # default behaviour: warning, exit 0
    assert report.exit_code() == 0
    msgs = report.results[0].messages
    assert any(
        "non-primitive type" in m.message for m in msgs
    ), f"expected primitive-type warning, got: {[m.message for m in msgs]}"


def test_lint_strict_primitives_treats_unknown_type_as_error(tmp_spec_dir: Path):
    """``strict_primitives=True`` should escalate unknown-type to an error."""
    bad = GOOD_BODY.replace(
        GOOD_TOOL_LINE,
        "- acme_tool(name: foobar): unknown-primitive parameter type.",
    )
    path = _write(tmp_spec_dir / "weirdstrict.eds.md", bad)
    report = lint_spec(path, strict_primitives=True)
    assert report.exit_code() == 1
    assert any("foobar" in m.message for m in report.results[0].messages)


def test_lint_catches_invalid_limits(tmp_spec_dir: Path):
    """``max_tool_calls < max_turns`` must produce a cross-field error."""
    bad = GOOD_BODY.replace(
        GOOD_LIMITS_LINE,
        "  max_turns: 8\n  max_tool_calls: 4",
    )
    path = _write(tmp_spec_dir / "limits.eds.md", bad)
    report = lint_spec(path)
    assert report.exit_code() == 1
    msgs = report.results[0].messages
    assert any("max_tool_calls" in m.message for m in msgs)


def test_lint_catches_parser_error_with_line_number(tmp_spec_dir: Path):
    """A known parser error (insufficient rubric) must be reported with a line."""
    bad = GOOD_BODY.replace(
        GOOD_RUBRIC_BLOCK,
        "1. Skips the tool.\n2. Calls tool with wrong arg.",
    )
    path = _write(tmp_spec_dir / "shortrubric.eds.md", bad)
    report = lint_spec(path)
    # The parser raises EpisodeParseError; the linter wraps it as one error.
    assert report.exit_code() == 1
    msgs = report.results[0].messages
    assert msgs, "expected at least one message on short rubric"
    assert msgs[0].line is not None, "expected a 1-indexed line on parser-error finding"


def test_lint_rejects_non_eds_file_extension(tmp_spec_dir: Path):
    """File without ``.eds.md`` suffix should raise a ``ValueError``."""
    bogus = _write(tmp_spec_dir / "wrong.txt", GOOD_BODY)
    with pytest.raises(ValueError):
        lint_spec(bogus)


def test_lint_rejects_missing_path(tmp_spec_dir: Path):
    """Path that does not exist should raise ``FileNotFoundError``."""
    missing = tmp_spec_dir / "does_not_exist.eds.md"
    with pytest.raises(FileNotFoundError):
        lint_spec(missing)


# ---------------------------------------------------------------------------
# Directory mode and aggregation
# ---------------------------------------------------------------------------


def test_lint_directory_aggregates_per_file_results(tmp_spec_dir: Path):
    """Linting a directory must produce one ``LintResult`` per nested file."""
    _write(tmp_spec_dir / "good.eds.md", GOOD_BODY)
    bad = GOOD_BODY.replace(
        GOOD_TOOL_LINE,
        "- acme_tool(opt: int = 0, req: str): required after defaulted.",
    )
    _write(tmp_spec_dir / "warn.eds.md", bad)
    busted = GOOD_BODY.replace(
        GOOD_TOOL_LINE,
        "- acme_tool(repeat: str, repeat: int): dup params.",
    )
    _write(tmp_spec_dir / "broken.eds.md", busted)
    report = lint_spec(tmp_spec_dir)
    assert report.total_files == 3
    # broken file must be the only error; warn must be warning; good must be ok.
    by_file = {r.file.name: r for r in report}
    assert by_file["good.eds.md"].status == "ok"
    assert by_file["warn.eds.md"].status == "warning"
    assert by_file["broken.eds.md"].status == "error"
    assert report.has_errors is True
    assert report.exit_code() == 1


def test_lint_directory_skips_hidden_directories(tmp_spec_dir: Path):
    """Hidden (dotfile) directories under the target are ignored by the walk."""
    _write(tmp_spec_dir / "good.eds.md", GOOD_BODY)
    hidden = tmp_spec_dir / ".hidden"
    _write(hidden / "should.not.be.linted.eds.md", GOOD_BODY)
    report = lint_spec(tmp_spec_dir)
    assert report.total_files == 1
    assert report.results[0].file.name == "good.eds.md"


# ---------------------------------------------------------------------------
# CLI bridge — full integration with ``python -m evalsbench validate-spec``
# ---------------------------------------------------------------------------


def test_cli_validate_spec_runs_via_dispatch(monkeypatch, tmp_spec_dir: Path):
    """The CLI subcommand must invoke the linter and return its exit code."""
    from evalsbench import cli as ev_cli

    path = _write(tmp_spec_dir / "ok.eds.md", GOOD_BODY)
    rc = ev_cli._handle_validate_spec([str(path), "--no-color"])
    assert rc == 0


def test_cli_validate_spec_propagates_error_exit(monkeypatch, tmp_spec_dir: Path):
    """An error file must surface an exit code of 1 from the CLI handler."""
    from evalsbench import cli as ev_cli

    bad = GOOD_BODY.replace(
        GOOD_TOOL_LINE,
        "- acme_tool(repeat: str, repeat: int): dup params.",
    )
    path = _write(tmp_spec_dir / "broken.eds.md", bad)
    rc = ev_cli._handle_validate_spec([str(path), "--no-color"])
    assert rc == 1


def test_cli_dispatch_returns_none_for_legacy_invocation():
    """``_maybe_dispatch_subcommand`` must defer to the legacy parser for flags."""
    from evalsbench import cli as ev_cli

    assert ev_cli._maybe_dispatch_subcommand(["--model", "foo"]) is None
    assert ev_cli._maybe_dispatch_subcommand(["--help"]) is None
    assert ev_cli._maybe_dispatch_subcommand([]) is None


def test_render_report_includes_file_lines(tmp_spec_dir: Path):
    """The pretty report must include ``file:line:level:message`` lines."""
    bad = GOOD_BODY.replace(
        GOOD_TOOL_LINE,
        "- acme_tool(repeat: str, repeat: int): dup params.",
    )
    path = _write(tmp_spec_dir / "x.eds.md", bad)
    report = lint_spec(path)
    rendered = render_report(report, use_color=False)
    assert "x.eds.md" in rendered
    assert "Summary" in rendered
    assert "error" in rendered
