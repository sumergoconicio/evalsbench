"""
EDS Markdown-first Episode DSL parser.

This module is the single source of truth for translating a human-authored
``.eds.md`` episode specification file into:

    1. A validated :class:`evalsbench.eds.models.EpisodeSpec` (the canonical
       machine-readable contract), and
    2. A standard :class:`inspect_ai.dataset.Sample` that downstream solver,
       tool, and scoring code can consume without bespoke adapters.

The Markdown-first DSL is the only supported format. Every episode file MUST
begin with a YAML frontmatter block (between two ``---`` fences) that declares
the machine metadata (id, suite, version, world fixture, actor, limits,
hidden truth, and EpisodeMetadata), followed by ordered H1 sections that
describe the visible/interactive parts (objective, request, tool inventory,
deterministic oracles, semantic rubric, optional trajectory).

Error reporting is line-numbered and section-aware so contributors can fix
malformed specs without guesswork.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import yaml
from inspect_ai.dataset import Sample
from pydantic import ValidationError

from .models import (
    Actor,
    EpisodeMetadata,
    EpisodeSpec,
    HiddenTruth,
    InteractionLimits,
    PolicyRule,
    Provenance,
    TaggedEntity,
    WorldFixture,
)


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class EpisodeParseError(ValueError):
    """Raised when an EDS Markdown file cannot be parsed into an EpisodeSpec.

    The message contains the absolute source path, the offending section name
    (when known), and a 1-indexed line number to aid fixing.
    """

    def __init__(
        self,
        message: str,
        *,
        path: Optional[Union[str, Path]] = None,
        section: Optional[str] = None,
        line: Optional[int] = None,
    ) -> None:
        """Initialise the typed parse error with file/section/line metadata.

        Parameters:
            message: Human-readable description of the malformed spec.
            path: Absolute or relative path of the offending file (optional).
            section: Name of the offending H1 section, ``<frontmatter>`` for
                YAML frontmatter errors, or ``None`` for top-level errors.
            line: 1-indexed line number where the error was detected, or
                ``None`` if the error is file-wide.

        Returns:
            None. Stamps the supplied metadata on the exception instance and
            composes a single string for the ``__str__`` representation.
        """
        bits: List[str] = []
        if path is not None:
            bits.append(f"{path}")
        if section is not None:
            bits.append(f"section={section!r}")
        if line is not None:
            bits.append(f"line={line}")
        bits.append(message)
        super().__init__(" | ".join(bits))
        self.path = str(path) if path is not None else None
        self.section = section
        self.line = line


# ---------------------------------------------------------------------------
# Section grammar (canonical, exposed for the linter worker)
# ---------------------------------------------------------------------------


# Ordered list of legal H1 section names. Parser accumulates them in arrival
# order and rejects anything not on this list with a precise line number.
KNOWN_SECTIONS: tuple = (
    "Objective",
    "Visible Request",
    "Visible Tools",
    "Deterministic Oracles",
    "Semantic Rubric",
    "Expected Behavioral Trajectory",
)

# Tools must be declared on lines beginning with "- " after list sanitation.
_TOOL_LINE_RE = re.compile(r"^\-\s+(?P<signature>\S.*)$")

# Tool signature grammar: ``name(param: type, param: type)``. Whitespace and
# optional trailing descriptions are tolerated but surfaced in the parse tree.
_TOOL_SIG_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<params>[^)]*)\)\s*(?::\s*(?P<desc>.+))?$"
)

# Oracle tag detection: ``[Trace]``, ``[State]``, ``[Output]``, ``[Budget]``.
# The regex tolerates a leading markdown list marker (``-``) because oracle
# clauses are written as list items in the DSL.
_ORACLE_TAG_RE = re.compile(
    r"^\s*(?:-\s+)?(?P<tag>\[(Trace|State|Output|Budget)\])\s*(?P<body>.*)$"
)

# Trajectory numbered step: ``1. <step>`` (also ``2.``, ...).
_TRAJECTORY_STEP_RE = re.compile(r"^(?P<num>\d+)\.\s+(?P<text>.+)$")


# ---------------------------------------------------------------------------
# Parsed section model
# ---------------------------------------------------------------------------


@dataclass
class ToolSignature:
    """One tool signature parsed from the ``# Visible Tools`` section."""

    name: str
    parameters: List[Dict[str, str]] = field(default_factory=list)
    description: Optional[str] = None
    line: int = 0


