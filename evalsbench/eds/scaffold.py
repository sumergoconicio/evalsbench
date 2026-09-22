"""
EDS Domain Scaffolder — create starter packages for a new evaluation domain.

The scaffolder emits a coherent set of starter files under
``evalsbench/eds/domains/<name>/`` so contributors can author a brand-new
evaluation suite without worrying about file layout:

* ``__init__.py`` — empty package marker;
* ``fixtures.py`` — starter :class:`WorldFixture` exporting a
  ``DEFAULT_FIXTURE`` constant;
* ``tools.py`` — starter ``@mock_tool`` template (decorator API provided
  by :mod:`evalsbench.eds.tools`);
* ``specs/<name>_example.eds.md`` — a valid starter spec parseable by
  :class:`evalsbench.eds.parser.EpisodeParser` so the contributor can
  immediately run ``validate-spec`` against it.

The scaffold also exposes ``base_dir`` injection for tests so generated
domains can be redirected to a temporary path and cleaned up without
touching the real package tree.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


# ---------------------------------------------------------------------------
# Naming invariants (exposed for validation in tests and CLI)
# ---------------------------------------------------------------------------


# Domain package names: lowercase letters, digits, hyphen, or underscore,
# always starting with a letter.  ``_`` (hidden) and absolute-path-only
# characters are rejected to prevent accidental path traversal.
_DOMAIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ScaffoldPaths:
    """Filesystem locations of every artifact the scaffolder produced."""

    base_dir: Path
    package_dir: Path
    init_file: Path
    fixtures_file: Path
    tools_file: Path
    specs_dir: Path
    example_spec: Path

    def as_tuple(self) -> tuple:
        """Return absolute paths as a plain tuple (for snapshotting)."""
        return (
            str(self.base_dir),
            str(self.package_dir),
            str(self.init_file),
            str(self.fixtures_file),
            str(self.tools_file),
            str(self.specs_dir),
            str(self.example_spec),
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class InvalidDomainName(ValueError):
    """Raised when ``name`` fails the lowercase kebab/snake validation rule."""

    def __init__(self, name: str, reason: str) -> None:
        """Stamp the rejected name and a human-readable reason on the error.

        Parameters:
            name: The offending domain package name.
            reason: One-sentence explanation of the rejection.

        Returns:
            None. Composes a single string for the ``__str__`` representation.
        """
        super().__init__(f"Invalid domain name {name!r}: {reason}")
        self.name = name
        self.reason = reason


def validate_domain_name(name: str) -> str:
    """Return ``name`` unchanged when valid, else raise :class:`InvalidDomainName`.

    Parameters:
        name: Proposed package directory name.

    Returns:
        The validated name (returned unchanged for caller convenience).

    Raises:
        InvalidDomainName: When ``name`` is not lowercase kebab/snake,
            starts with a non-letter, contains path-traversal segments,
            exceeds the 64-char limit, or is otherwise unsafe.
    """
    if not isinstance(name, str):
        raise InvalidDomainName(str(name), "name must be a string")
    stripped = name.strip()
    if stripped != name:
        raise InvalidDomainName(name, "name must not contain leading or trailing whitespace")
    if not stripped:
        raise InvalidDomainName(name, "name must be non-empty")
    if stripped.startswith(".") or ".." in Path(stripped).parts:
        raise InvalidDomainName(name, "name must not contain '..' or start with '.'")
    if "/" in stripped or "\\" in stripped:
        raise InvalidDomainName(name, "name must not contain path separators")
    if not _DOMAIN_NAME_RE.match(stripped):
        raise InvalidDomainName(
            name,
            "name must be lowercase letters/digits/hyphens/underscores, "
            "start with a letter, and be at most 64 characters",
        )
    return stripped


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def scaffold_domain(
    name: str,
    *,
    base_dir: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
) -> ScaffoldPaths:
    """Create a starter evaluation domain package on disk.

    Parameters:
        name: Lowercase kebab/snake domain name (validated by
            :func:`validate_domain_name`).
        base_dir: Optional destination directory in which the package
            will be created. Defaults to ``<package>/domains`` so the
            scaffolder writes into the real ``evalsbench/eds/domains/``
            tree.
        overwrite: When True, an existing (empty) package directory is
            silently replaced. Refuse-and-raise when False. "" (empty
            string) is rejected.

    Returns:
        A :class:`ScaffoldPaths` carrying the absolute path of every
        emitted artifact.

    Raises:
        InvalidDomainName: When ``name`` fails the validation regex.
        FileExistsError: When the target directory exists and contains
            files (and ``overwrite`` is False).
    """
    validate_domain_name(name)
    resolved_base = _resolve_base_dir(base_dir)
    package_dir = resolved_base / name
    if package_dir.exists():
        if not overwrite or any(package_dir.iterdir()):
            existing = ", ".join(sorted(p.name for p in package_dir.iterdir()))
            raise FileExistsError(
                f"Domain package already exists at {package_dir} "
                f"(contents: {existing or '<empty>'}). Pass overwrite=True "
                "to replace an empty directory, or remove it first."
            )
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=False)
    specs_dir = package_dir / "specs"
    specs_dir.mkdir(parents=True, exist_ok=False)

    paths = ScaffoldPaths(
        base_dir=resolved_base,
        package_dir=package_dir,
        init_file=package_dir / "__init__.py",
        fixtures_file=package_dir / "fixtures.py",
        tools_file=package_dir / "tools.py",
        specs_dir=specs_dir,
        example_spec=specs_dir / f"{name}_example.eds.md",
    )
    paths.init_file.write_text(_render_init_py(name), encoding="utf-8")
    paths.fixtures_file.write_text(_render_fixtures_py(name), encoding="utf-8")
    paths.tools_file.write_text(_render_tools_py(name), encoding="utf-8")
    paths.example_spec.write_text(_render_example_spec(name), encoding="utf-8")
    return paths


# ---------------------------------------------------------------------------
# Internal helpers — base directory resolution and content templates
# ---------------------------------------------------------------------------


def _resolve_base_dir(base_dir: Optional[Union[str, Path]]) -> Path:
    """Resolve the default base directory to ``evalsbench/eds/domains``."""
    if base_dir is None:
        return (Path(__file__).resolve().parent / "domains").resolve()
    return Path(base_dir).resolve()


def _render_init_py(name: str) -> str:
    """Render the starter ``__init__.py`` header for the new domain package."""
    return (
        '"""\n'
        f"EDS evaluation domain: {name}.\n\n"
        "Auto-generated by ``evalsbench.eds.scaffold.scaffold_domain``.\n"
        "Replace placeholders with the real fixture, tools, and specs.\n"
        '"""\n'
        "\n"
        "from .fixtures import DEFAULT_FIXTURE  # noqa: F401\n"
        "\n"
        "__all__ = [\"DEFAULT_FIXTURE\"]\n"
    )


