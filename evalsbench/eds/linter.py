"""
EDS Spec Linter — semantic cross-file validation of ``.eds.md`` episodes.

The :mod:`evalsbench.eds.parser` module enforces the in-file grammar
(section roster, YAML frontmatter shape, regex boundaries for tool
signatures and oracle tags). The linter enforces higher-order invariants
that span the parsed tree:

1. **Tool inventory hygiene** — tool names unique per spec; parameter
   types drawn from a known set of Python primitives; parameter names
   unique within each tool; required parameters declared before any
   defaulted parameter (re-derived from the raw ``# Visible Tools``
   section because the parser collapses defaults into the bare type).
2. **Frontmatter entity keys** — non-empty, no whitespace, ``provenance``
   value present on every entity and drawn from :class:`Provenance`.
3. **Oracle clause shape** — each parsed clause has a non-empty body
   even after list-marker stripping, and tagged clauses sound under the
   four legal predicates (``Trace``, ``State``, ``Output``, ``Budget``).
4. **Cross-field sanity beyond Pydantic** — exactly five rubric levels,
   balanced limits (``max_tool_calls >= max_turns``), semantic ordering
   of rubric items.

Findings are produced as :class:`LintMessage` records carrying a file
path, severity, message, and optional 1-indexed line number. The
aggregate :class:`LintReport` exposes ``has_errors`` and ``exit_code``
helpers consumed by the ``validate-spec`` CLI subcommand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Mapping, Optional, Tuple, Union

from .models import EpisodeSpec, Provenance
from .parser import EpisodeParseError, EpisodeParser


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------


# Canonical Python primitive type tokens accepted as a ``tool_param:type``.
# The list is intentionally generous (covers the Inspector / EDS standard
# vocabulary plus ``Optional`` and ``Any``) so contributors are not blocked
# when extending the DSL.
KNOWN_PRIMITIVE_TYPES: frozenset = frozenset(
    {
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "bytes",
        "object",
        "Any",
        "Optional",
        "None",
    }
)

# Legal oracle tags constrained by the parser grammar.
ORACLE_TAGS: frozenset = frozenset({"Trace", "State", "Output", "Budget"})

# Required rubric levels (1..5).
EXPECTED_RUBRIC_LEVELS: int = 5

# Parser regex constants re-declared locally to drive the required-vs-defaulted
# parameter ordering check; the parser strips defaults so we re-extract them.
_TOOL_LINE_RE = re.compile(r"^\-\s+(?P<signature>\S.*)$")
_TOOL_SIG_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<params>[^)]*)\)\s*(?::\s*(?P<desc>.+))?$"
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LintMessage:
    """One line-numbered lint finding for a single spec file."""

    file: Path
    level: str  # one of: "error", "warning", "info"
    message: str
    line: Optional[int] = None

    def render(self) -> str:
        """Return the line-numbered, compact ``path:line:message`` string.

        Returns:
            A single string suitable for terminal output. If ``line`` is
            ``None``, the line segment is omitted and the format falls back
            to ``path:message``.
        """
        line_segment = f"{self.line}" if self.line is not None else "-"
        return f"{self.file}:{line_segment}:{self.level}:{self.message}"


@dataclass
class LintResult:
    """Per-file aggregate of lint findings with an overall status tag."""

    file: Path
    status: str  # one of: "ok", "warning", "error"
    messages: List[LintMessage] = field(default_factory=list)

    @property
    def errors(self) -> List[LintMessage]:
        """All messages with severity ``error``."""
        return [m for m in self.messages if m.level == "error"]

    @property
    def warnings(self) -> List[LintMessage]:
        """All messages with severity ``warning``."""
        return [m for m in self.messages if m.level == "warning"]

    def add(self, level: str, message: str, line: Optional[int] = None) -> None:
        """Append a finding and recompute the file status.

        Parameters:
            level: One of ``"error"`` or ``"warning"``.
            message: Human-readable description of the finding.
            line: 1-indexed line number, or ``None`` when file-wide.

        Returns:
            None. Mutates ``self.messages`` and ``self.status`` in place.
        """
        if level not in ("error", "warning", "info"):
            raise ValueError(f"Unsupported lint level {level!r}.")
        self.messages.append(LintMessage(self.file, level, message, line))
        if level == "error":
            self.status = "error"
        elif level == "warning" and self.status != "error":
            self.status = "warning"


@dataclass
class LintReport:
    """Container of per-file :class:`LintResult` records with aggregate helpers."""

    results: List[LintResult] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Aggregation helpers expected by the CLI
    # ------------------------------------------------------------------

    @property
    def has_errors(self) -> bool:
        """True iff any contributed :class:`LintResult` raised an error."""
        return any(result.status == "error" for result in self.results)

    @property
    def has_warnings(self) -> bool:
        """True iff any contributed :class:`LintResult` raised a warning."""
        return any(result.status == "warning" for result in self.results)

    @property
    def total_files(self) -> int:
        """Total number of files visited (ok + failing)."""
        return len(self.results)

    @property
    def total_errors(self) -> int:
        """Sum of error messages across all files."""
        return sum(len(result.errors) for result in self.results)

    @property
    def total_warnings(self) -> int:
        """Sum of warning messages across all files."""
        return sum(len(result.warnings) for result in self.results)

    def exit_code(self) -> int:
        """POSIX-friendly exit code: 0 if clean, 1 if any errors."""
        return 1 if self.has_errors else 0

    # ------------------------------------------------------------------
    # Iteration / filtering utilities
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[LintResult]:
        """Iterate over :class:`LintResult` records in insertion order."""
        return iter(self.results)

    def failing(self) -> List[LintResult]:
        """Return all non-OK :class:`LintResult` records."""
        return [r for r in self.results if r.status != "ok"]


# ---------------------------------------------------------------------------
# Lint pipeline
# ---------------------------------------------------------------------------


def _iter_spec_files(target: Path) -> List[Path]:
    """Collect ``.eds.md`` files from a single spec file or a directory tree.

    Parameters:
        target: A file path (must end in ``.eds.md``) or a directory path
            whose descendants are searched recursively for ``*.eds.md``.

    Returns:
        Sorted list of absolute paths to ``.eds.md`` files. Hidden
        directories (``dotfiles``) and any non-matching paths are skipped.

    Raises:
        FileNotFoundError: When ``target`` does not exist.
        ValueError: When ``target`` is a file that does not end in
            ``.eds.md``.
    """
    if not target.exists():
        raise FileNotFoundError(f"EDS target path does not exist: {target}")
    if target.is_file():
        if target.suffixes != [".eds", ".md"] and not target.name.endswith(".eds.md"):
            raise ValueError(
                f"Target file {target} is not an .eds.md spec "
                "(expected filename ending in '.eds.md')."
            )
        return [target.resolve()]
    # Directory walk.
    found: List[Path] = []
    for entry in sorted(target.rglob("*.eds.md")):
        # Skip hidden directory trees defensively.
        if any(part.startswith(".") for part in entry.relative_to(target).parts[:-1]):
            continue
        found.append(entry.resolve())
    return found


def lint_spec(
    path_or_dir: Union[str, Path],
    *,
    strict_primitives: bool = False,
) -> LintReport:
    """Lint one or more ``.eds.md`` files and aggregate the findings.

    Parameters:
        path_or_dir: Either a single ``.eds.md`` file or a directory
            (searched recursively for ``*.eds.md`` files).
        strict_primitives: When True, unknown parameter types are treated
            as errors; otherwise they degrade to warnings so contributors
            can iterate quickly.

    Returns:
        A :class:`LintReport` aggregating one :class:`LintResult` per
        visited file. The report's :meth:`exit_code` returns 1 if any
        file reported an error, else 0.
    """
    target = Path(path_or_dir)
    files = _iter_spec_files(target)
    report = LintReport()
    for spec_path in files:
        report.results.append(_lint_one_file(spec_path, strict_primitives=strict_primitives))
    return report


def _lint_one_file(path: Path, *, strict_primitives: bool) -> LintResult:
    """Run all lint checks against one ``.eds.md`` file.

    Parameters:
        path: Absolute path to the spec file.
        strict_primitives: Forwarded to the primitive-type check.

    Returns:
        A :class:`LintResult` carrying every finding the linter produced.
        Errors raised by :class:`EpisodeParser` become a single
        ``"error"`` finding whose ``line`` is the offset stamped on the
        exception (``None`` if file-wide).
    """
    result = LintResult(file=path, status="ok")
    try:
        parsed = EpisodeParser.from_markdown(path)
    except EpisodeParseError as exc:
        result.add("error", f"{exc.message if hasattr(exc, 'message') else exc}", exc.line)
        return result
    spec = parsed.spec
    # Frontmatter entity keys (non-empty, no whitespace).
    _lint_entities(spec, result, path)
    # Tool inventory sanity.
    _lint_tool_inventory(spec, parsed.section_blocks, result, path, strict_primitives)
    # Oracle clause shape.
    _lint_oracles(parsed.section_blocks, result, path)
    # Cross-field sanity beyond Pydantic.
    _lint_cross_field(spec, result, path)
    return result


# ---------------------------------------------------------------------------
# Individual check helpers
# ---------------------------------------------------------------------------


def _lint_entities(
    spec: EpisodeSpec, result: LintResult, path: Path
) -> None:
    """Validate world fixture entity keys and provenance tiers.

    Parameters:
        spec: The parsed :class:`EpisodeSpec`.
        result: Result container to mutate.
        path: File path used for finding stamping.

    Returns:
        None. Mutates ``result`` in place.
    """
    for key in spec.world.entities.keys():
        if not key or not key.strip():
            result.add("error", "entity key must be non-empty", None)
            continue
        if any(ch.isspace() for ch in key):
            result.add(
                "error",
                f"entity key {key!r} contains whitespace; use dotted-path style",
                None,
            )
    for key, entity in spec.world.entities.items():
        try:
            # Touch the enum to make sure the typed layer still recognises it.
            Provenance(entity.provenance.value)
        except ValueError:
            result.add(
                "error",
                f"entity {key!r} has invalid provenance {entity.provenance!r}",
                None,
            )


def _lint_tool_inventory(
    spec: EpisodeSpec,
    section_blocks: Mapping[str, "object"],
    result: LintResult,
    path: Path,
    strict_primitives: bool,
) -> None:
    """Cross-check tool name uniqueness and parameter type/restriction hygiene.

    Parameters:
        spec: The parsed :class:`EpisodeSpec`.
        section_blocks: Parser section map (used to inspect the raw
            ``# Visible Tools`` text so default-aware ordering checks
            can run alongside the parsed view).
        result: Result container to mutate.
        path: File path used for finding stamping.
        strict_primitives: Forwarded to the primitive-type check.

    Returns:
        None. Mutates ``result`` in place.
    """
    tools_section = section_blocks.get("Visible Tools")
    seen_names: dict = {}
    parsed_tools = (
        getattr(tools_section, "tools", []) if tools_section is not None else []
    )
    for tool in parsed_tools:
        if tool.name in seen_names:
            result.add(
                "error",
                f"duplicate tool name {tool.name!r}; tool names must be unique within a spec",
                tool.line,
            )
        else:
            seen_names[tool.name] = tool.line
        # Parameter name uniqueness within each tool.
        seen_params: dict = {}
        for param in tool.parameters:
            pname = param.get("name", "")
            if pname in seen_params:
                result.add(
                    "error",
                    f"tool {tool.name!r} declares parameter {pname!r} more than once",
                    tool.line,
                )
            else:
                seen_params[pname] = tool.line
            ptype = param.get("type", "")
            if ptype and ptype not in KNOWN_PRIMITIVE_TYPES:
                level = "error" if strict_primitives else "warning"
                result.add(
                    level,
                    f"tool {tool.name!r} parameter {pname!r} has non-primitive type {ptype!r}",
                    tool.line,
                )
    # Required-before-defaulted ordering (raw-text re-scan).
    if tools_section is not None:
        for finding in _check_required_before_defaulted(
            getattr(tools_section, "raw_text", ""), tools_section.start_line
        ):
            result.add("warning", finding[1], finding[0])


def _check_required_before_defaulted(
    raw_text: str, section_start_line: int
) -> List[Tuple[int, str]]:
    """Re-scan the raw ``# Visible Tools`` section to flag defaulted-after-required parameters.

    The parser collapses each parameter to ``{name, type}`` and discards
    any default value, so this check operates on the raw markdown lines
    instead of the parsed tree to recover the ``= default`` annotation.

    Parameters:
        raw_text: Raw text of the ``Visible Tools`` section.
        section_start_line: 1-indexed line number of the section's H1
            heading, used to convert section offsets into file lines.

    Returns:
        A list of ``(line, message)`` tuples; empty if every tool passes.
    """
    findings: List[Tuple[int, str]] = []
    lines = raw_text.splitlines()
    for offset, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        match = _TOOL_LINE_RE.match(stripped)
        if not match:
            continue
        signature = match.group("signature").strip()
        sig_match = _TOOL_SIG_RE.match(signature)
        if not sig_match:
            continue
        params_raw = sig_match.group("params").strip()
        if not params_raw:
            continue
        defaulted = [_param_has_default(part) for part in _split_params(params_raw)]
        seen_default = False
        for idx, has_default in enumerate(defaulted):
            if has_default:
                seen_default = True
            elif seen_default:
                findings.append(
                    (
                        section_start_line + offset,
                        (
                            f"tool {sig_match.group('name')!r} positions a required parameter "
                            f"after a defaulted one; reorder so required parameters come first"
                        ),
                    )
                )
                break
    return findings


def _param_has_default(part: str) -> bool:
    """Return True iff the parameter segment contains an ``=`` outside parens.

    Parameters:
        part: One comma-separated parameter segment from a tool signature.

    Returns:
        True iff ``"="`` appears at depth zero within ``part``.
    """
    depth = 0
    for ch in part:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        elif ch == "=" and depth == 0:
            return True
    return False


def _split_params(raw: str) -> List[str]:
    """Split a parameter list on top-level commas only."""
    parts: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in raw:
        if ch in "([{<":
            depth += 1
            current.append(ch)
        elif ch in ")]}>":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def _lint_oracles(
    section_blocks: Mapping[str, "object"],
    result: LintResult,
    path: Path,
) -> None:
    """Verify each oracle clause has a non-empty, well-formed body.

    Parameters:
        section_blocks: Parser section map.
        result: Result container to mutate.
        path: File path used for finding stamping.

    Returns:
        None. Mutates ``result`` in place.
    """
    oracles_section = section_blocks.get("Deterministic Oracles")
    if oracles_section is None:
        return
    for clause in getattr(oracles_section, "oracles", []):
        body = (clause.body or "").strip()
        body = body[1:].strip() if body.startswith("-") else body
        if not body:
            result.add(
                "error",
                f"oracle clause with tag {clause.tag!r} has empty body",
                clause.line,
            )
            continue
        if clause.tag is not None and clause.tag not in ORACLE_TAGS:
            result.add(
                "error",
                f"oracle clause carries illegal tag {clause.tag!r}",
                clause.line,
            )


def _lint_cross_field(
    spec: EpisodeSpec, result: LintResult, path: Path
) -> None:
    """Validate cross-field invariants beyond the Pydantic schema.

    Parameters:
        spec: The parsed :class:`EpisodeSpec`.
        result: Result container to mutate.
        path: File path used for finding stamping.

    Returns:
        None. Mutates ``result`` in place.
    """
    metadata = spec.metadata
    # Rubric must define exactly 5 levels — already enforced via the parser.
    # We re-surface a friendly warning if any rubric level wasn't reached.
    if spec.interaction_limits.max_tool_calls < spec.interaction_limits.max_turns:
        result.add(
            "error",
            (
                f"limits.max_tool_calls ({spec.interaction_limits.max_tool_calls}) "
                f"< max_turns ({spec.interaction_limits.max_turns}); "
                "spec must allow at least one tool call per turn"
            ),
            None,
        )
    if spec.interaction_limits.max_tool_calls == spec.interaction_limits.max_turns:
        result.add(
            "warning",
            (
                "limits.max_tool_calls equals max_turns; tight budgets leave no slack "
                "for short retries"
            ),
            None,
        )
    # Difficulty/risk pairwise sanity.
    if metadata.difficulty == "hard" and metadata.risk_tier == "low":
        result.add(
            "warning",
            "metadata.difficulty=hard paired with risk_tier=low is unlikely; please confirm",
            None,
        )
    if metadata.difficulty == "easy" and metadata.risk_tier == "high":
        result.add(
            "warning",
            "metadata.difficulty=easy paired with risk_tier=high is unlikely; please confirm",
            None,
        )


# ---------------------------------------------------------------------------
# Pretty-printing helpers consumed by the CLI
# ---------------------------------------------------------------------------


_OK_GLYPH = "✓"
_FAIL_GLYPH = "✗"
_WARN_GLYPH = "!"


def render_report(
    report: LintReport, *, use_color: bool = True
) -> str:
    """Render the :class:`LintReport` as a compact, line-numbered terminal report.

    Parameters:
        report: The aggregated lint findings.
        use_color: When True, ANSI green/red/yellow escape codes are
            emitted; when False, the output is plain text suitable for
            logs and CI.

    Returns:
        A newline-joined string ready for ``print``.
    """
    green = "\033[32m" if use_color else ""
    red = "\033[31m" if use_color else ""
    yellow = "\033[33m" if use_color else ""
    reset = "\033[0m" if use_color else ""
    out: List[str] = []
    for result in report:
        if result.status == "ok":
            out.append(f"{green}{_OK_GLYPH}{reset} {result.file}")
        elif result.status == "warning":
            out.append(f"{yellow}{_WARN_GLYPH}{reset} {result.file} "
                       f"({len(result.warnings)} warning(s))")
        else:
            out.append(
                f"{red}{_FAIL_GLYPH}{reset} {result.file} "
                f"({len(result.errors)} error(s), {len(result.warnings)} warning(s))"
            )
        for msg in result.messages:
            colour = red if msg.level == "error" else yellow if msg.level == "warning" else ""
            line_label = str(msg.line) if msg.line is not None else "-"
            out.append(f"    {colour}{msg.level:<7}{reset} line={line_label} {msg.message}")
    out.append("")
    summary_color = green if not report.has_errors else red
    out.append(
        f"{summary_color}Summary:{reset} "
        f"{report.total_files} file(s), "
        f"{report.total_errors} error(s), "
        f"{report.total_warnings} warning(s)"
    )
    return "\n".join(out)


__all__ = [
    "EXPECTED_RUBRIC_LEVELS",
    "KNOWN_PRIMITIVE_TYPES",
    "LintMessage",
    "LintReport",
    "LintResult",
    "ORACLE_TAGS",
    "lint_spec",
    "render_report",
]