@dataclass
class OracleClause:
    """One clause parsed from the ``# Deterministic Oracles`` section.

    ``tag`` is one of ``Trace`` | ``State`` | ``Output`` | ``Budget`` or
    ``None`` when the author opts to write an untagged clause (which the
    validator later treats as a generic ``Trace`` predicate).
    """

    tag: Optional[str]
    body: str
    line: int


@dataclass
class ParsedSection:
    """Raw text and structured views of one H1 section."""

    name: str
    start_line: int
    raw_text: str
    # Structured projections (filled lazily by accessors).
    objective: Optional[str] = None
    visible_request: Optional[str] = None
    tools: List[ToolSignature] = field(default_factory=list)
    oracles: List[OracleClause] = field(default_factory=list)
    rubric: List[str] = field(default_factory=list)
    trajectory: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# File splitter: frontmatter + ordered # -prefixed body sections
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<yaml>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)


@dataclass
class _FileSplit:
    frontmatter: Dict[str, Any]
    frontmatter_start_line: int  # line where the first '---' begins
    sections: List[ParsedSection]


def _split_frontmatter(path: Path, text: str) -> _FileSplit:
    """Separate YAML frontmatter from ordered H1 sections and capture line offsets."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise EpisodeParseError(
            "Missing YAML frontmatter block (expected file to begin with '---' "
            "before the first H1 section).",
            path=path,
            line=1,
        )
    yaml_text = match.group("yaml")
    # The match.start() is the index of the opening '---' fence.
    frontmatter_start_line = text.count("\n", 0, match.start()) + 1
    try:
        frontmatter = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        # Locate the offending line within the frontmatter block.
        mark = getattr(exc, "problem_mark", None)
        line_offset = (mark.line + 1) if mark is not None else 0
        raise EpisodeParseError(
            f"YAML frontmatter unparsable: {exc}",
            path=path,
            section="<frontmatter>",
            line=frontmatter_start_line + line_offset,
        ) from exc
    if not isinstance(frontmatter, Mapping):
        raise EpisodeParseError(
            "YAML frontmatter must decode to a mapping (key/value block).",
            path=path,
            section="<frontmatter>",
            line=frontmatter_start_line + 1,
        )

    body = text[match.end():]
    sections = _split_body_sections(path, body)
    return _FileSplit(
        frontmatter=dict(frontmatter),
        frontmatter_start_line=frontmatter_start_line,
        sections=sections,
    )


def _split_body_sections(path: Path, body: str) -> List[ParsedSection]:
    """Slice the body into ordered ``# Section`` blocks preserving line numbers."""
    body_lines = body.splitlines()
    sections: List[ParsedSection] = []
    current_name: Optional[str] = None
    current_start_line: Optional[int] = None
    current_buffer: List[str] = []

    def _flush(end_line: int) -> None:
        """Append the current buffered section lines as a :class:`ParsedSection`.

        Parameters:
            end_line: 1-indexed line number of the last line of the section
                (informational; not stored on the dataclass).

        Returns:
            None. Mutates the enclosing ``sections`` list in place.
        """
        if current_name is None or current_start_line is None:
            return
        sections.append(
            ParsedSection(
                name=current_name,
                start_line=current_start_line,
                raw_text="\n".join(current_buffer).rstrip("\n"),
            )
        )

    line_index = 0
    abs_line = 1
    while line_index < len(body_lines):
        raw = body_lines[line_index]
        stripped = raw.lstrip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            heading = stripped[2:].strip()
            # Close the previous section.
            _flush(abs_line - 1)
            current_name = heading
            current_start_line = abs_line
            current_buffer = []
        else:
            if current_name is not None:
                current_buffer.append(raw)
        line_index += 1
        abs_line += 1
    _flush(abs_line)
    return sections


