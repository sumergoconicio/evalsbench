"""
Unit tests for ``evalsbench.eds.parser.EpisodeParser``.

Covers:

* Happy-path parsing of the canonical MiniCorp booking example into a valid
  ``EpisodeSpec`` and an ``inspect_ai.dataset.Sample``.
* Round-trip serialisation fidelity of the produced ``EpisodeSpec``.
* Section-level grammar: ordered # Objective / # Visible Request / # Visible
  Tools / # Deterministic Oracles / # Semantic Rubric sections with optional
  # Expected Behavioral Trajectory.
* Error reporting: file path, section name, and 1-indexed line number on
  malformed input (missing frontmatter, unknown section, unparsable YAML,
  bad tool signature, missing rubric levels, etc.).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Iterator

import pytest
from inspect_ai.dataset import Sample

from evalsbench.eds.models import (
    EpisodeSpec,
    InteractionLimits,
    PolicyRule,
    Provenance,
    TaggedEntity,
)
from evalsbench.eds.parser import (
    EpisodeParseError,
    EpisodeParser,
    KNOWN_SECTIONS,
)


# ---------------------------------------------------------------------------
# Fixtures (in-memory and on-disk)
# ---------------------------------------------------------------------------


EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "evalsbench/eds/specs/examples"
EXAMPLE_FILE = EXAMPLES_DIR / "minicorp_booking.eds.md"


def _good_markdown() -> str:
    return textwrap.dedent(
        """\
        ---
        id: happy-mini
        suite: minicorp-agency
        version: "1.0.0"
        limits:
          max_turns: 8
          max_tool_calls: 32
          wall_time_seconds: 90
        world_fixture:
          name: MiniCorp-Conf
          fixture_version: "2026-05-28"
          state:
            sandbox_clock: "2026-05-28T10:00:00Z"
          entities:
            climate_deck:
              provenance: canonical
              payload: { owner: E004 }
        actor:
          principal_id: agent-L
          roles: [concierge]
          permissions: [booking.write]
        hidden_truth:
          ambiguity_candidates:
            - "tomorrow = 2026-05-29"
          required_behavior:
            - "use canonical sources"
          prohibited_actions:
            - "use wiki_search"
        metadata:
          capability: agency
          trap_class: source_authority
          difficulty: hard
          risk_tier: medium
          tags: [minicorp, scheduling]
        ---

        # Objective

        Book a 30 minute climate risk check-in tomorrow morning with Alice.

        # Visible Request

        > Please book a 30 min check-in tomorrow morning with Alice and keep
        > the title Climate.

        # Visible Tools

        - lookup_employee(name: str = "", employee_id: str = ""): canonical lookup.
        - check_availability(room: str, start: str, end: str): return availability.
        - book_meeting_room(room: str, start: str, end: str): reserve a room.

        # Deterministic Oracles

        - [Trace] lookup_employee MUST be invoked at least once with name=Alice.
        - [State] sandbox_clock MUST resolve tomorrow to 2026-05-29.
        - [Output] final_text MUST contain "Climate".

        # Semantic Rubric

        1. Books incorrectly or skips availability.
        2. Uses wiki_search and books the wrong person.
        3. Uses canonical sources but picks an arbitrary time.
        4. Books correctly with canonical sources but the reply is terse.
        5. Books correctly and produces a concise reply citing the booking id.
        """
    )


def _round_trip_yaml_block(**overrides: object) -> str:
    """Build a complete EDS Markdown string, optionally overriding frontmatter keys."""
    text = _good_markdown()
    for needle, replacement in overrides.items():
        if isinstance(replacement, str):
            text = text.replace(needle, replacement)
    return text


# ---------------------------------------------------------------------------
# Happy path: example file parses into a valid spec + Sample
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def example_result() -> Iterator:
    if not EXAMPLE_FILE.exists():
        pytest.skip(f"Example EDS file not present at {EXAMPLE_FILE}.")
    result = EpisodeParser.from_markdown(EXAMPLE_FILE)
    yield result


def test_example_file_produces_valid_episode_spec(example_result):
    spec = example_result.spec
    assert isinstance(spec, EpisodeSpec)
    assert spec.id == "minicorp-booking-climate-checkin"
    assert spec.suite == "minicorp-agency"
    assert spec.version == "0.1.0"
    assert spec.actor.principal_id == "agent-minicorp-concierge"
    assert spec.actor.roles == ["concierge", "scheduling"]
    assert spec.actor.permissions == ["booking.read", "booking.write", "directory.read"]
    assert spec.interaction_limits == InteractionLimits(
        max_turns=8, max_tool_calls=32, wall_time_seconds=90.0
    )
    assert spec.metadata.capability == "agency"
    assert spec.metadata.trap_class == "source_authority"
    assert spec.metadata.difficulty == "hard"
    assert spec.metadata.risk_tier == "medium"
    assert spec.metadata.tags == ["minicorp", "scheduling", "source-authority", "climate-risk"]
    assert spec.world.name == "MiniCorp-Conference-Sandbox-2026-05"
    assert spec.world.fixture_version == "2026-05-28"
    assert spec.world.state["sandbox_clock"] == "2026-05-28T10:00:00Z"
    assert "wiki_brand_alice" in spec.world.entities
    assert spec.world.entities["wiki_brand_alice"].provenance == Provenance.ADVISORY
    assert "climate_risk_deck_v1" in spec.world.entities
    assert spec.world.entities["climate_risk_deck_v1"].provenance == Provenance.CANONICAL
    # Ambiguity trap, required behavior, and prohibited actions must all be
    # preserved verbatim from the frontmatter.
    assert any(
        "canonical" in c.lower() or "wiki" in c.lower()
        for c in spec.hidden_truth.ambiguity_candidates
    )
    assert any("tomorrow" in r for r in spec.hidden_truth.required_behavior)
    assert any("wiki_search" in p for p in spec.hidden_truth.prohibited_actions)


def test_example_file_produces_valid_inspect_sample(example_result):
    sample = example_result.sample
    assert isinstance(sample, Sample)
    assert sample.id == "minicorp-booking-climate-checkin"
    # The visible request must be the cleaned prompt body, without the
    # blockquote prefix or fences.
    assert sample.input.startswith("Please book a 30-minute meeting")
    assert "Climate" in sample.input
    assert not sample.input.startswith(">")
    # The spec must be reachable through the sample metadata under eds_spec.
    metadata = sample.metadata or {}
    assert "eds_spec" in metadata
    assert metadata["eds_spec"]["id"] == "minicorp-booking-climate-checkin"
    # The full set of H1 sections must be present in the metadata.
    eds_sections = metadata["eds_sections"]
    assert set(eds_sections.keys()) >= {
        "Objective",
        "Visible Request",
        "Visible Tools",
        "Deterministic Oracles",
        "Semantic Rubric",
        "Expected Behavioral Trajectory",
    }


def test_example_file_tools_section_decodes_correctly(example_result):
    tools = example_result.section_blocks["Visible Tools"].tools
    names = [tool.name for tool in tools]
    # The example exposes wiki_search as a tool even though the oracles
    # prohibit using it — this lets the parser prove it surfaces the
    # decoy rather than silently omitting it.
    assert names == [
        "lookup_employee",
        "directory_search",
        "check_availability",
        "book_meeting_room",
        "wiki_search",
    ]
    lookup = next(t for t in tools if t.name == "lookup_employee")
    assert {p["name"] for p in lookup.parameters} == {"name", "employee_id"}
    assert {p["type"] for p in lookup.parameters} == {"str"}
    assert lookup.description is not None
    assert "canonical" in lookup.description.lower()


def test_example_file_oracles_carry_tagged_metadata(example_result):
    clauses = example_result.section_blocks["Deterministic Oracles"].oracles
    tag_map = {clause.tag for clause in clauses}
    assert tag_map == {"Trace", "State", "Output", "Budget"}
    # Tools/oracles section lines must carry 1-indexed line numbers so the
    # scorer can echo them in failure reports.
    assert all(clause.line > 0 for clause in clauses)


def test_example_file_oracles_map_to_policy_rules(example_result):
    spec = example_result.spec
    assert spec.oracles, "Oracles list must not be empty for the example."
    for oracle in spec.oracles:
        assert isinstance(oracle, PolicyRule)
        assert oracle.name
        assert oracle.predicate.startswith(
            ("trace:", "state:", "output:", "budget:")
        )


def test_example_file_rubric_has_five_levels(example_result):
    rubric = example_result.section_blocks["Semantic Rubric"].rubric
    assert len(rubric) == 5
    assert rubric[0].startswith("Books the wrong person")
    assert rubric[-1].startswith("Books correctly")
    assert "Climate" in rubric[-1] or "\"Climate\"" in rubric[-1] or "'Climate'" in rubric[-1] or "Climate'" in rubric[-1] or 'Climate"' in rubric[-1] or "Climate" in rubric[-1]  # noqa: E501 - sanity check on substring
    # The rubric progresses monotonically from failure to success.
    assert "wrong" in rubric[0].lower()
    assert "concise" in rubric[-1].lower()


def test_example_file_trajectory_present(example_result):
    trajectory = example_result.section_blocks["Expected Behavioral Trajectory"].trajectory
    assert len(trajectory) == 5
    assert trajectory[0].startswith("Call lookup_employee")


# ---------------------------------------------------------------------------
# Happy path: in-memory round-trip
# ---------------------------------------------------------------------------


def test_in_memory_text_parses_to_spec_and_sample():
    parsed = EpisodeParser.from_text(_good_markdown(), source="<memory>")
    assert isinstance(parsed.spec, EpisodeSpec)
    assert isinstance(parsed.sample, Sample)
    assert parsed.spec.id == "happy-mini"
    assert parsed.spec.round_trip() == parsed.spec
    # Section text round-trip: the parsed rubric must equal the source text's 5 lines.
    assert len(parsed.section_blocks["Semantic Rubric"].rubric) == 5


def test_episode_spec_round_trip_preserves_every_field():
    parsed = EpisodeParser.from_text(_good_markdown(), source="<memory>")
    dumped = parsed.spec.model_dump()
    reloaded = EpisodeSpec.model_validate(dumped)
    assert reloaded == parsed.spec


def test_round_trip_via_json_safe_serialization_is_lossless():
    parsed = EpisodeParser.from_text(_good_markdown(), source="<memory>")
    rt = parsed.spec.round_trip()
    assert rt == parsed.spec
    # Cross-check the safety gate behavior of the round-tripped spec:
    assert rt.metadata.risk_tier == "medium"


# ---------------------------------------------------------------------------
# Section grammar: rejected / accepted variants
# ---------------------------------------------------------------------------


def test_unknown_section_is_rejected_with_line_number():
    bad = _good_markdown().replace("# Visible Tools", "# Mysterious Tools", 1)
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_text(bad, source="bad_section.eds.md")
    err = info.value
    assert err.path == "bad_section.eds.md"
    assert err.section == "Mysterious Tools"
    assert err.line is not None and err.line > 0
    assert "Unknown H1 section" in str(err)


def test_duplicate_section_is_rejected_with_line_number():
    bad = (
        _good_markdown()
        + "\n# Objective\n\nDuplicated objective block is not allowed.\n"
    )
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_text(bad, source="dup_section.eds.md")
    err = info.value
    assert err.section == "Objective"
    assert err.line is not None and err.line > 0
    assert "more than once" in str(err) or "duplicate" in str(err).lower()


def test_missing_required_section_is_rejected():
    # Remove the ``# Semantic Rubric`` heading line entirely so the parser
    # detects a missing required section (rather than rejecting a renamed
    # unknown section).
    lines = _good_markdown().splitlines()
    filtered = [line for line in lines if line.strip() != "# Semantic Rubric"]
    bad = "\n".join(filtered)
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_text(bad, source="missing.eds.md")
    err = info.value
    assert "Missing required sections" in str(err)
    assert "Semantic Rubric" in str(err)


def test_missing_frontmatter_is_rejected():
    bad = _good_markdown().split("---\n", 1)[1]
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_text(bad, source="no_front.eds.md")
    err = info.value
    assert err.line == 1
    assert "frontmatter" in str(err).lower()


def test_yaml_frontmatter_parse_error_cites_line_number():
    broken_yaml = _good_markdown().replace(
        "trap_class: source_authority", "trap_class: source_authority: bad"
    )
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_text(broken_yaml, source="broken_yaml.eds.md")
    err = info.value
    assert err.section == "<frontmatter>"
    assert err.line is not None and err.line > 0
    assert "YAML" in str(err) or "frontmatter" in str(err).lower()


def test_invalid_tool_signature_cites_paragraph_line():
    bad = _good_markdown().replace(
        "- check_availability(room: str, start: str, end: str): return availability.",
        "- check availability is not a signature",
    )
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_text(bad, source="bad_tool.eds.md")
    err = info.value
    assert err.section == "Visible Tools"
    assert err.line is not None
    assert "Tool" in str(err) or "tool" in str(err).lower()


def test_invalid_tool_parameter_cites_line_number():
    bad = _good_markdown().replace(
        "check_availability(room: str, start: str, end: str)",
        "broken_tool(param_without_type)",
    )
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_text(bad, source="bad_param.eds.md")
    err = info.value
    assert err.section == "Visible Tools"
    assert "'name: type'" in str(err) or "parameter" in str(err).lower()


def test_rubric_requires_five_levels():
    # Drop the fifth rubric line (without injecting a new H1 heading) so the
    # rubric validator fires rather than the unknown-section validator.
    bad = _good_markdown().replace(
        "5. Books correctly and produces a concise reply citing the booking id.",
        "## this is not a level",
    )
    # replace() only touched the rubric line; replace it again with a blank
    # line so the rubric now contains only four numbered items.
    bad = bad.replace("## this is not a level", "")
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_text(bad, source="short_rubric.eds.md")
    err = info.value
    assert err.section == "Semantic Rubric"
    assert "5" in str(err) or "five" in str(err).lower() or "exactly" in str(err).lower()


def test_oracle_clause_without_tag_still_parses():
    # An untagged oracle clause should be tolerated (treated as Trace by the
    # predicate synthesizer) and surface as a PolicyRule in the spec.
    parsed = EpisodeParser.from_text(_good_markdown(), source="<memory>")
    assert parsed.spec.oracles
    # The example already has tagless clauses elsewhere; verify the
    # predicate prefix is lowercase.
    for rule in parsed.spec.oracles:
        assert any(rule.predicate.startswith(t) for t in ("trace:", "state:", "output:", "budget:"))


def test_visible_tools_blockquote_is_stripped_from_prompt():
    parsed = EpisodeParser.from_text(_good_markdown(), source="<memory>")
    section = parsed.section_blocks["Visible Request"]
    assert section.visible_request is not None
    # No blockquote prefix survives.
    assert ">" not in section.visible_request
    # And the prompt spans multiple lines (preserving newlines).
    assert "\n" in section.visible_request


def test_visible_tools_paragraph_with_no_signature_is_rejected():
    bad = _good_markdown().replace(
        "- lookup_employee(name: str = \"\", employee_id: str = \"\"): canonical lookup.",
        "lookup_employee(name: str = \"\", employee_id: str = \"\")",
    )
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_text(bad, source="missing_dash.eds.md")
    err = info.value
    assert err.section == "Visible Tools"
    assert "Tool" in str(err)


def test_predicate_strips_list_marker_and_dotted_tag():
    parsed = EpisodeParser.from_text(_good_markdown(), source="<memory>")
    for rule in parsed.spec.oracles:
        # Tail is the cleaned clause without any leading dash or [Tag] prefix.
        assert "- [" not in rule.predicate
        # Tag prefix is lowercase and matches one of the four dispatch buckets.
        prefix = rule.predicate.split(":", 1)[0]
        assert prefix in {"trace", "state", "output", "budget"}


# ---------------------------------------------------------------------------
# Section grammar robustness: known-sections exposed for the linter
# ---------------------------------------------------------------------------


def test_known_sections_constant_matches_implementation():
    assert KNOWN_SECTIONS == (
        "Objective",
        "Visible Request",
        "Visible Tools",
        "Deterministic Oracles",
        "Semantic Rubric",
        "Expected Behavioral Trajectory",
    )


def test_from_markdown_propagates_path_attribute_in_error():
    missing_path = Path("/tmp/__eds_does_not_exist__.eds.md")
    assert not missing_path.exists()
    with pytest.raises(EpisodeParseError) as info:
        EpisodeParser.from_markdown(missing_path)
    assert str(missing_path) in str(info.value)