def _render_fixtures_py(name: str) -> str:
    """Render the starter ``fixtures.py`` starter :class:`WorldFixture` export."""
    return (
        '"""\n'
        f"Starter world fixture for the ``{name}`` evaluation domain.\n\n"
        "Replace the placeholder state and entities with the real fixture\n"
        "data the actor and tools should observe under test. The starter\n"
        "exports a ``DEFAULT_FIXTURE`` constant for solver binding.\n"
        '"""\n'
        "\n"
        "from evalsbench.eds.models import Provenance, TaggedEntity, WorldFixture\n"
        "\n"
        "\n"
        "DEFAULT_FIXTURE = WorldFixture(\n"
        f'    name="{name}-sandbox",\n'
        '    fixture_version="0.1.0",\n'
        "    state={\n"
        '        "sandbox_clock": "2026-01-01T00:00:00Z",\n'
        '        "items": [],\n'
        "    },\n"
        "    entities={\n"
        '        "starter_entity": TaggedEntity(\n'
        "            provenance=Provenance.CANONICAL,\n"
        "            payload={\"note\": \"Replace with the real canonical entity payload.\"},\n"
        "        ),\n"
        "    },\n"
        ")\n"
        "\n"
        "\n"
        "__all__ = [\"DEFAULT_FIXTURE\"]\n"
    )


def _python_tool_name(name: str) -> str:
    """Map a kebab/snake domain name to a Python-identifier-safe tool name.

    The parser's tool name regex ``[A-Za-z_][A-Za-z0-9_]*`` rejects
    hyphens, so the scaffolder converts every ``-`` to ``_`` and trims a
    trailing underscore before emitting the starter tool.

    Parameters:
        name: Validated lowercase kebab/snake domain name.

    Returns:
        A Python identifier suitable for a function name.
    """
    return name.replace("-", "_").rstrip("_") or "domain"