# ---------------------------------------------------------------------------
# Structured parsers for each section
# ---------------------------------------------------------------------------


def _parse_objective(path: Path, section: ParsedSection) -> str:
    text = section.raw_text.strip()
    if not text:
        raise EpisodeParseError(
            "Section 'Objective' must contain at least one paragraph.",
            path=path,
            section="Objective",
            line=section.start_line,
        )
    return text


def _parse_visible_request(path: Path, section: ParsedSection) -> str:
    """Concatenate blockquote (``>``) prefixes into a single visible prompt.

    Leading ``> `` characters and the optional wrapping ``` ``` fences are
    stripped so the model sees clean prose. Plain (non-blockquote) text is
    preserved as-is to support prompt fragments that include inline lists.
    """
    lines = section.raw_text.splitlines()
    cleaned: List[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and stripped.startswith(">"):
            cleaned.append(stripped.lstrip(">").lstrip())
        else:
            cleaned.append(line.rstrip())
    body = "\n".join(cleaned).strip()
    if not body:
        raise EpisodeParseError(
            "Section 'Visible Request' must contain a prompt (block-quoted or plain).",
            path=path,
            section="Visible Request",
            line=section.start_line,
        )
    return body


def _parse_visible_tools(path: Path, section: ParsedSection) -> List[ToolSignature]:
    """Parse the markdown list of tool signatures into typed records."""
    tools: List[ToolSignature] = []
    for offset, raw in enumerate(section.raw_text.splitlines()):
        stripped = raw.strip()
        if not stripped:
            continue
        match = _TOOL_LINE_RE.match(stripped)
        if not match:
            raise EpisodeParseError(
                "Tool declarations must be markdown list items beginning with '- name(...).'",
                path=path,
                section="Visible Tools",
                line=section.start_line + offset,
            )
        signature = match.group("signature").strip()
        sig_match = _TOOL_SIG_RE.match(signature)
        if not sig_match:
            raise EpisodeParseError(
                f"Tool signature {signature!r} does not match 'name(param: type, ...)'.",
                path=path,
                section="Visible Tools",
                line=section.start_line + offset,
            )
        name = sig_match.group("name")
        params_raw = sig_match.group("params").strip()
        description = (
            sig_match.group("desc").strip() if sig_match.group("desc") else None
        )
        parameters: List[Dict[str, str]] = []
        if params_raw:
            for entry in _split_params(params_raw):
                if ":" not in entry:
                    raise EpisodeParseError(
                        f"Tool '{name}' parameter {entry!r} must be 'name: type'.",
                        path=path,
                        section="Visible Tools",
                        line=section.start_line + offset,
                    )
                pname, ptype = entry.split(":", 1)
                pname = pname.strip()
                # Type may include a default-value suffix (e.g. ``str = ""``).
                # Strip everything after the first whitespace once the type
                # identifier has been collected so downstream code receives
                # just the canonical type token.
                ptype = ptype.strip()
                ptype_first_word = ptype.split(None, 1)[0] if ptype else ""
                if not pname or not ptype_first_word:
                    raise EpisodeParseError(
                        f"Tool '{name}' parameter {entry!r} has empty name or type.",
                        path=path,
                        section="Visible Tools",
                        line=section.start_line + offset,
                    )
                parameters.append({"name": pname, "type": ptype_first_word})
        tools.append(
            ToolSignature(
                name=name,
                parameters=parameters,
                description=description,
                line=section.start_line + offset,
            )
        )
    if not tools:
        raise EpisodeParseError(
            "Section 'Visible Tools' must declare at least one tool signature.",
            path=path,
            section="Visible Tools",
            line=section.start_line,
        )
    return tools


def _split_params(raw: str) -> List[str]:
    """Split a tool parameter list on top-level commas only."""
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
    # Filter out empty trailing splits produced by dangling commas.
    return [part for part in parts if part]


def _parse_oracles(path: Path, section: ParsedSection) -> List[OracleClause]:
    clauses: List[OracleClause] = []
    for offset, raw in enumerate(section.raw_text.splitlines()):
        stripped = raw.strip()
        if not stripped:
            continue
        match = _ORACLE_TAG_RE.match(stripped)
        if match:
            clauses.append(
                OracleClause(
                    tag=match.group(2),
                    body=match.group("body").strip(),
                    line=section.start_line + offset,
                )
            )
        else:
            clauses.append(
                OracleClause(
                    tag=None,
                    body=stripped,
                    line=section.start_line + offset,
                )
            )
    if not clauses:
        raise EpisodeParseError(
            "Section 'Deterministic Oracles' must list at least one oracle clause.",
            path=path,
            section="Deterministic Oracles",
            line=section.start_line,
        )
    return clauses


def _parse_rubric(path: Path, section: ParsedSection) -> List[str]:
    """Parse a 1-5 scale semantic rubric from numbered list items."""
    items: List[str] = []
    next_expected = 1
    for offset, raw in enumerate(section.raw_text.splitlines()):
        stripped = raw.strip()
        if not stripped:
            continue
        match = _TRAJECTORY_STEP_RE.match(stripped)
        if not match:
            raise EpisodeParseError(
                "Rubric items must be a numbered list (1. through 5.).",
                path=path,
                section="Semantic Rubric",
                line=section.start_line + offset,
            )
        num = int(match.group("num"))
        text = match.group("text").strip()
        if num != next_expected:
            raise EpisodeParseError(
                f"Rubric items must be sequential starting at 1 (got {num}, expected {next_expected}).",
                path=path,
                section="Semantic Rubric",
                line=section.start_line + offset,
            )
        if not text:
            raise EpisodeParseError(
                "Rubric items must include a description.",
                path=path,
                section="Semantic Rubric",
                line=section.start_line + offset,
            )
        items.append(text)
        next_expected += 1
    if next_expected - 1 != 5:
        raise EpisodeParseError(
            "Semantic Rubric must define exactly 5 levels (1-5).",
            path=path,
            section="Semantic Rubric",
            line=section.start_line,
        )
    return items


def _parse_trajectory(path: Path, section: ParsedSection) -> List[str]:
    """Parse the optional numbered behavioral trajectory."""
    items: List[str] = []
    for offset, raw in enumerate(section.raw_text.splitlines()):
        stripped = raw.strip()
        if not stripped:
            continue
        match = _TRAJECTORY_STEP_RE.match(stripped)
        if not match:
            raise EpisodeParseError(
                "Trajectory steps must be a numbered list ('1. ...').",
                path=path,
                section="Expected Behavioral Trajectory",
                line=section.start_line + offset,
            )
        text = match.group("text").strip()
        if not text:
            raise EpisodeParseError(
                "Trajectory steps must include a description.",
                path=path,
                section="Expected Behavioral Trajectory",
                line=section.start_line + offset,
            )
        items.append(text)
    if not items:
        raise EpisodeParseError(
            "Section 'Expected Behavioral Trajectory' is present but empty.",
            path=path,
            section="Expected Behavioral Trajectory",
            line=section.start_line,
        )
    return items


# ---------------------------------------------------------------------------
# EpisodeParser: from_markdown entrypoint
# ---------------------------------------------------------------------------


@dataclass
class ParsedEpisode:
    """Container that exposes the canonical EpisodeSpec and Inspect Sample."""

    spec: EpisodeSpec
    sample: Sample
    section_blocks: Dict[str, ParsedSection]


class EpisodeParser:
    """Parse a single ``.eds.md`` episode file into a spec + Sample pair."""

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    @classmethod
    def from_markdown(cls, path: Union[str, Path]) -> ParsedEpisode:
        """Read the Markdown file at ``path`` and produce a :class:`ParsedEpisode`."""
        file_path = Path(path)
        try:
            text = file_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise EpisodeParseError(
                f"EDS spec file not found: {exc}.",
                path=file_path,
                line=1,
            ) from exc
        return cls.from_text(text, source=str(file_path))

    @classmethod
    def from_text(cls, text: str, *, source: Union[str, Path, None] = None) -> ParsedEpisode:
        """Parse an in-memory Markdown string (used by tests)."""
        path = Path(source) if source is not None else Path("<memory>")
        try:
            file_path = Path("<memory>") if source is None else Path(source)
            split = _split_frontmatter(file_path, text)
        except EpisodeParseError:
            raise
        # Validate the H1 section roster before any structured parsing runs.
        cls._validate_section_roster(path, split.sections)
        # Fill structured projections on each section.
        section_blocks: Dict[str, ParsedSection] = {}
        for section in split.sections:
            section_blocks[section.name] = section
        if "Objective" in section_blocks:
            section_blocks["Objective"].objective = _parse_objective(
                path, section_blocks["Objective"]
            )
        if "Visible Request" in section_blocks:
            section_blocks["Visible Request"].visible_request = _parse_visible_request(
                path, section_blocks["Visible Request"]
            )
        if "Visible Tools" in section_blocks:
            section_blocks["Visible Tools"].tools = _parse_visible_tools(
                path, section_blocks["Visible Tools"]
            )
        if "Deterministic Oracles" in section_blocks:
            section_blocks["Deterministic Oracles"].oracles = _parse_oracles(
                path, section_blocks["Deterministic Oracles"]
            )
        if "Semantic Rubric" in section_blocks:
            section_blocks["Semantic Rubric"].rubric = _parse_rubric(
                path, section_blocks["Semantic Rubric"]
            )
        if "Expected Behavioral Trajectory" in section_blocks:
            section_blocks["Expected Behavioral Trajectory"].trajectory = _parse_trajectory(
                path, section_blocks["Expected Behavioral Trajectory"]
            )

        spec = cls._build_spec(path, split.frontmatter, section_blocks)
        sample = cls._build_sample(path, spec, section_blocks)
        return ParsedEpisode(spec=spec, sample=sample, section_blocks=section_blocks)

    # ------------------------------------------------------------------
    # Section roster validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_section_roster(path: Path, sections: Sequence[ParsedSection]) -> None:
        """Reject any H1 section that is unknown, duplicated, or required-but-absent.

        Parameters:
            path: File path used to stamp :class:`EpisodeParseError`.
            sections: Parsed H1 sections in arrival order.

        Returns:
            None.

        Raises:
            EpisodeParseError: When an unknown/duplicate section appears or
                when any required section (``Expected Behavioral Trajectory``
                excepted) is missing.
        """
        seen: List[str] = []
        for section in sections:
            if section.name not in KNOWN_SECTIONS:
                raise EpisodeParseError(
                    f"Unknown H1 section {section.name!r}; allowed: "
                    f"{', '.join(KNOWN_SECTIONS)}.",
                    path=path,
                    section=section.name,
                    line=section.start_line,
                )
            if section.name in seen:
                raise EpisodeParseError(
                    f"Section {section.name!r} is declared more than once.",
                    path=path,
                    section=section.name,
                    line=section.start_line,
                )
            seen.append(section.name)
        missing = [
            name for name in KNOWN_SECTIONS
            if name not in seen and name != "Expected Behavioral Trajectory"
        ]
        if missing:
            raise EpisodeParseError(
                f"Missing required sections: {', '.join(missing)}.",
                path=path,
                line=1,
            )

    # ------------------------------------------------------------------
    # EpisodeSpec assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _build_spec(
        path: Path,
        frontmatter: Mapping[str, Any],
        section_blocks: Mapping[str, ParsedSection],
    ) -> EpisodeSpec:
        """Compose a validated ``EpisodeSpec`` from frontmatter and parsed sections.

        Parameters:
            path: File path used for error stamping.
            frontmatter: Decoded YAML mapping.
            section_blocks: Structured H1 sections (used to harvest oracles).

        Returns:
            A fully validated :class:`EpisodeSpec` ready for solver binding.

        Raises:
            EpisodeParseError: When any required frontmatter block is missing
                or violates the Pydantic v2 schema enforced by
                ``EpisodeSpec`` and its dependent models.
        """
        # ----- Identity --------------------------------------------------
        missing_top = [key for key in ("id", "suite", "version") if key not in frontmatter]
        if missing_top:
            raise EpisodeParseError(
                f"Frontmatter missing required top-level keys: {', '.join(missing_top)}.",
                path=path,
                section="<frontmatter>",
                line=1,
            )
        # ----- World fixture --------------------------------------------
        world_block = frontmatter.get("world_fixture")
        if not isinstance(world_block, Mapping):
            raise EpisodeParseError(
                "Frontmatter 'world_fixture' must be a mapping.",
                path=path,
                section="<frontmatter>",
                line=1,
            )
        try:
            world = WorldFixture(
                name=str(world_block.get("name", "")),
                fixture_version=str(world_block.get("fixture_version", "")),
                state=dict(world_block.get("state", {}) or {}),
                entities=EpisodeParser._parse_entities(
                    path, world_block.get("entities", {}) or {}
                ),
            )
        except ValidationError as exc:
            raise EpisodeParseError(
                f"World fixture failed validation: {exc}.",
                path=path,
                section="<frontmatter>",
                line=1,
            ) from exc
        # ----- Actor ---------------------------------------------------
        actor_block = frontmatter.get("actor") or {}
        if not isinstance(actor_block, Mapping):
            raise EpisodeParseError(
                "Frontmatter 'actor' must be a mapping.",
                path=path,
                section="<frontmatter>",
                line=1,
            )
        try:
            actor = Actor(
                principal_id=str(actor_block.get("principal_id", "")),
                roles=list(actor_block.get("roles", []) or []),
                permissions=list(actor_block.get("permissions", []) or []),
            )
        except ValidationError as exc:
            raise EpisodeParseError(
                f"Actor failed validation: {exc}.",
                path=path,
                section="<frontmatter>",
                line=1,
            ) from exc
        # ----- Limits --------------------------------------------------
        limits_block = frontmatter.get("limits") or {}
        if not isinstance(limits_block, Mapping):
            raise EpisodeParseError(
                "Frontmatter 'limits' must be a mapping.",
                path=path,
                section="<frontmatter>",
                line=1,
            )
        try:
            limits = InteractionLimits(
                max_turns=int(limits_block.get("max_turns", 8)),
                max_tool_calls=int(limits_block.get("max_tool_calls", 32)),
                wall_time_seconds=float(limits_block.get("wall_time_seconds", 90.0)),
            )
        except (TypeError, ValueError) as exc:
            raise EpisodeParseError(
                f"Frontmatter 'limits' has invalid values: {exc}.",
                path=path,
                section="<frontmatter>",
                line=1,
            ) from exc
        # ----- Hidden truth --------------------------------------------
        ht_block = frontmatter.get("hidden_truth") or {}
        if not isinstance(ht_block, Mapping):
            raise EpisodeParseError(
                "Frontmatter 'hidden_truth' must be a mapping.",
                path=path,
                section="<frontmatter>",
                line=1,
            )
        try:
            hidden_truth = HiddenTruth(
                ambiguity_candidates=list(ht_block.get("ambiguity_candidates", []) or []),
                required_behavior=list(ht_block.get("required_behavior", []) or []),
                prohibited_actions=list(ht_block.get("prohibited_actions", []) or []),
            )
        except ValidationError as exc:
            raise EpisodeParseError(
                f"Hidden truth failed validation: {exc}.",
                path=path,
                section="<frontmatter>",
                line=1,
            ) from exc
        # ----- Oracles -------------------------------------------------
        oracles = EpisodeParser._collect_oracles(
            path, section_blocks.get("Deterministic Oracles")
        )
        # ----- Metadata ------------------------------------------------
        md_block = frontmatter.get("metadata") or {}
        if not isinstance(md_block, Mapping):
            raise EpisodeParseError(
                "Frontmatter 'metadata' must be a mapping.",
                path=path,
                section="<frontmatter>",
                line=1,
            )
        try:
            metadata = EpisodeMetadata(
                capability=str(md_block.get("capability", "")),
                trap_class=md_block.get("trap_class"),
                difficulty=str(md_block.get("difficulty", "medium")),
                risk_tier=str(md_block.get("risk_tier", "medium")),
                tags=list(md_block.get("tags", []) or []),
            )
        except ValidationError as exc:
            raise EpisodeParseError(
                f"Episode metadata failed validation: {exc}.",
                path=path,
                section="<frontmatter>",
                line=1,
            ) from exc
        # ----- Assembly ------------------------------------------------
        try:
            spec = EpisodeSpec(
                id=str(frontmatter["id"]),
                suite=str(frontmatter["suite"]),
                version=str(frontmatter["version"]),
                world=world,
                actor=actor,
                interaction_limits=limits,
                hidden_truth=hidden_truth,
                oracles=oracles,
                metadata=metadata,
            )
        except ValidationError as exc:
            raise EpisodeParseError(
                f"EpisodeSpec assembly failed: {exc}.",
                path=path,
                section="<frontmatter>",
                line=1,
            ) from exc
        return spec

    @staticmethod
    def _parse_entities(
        path: Path, entities: Mapping[str, Any]
    ) -> Dict[str, TaggedEntity]:
        """Coerce ``world_fixture.entities`` YAML into :class:`TaggedEntity` records.

        Parameters:
            path: File path used for error stamping.
            entities: Raw mapping loaded from the YAML frontmatter; each value
                must itself be a mapping containing ``provenance`` and an
                optional ``payload`` block.

        Returns:
            Mapping of entity key to a fully validated :class:`TaggedEntity`.

        Raises:
            EpisodeParseError: When an entity value is the wrong shape or has
                an unrecognised ``provenance`` token.
        """
        parsed: Dict[str, TaggedEntity] = {}
        for key, value in entities.items():
            if not isinstance(value, Mapping):
                raise EpisodeParseError(
                    f"Entity {key!r} must be a mapping with 'provenance' and optional 'payload'.",
                    path=path,
                    section="<frontmatter>",
                    line=1,
                )
            prov_raw = value.get("provenance", "canonical")
            try:
                provenance = Provenance(str(prov_raw))
            except ValueError as exc:
                raise EpisodeParseError(
                    f"Entity {key!r} has invalid provenance {prov_raw!r}; "
                    f"allowed: {[p.value for p in Provenance]}.",
                    path=path,
                    section="<frontmatter>",
                    line=1,
                ) from exc
            payload = value.get("payload", {}) or {}
            parsed[key] = TaggedEntity(provenance=provenance, payload=dict(payload))
        return parsed

    @staticmethod
    def _collect_oracles(
        path: Path, section: Optional[ParsedSection]
    ) -> List[PolicyRule]:
        """Map the parsed oracle clauses into typed :class:`PolicyRule` records.

        Parameters:
            path: File path used for error stamping.
            section: The parsed ``Deterministic Oracles`` section (optional; an
                empty list is returned if the section is absent).

        Returns:
            A list of :class:`PolicyRule`, one per oracle clause, with
            names guaranteed unique and severity bumped to ``critical`` when
            the clause text contains prohibited-action vocabulary.

        Raises:
            EpisodeParseError: Not raised by this helper directly; underlying
            :class:`PolicyRule` validation will surface in the assembler.
        """
        if section is None or not section.oracles:
            return []
        oracles: List[PolicyRule] = []
        seen: set = set()
        for clause in section.oracles:
            tag = clause.tag or "Trace"
            name = f"{tag.lower()}_oracle_{clause.line}"
            if name in seen:
                # Disambiguate duplicates when multiple untagged clauses share a line range.
                name = f"{name}_{clause.line}_{len(oracles)}"
            seen.add(name)
            predicate = _oracle_predicate(tag, clause.body)
            critical = tag == "Policy" or _looks_critical(clause.body)
            oracles.append(
                PolicyRule(
                    name=name,
                    severity="critical" if critical else "normal",
                    predicate=predicate,
                )
            )
        return oracles

    # ------------------------------------------------------------------
    # Inspect Sample assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _build_sample(
        path: Path,
        spec: EpisodeSpec,
        section_blocks: Mapping[str, ParsedSection],
    ) -> Sample:
        """Build an :class:`inspect_ai.dataset.Sample` wrapping the visible prompt.

        Parameters:
            path: File path used for error stamping.
            spec: The validated episode spec whose ``id`` is propagated to the
                sample identity.
            section_blocks: Parsed H1 sections from the spec file.

        Returns:
            A :class:`Sample` whose ``input`` is the cleaned visible request
            and whose ``metadata`` carries the full spec, all section blocks,
            tool inventory, oracle clauses, rubric, and trajectory.

        Raises:
            EpisodeParseError: If the ``Visible Request`` section cannot be
                surfaced as a string (defensive check — the parser normally
                raises earlier on empty bodies).
        """
        request_section = section_blocks["Visible Request"]
        if request_section.visible_request is None:
            # Should be unreachable because _parse_visible_request raises on empty bodies.
            raise EpisodeParseError(
                "Visible Request section produced no prompt text.",
                path=path,
                section="Visible Request",
                line=request_section.start_line,
            )
        metadata_payload: Dict[str, Any] = {
            "eds_spec": spec.model_dump(mode="json"),
            "eds_sections": {
                name: _serialise_section(section_blocks[name])
                for name in section_blocks
            },
            "eds_visible_tools": [
                {
                    "name": tool.name,
                    "parameters": list(tool.parameters),
                    "description": tool.description,
                    "line": tool.line,
                }
                for tool in (
                    section_blocks["Visible Tools"].tools
                    if "Visible Tools" in section_blocks
                    else []
                )
            ],
            "eds_oracle_clauses": [
                {
                    "tag": clause.tag,
                    "body": clause.body,
                    "line": clause.line,
                }
                for clause in (
                    section_blocks["Deterministic Oracles"].oracles
                    if "Deterministic Oracles" in section_blocks
                    else []
                )
            ],
            "eds_rubric": (
                section_blocks["Semantic Rubric"].rubric
                if "Semantic Rubric" in section_blocks
                else []
            ),
            "eds_trajectory": (
                section_blocks["Expected Behavioral Trajectory"].trajectory
                if "Expected Behavioral Trajectory" in section_blocks
                else []
            ),
        }
        return Sample(
            input=request_section.visible_request,
            id=spec.id,
            metadata=metadata_payload,
        )


# ---------------------------------------------------------------------------
# Helpers (oracle serialisation, predicate synthesis, section serialisation)
# ---------------------------------------------------------------------------


def _oracle_predicate(tag: str, body: str) -> str:
    """Render a structured predicate string the runtime can dispatch on.

    Strips a leading list marker (``-``) so the predicate is just the clause
    text prefixed by the tag namespace (``trace:`` / ``state:`` / ``output:``
    / ``budget:``).
    """
    cleaned = body.strip()
    if cleaned.startswith("-"):
        cleaned = cleaned[1:].lstrip()
    cleaned = cleaned.rstrip(".").rstrip()
    return f"{tag.lower()}:{cleaned}"


_CRITICAL_KEYWORDS = (
    "policy_violation",
    "prohibited",
    "forbidden",
    "never",
    "must_not",
)


def _looks_critical(body: str) -> bool:
    lowered = body.lower()
    return any(keyword in lowered for keyword in _CRITICAL_KEYWORDS)


def _serialise_section(section: ParsedSection) -> Dict[str, Any]:
    """Render one ``ParsedSection`` as a JSON-safe dict for sample metadata."""
    return {
        "name": section.name,
        "start_line": section.start_line,
        "raw_text": section.raw_text,
        "objective": section.objective,
        "visible_request": section.visible_request,
        "tools": [
            {
                "name": tool.name,
                "parameters": list(tool.parameters),
                "description": tool.description,
                "line": tool.line,
            }
            for tool in section.tools
        ],
        "oracles": [
            {"tag": clause.tag, "body": clause.body, "line": clause.line}
            for clause in section.oracles
        ],
        "rubric": list(section.rubric),
        "trajectory": list(section.trajectory),
    }


__all__ = [
    "EpisodeParser",
    "EpisodeParseError",
    "KNOWN_SECTIONS",
    "OracleClause",
    "ParsedEpisode",
    "ParsedSection",
    "ToolSignature",
]