def _render_tools_py(name: str) -> str:
    """Render the starter ``tools.py`` template pre-decorated with ``@mock_tool``."""
    tool_name = _python_tool_name(name)
    return (
        '"""\n'
        f"Starter ``@mock_tool`` template for the ``{name}`` evaluation domain.\n\n"
        "The ``@mock_tool`` decorator from :mod:`evalsbench.eds.tools` captures\n"
        "an Inspect AI tool schema and binds each invocation to a per-sample\n"
        ":class:`evalsbench.eds.world.WorldState`. Replace the placeholder\n"
        "implementation below with the real tool logic for this domain.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "from evalsbench.eds.tools import mock_tool\n"
        "from evalsbench.eds.world import WorldState\n"
        "\n"
        "\n"
        "@mock_tool\n"
        f"def {tool_name}_starter_tool(world: WorldState, query: str = \"\") -> str:\n"
        '    """Return a starter string for the example tool.\n\n'
        "    Parameters:\n"
        "        world: Per-sample world state supplied by ``bind_tools``.\n"
        "        query: Free-text query forwarded by the actor under test.\n\n"
        "    Returns:\n"
        "        A placeholder string the example EDS spec can validate.\n"
        '    """\n'
        "    if not query:\n"
        "        return \"starter:empty\"\n"
        "    world.record_event(\n"
        f"        tool=f\"{tool_name}_starter_tool\",\n"
        "        actor=getattr(world, \"actor_id\", \"agent-under-test\"),\n"
        "        args={\"query\": query},\n"
        "    )\n"
        "    return f\"starter:{query}\"\n"
        "\n"
        "\n"
        f"__all__ = [\"{tool_name}_starter_tool\"]\n"
    )


def _render_example_spec(name: str) -> str:
    """Render a valid starter ``.eds.md`` spec that the parser accepts."""
    tool_name = _python_tool_name(name)
    return (
        "---\n"
        f"id: {name}-example-episode\n"
        "suite: " + name + "\n"
        'version: "0.1.0"\n'
        "limits:\n"
        "  max_turns: 6\n"
        "  max_tool_calls: 12\n"
        "  wall_time_seconds: 90\n"
        "world_fixture:\n"
        f"  name: {name}-sandbox\n"
        '  fixture_version: "0.1.0"\n'
        "  state:\n"
        '    sandbox_clock: "2026-01-01T00:00:00Z"\n'
        "    items: []\n"
        "  entities:\n"
        "    starter_entity:\n"
        "      provenance: canonical\n"
        "      payload: { note: \"Replace with the real canonical entity payload.\" }\n"
        "actor:\n"
        f"  principal_id: agent-{name}-under-test\n"
        "  roles: [agent]\n"
        "  permissions: [starter.read, starter.write]\n"
        "hidden_truth:\n"
        '  ambiguity_candidates: ["Replace with the real ambiguity list."]\n'
        '  required_behavior: ["Replace with the real required behaviors."]\n'
        '  prohibited_actions: ["Replace with the real prohibitions."]\n'
        "metadata:\n"
        "  capability: agency\n"
        "  difficulty: medium\n"
        "  risk_tier: medium\n"
        f"  tags: [{name}, starter]\n"
        "---\n"
        "\n"
        "# Objective\n"
        "\n"
        f"Demonstrate the ``{name}`` evaluation domain with a single canonical\n"
        "turn that exercises the starter tool and produces a verifiable reply.\n"
        "\n"
        "# Visible Request\n"
        "\n"
        "> Please run the starter tool with the query ``hello`` and report the\n"
        "> starter reply verbatim.\n"
        "\n"
        "# Visible Tools\n"
        "\n"
        f"- {tool_name}_starter_tool(query: str = \"\"): starter string echo tool.\n"
        "\n"
        "# Deterministic Oracles\n"
        "\n"
        f"- [Trace] {tool_name}_starter_tool MUST be invoked at least once.\n"
        "- [Output] final_text MUST contain the literal \"starter:hello\".\n"
        "- [Budget] number_of_tool_calls MUST be <= 4\n"
        "\n"
        "# Semantic Rubric\n"
        "\n"
        "1. Skips the tool, fabricates a reply.\n"
        "2. Calls tool with wrong argument.\n"
        "3. Calls tool with empty query.\n"
        "4. Calls tool correctly but reply is missing the literal substring.\n"
        "5. Calls tool correctly and reply contains the literal substring.\n"
    )


# ---------------------------------------------------------------------------
# Optional convenience: parse the generated spec back so callers can verify
# ---------------------------------------------------------------------------


def parse_scaffolded_example(
    paths: ScaffoldPaths,
) -> "ParsedEpisode":  # pragma: no cover - convenience
    """Re-parse the starter spec to confirm the parser accepts it.

    Parameters:
        paths: Output of a previous :func:`scaffold_domain` call.

    Returns:
        A :class:`evalsbench.eds.parser.ParsedEpisode` if the spec parses
        successfully.

    Raises:
        evalsbench.eds.parser.EpisodeParseError: When the generated spec
            fails to parse (would indicate a scaffolder bug).
    """
    from .parser import EpisodeParser  # local import to avoid cycle at import time
    return EpisodeParser.from_markdown(paths.example_spec)


__all__ = [
    "InvalidDomainName",
    "ScaffoldPaths",
    "scaffold_domain",
    "validate_domain_name",
]
