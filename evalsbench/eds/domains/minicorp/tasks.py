"""
MiniCorp EDS ``@task`` factory for the EvalsBench EDS subpackage.

File:    evalsbench/eds/domains/minicorp/tasks.py
Module:  evalsbench.eds.domains.minicorp
Purpose: Compile the 16-scenario MiniCorp suite ported verbatim from
         ``lukes-agency/agency_bench.py`` into a single Inspect AI
         ``@task`` factory that:

         * Emits one ``Sample`` per scenario with the canonical
           prompt as user ``input`` and the scenario's deterministic
           oracle as ``metadata['oracle_spec']``.
         * Resolves the per-sample :class:`EpisodeSpec` from the
           canonical :func:`minicorp_fixture` so each sample boots
           with a copy-on-write ``WorldState`` seeded from the same
           employee roster / rate table / wiki / booking-list /
           sandbox clock the legacy harness used.
         * Drives the agent loop through
           :func:`eds_agent_solver` bound to the eight
           :data:`~evalsbench.eds.domains.minicorp.MINICORP_TOOLS`
           with per-sample ``InteractionLimits`` (8 turns max,
           90-second wall clock) and the verbatim system prompt
           from the agency_bench source. Hardware telemetry
           (TTFT, decode TPS, MTP acceptance) is captured per
           sample by the solver's default-on :class:`~evalsbench.eds.telemetry.TelemetryCollector`
           and stamped onto ``state.metadata['telemetry']``.
         * Scores every sample through the
           :func:`tri_axis <evalsbench.eds.scorers.tri_axis.tri_axis>`
           scorer.
         * Aggregates the per-sample telemetry envelopes into the
           run-level ``eds_telemetry`` Inspect ``@metric`` so
           dashboards can read median TTFT, median decode TPS,
           and median MTP draft acceptance without per-task
           wiring.

The oracle schema mirrors the legacy lambda checkers:
``booking_args`` for room reservations,
``text_content`` for single-term lookups,
``text_or_names`` for "list at least one of" prompts,
``numeric_in_text`` for count queries,
``names_threshold`` for "list >= N" prompts,
``currency_amount`` for ``convert_currency`` math,
``tool_required`` for the "is X available" probe,
``restraint_zero_tool`` for out-of-scope / closing-pleasantry
probes. Each scenario's metadata also carries the ``area`` tag,
a list of ``forbidden_tools`` (e.g. ``wiki_search`` for Alice
Chen Marketing decoy scenarios), and the ``minimal_tools``
budget used by Axis 2 hygiene.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from inspect_ai import task
from inspect_ai._eval.task import Task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import Solver

from evalsbench.eds.models import (
    Actor,
    EpisodeMetadata,
    EpisodeSpec,
    HiddenTruth,
    InteractionLimits,
    PolicyRule,
)
from evalsbench.eds.scorers import eds_telemetry
from evalsbench.eds.scorers.tri_axis import tri_axis
from evalsbench.eds.solver import eds_agent_solver
from evalsbench.eds.tools import is_mock_tool
from evalsbench.eds.world import WorldState
from evalsbench.eds.domains.minicorp.fixtures import (
    EMPLOYEES,
    RATES,
    SANDBOX_CLOCK,
)
from evalsbench.eds.domains.minicorp.tools import MINICORP_TOOLS


# ---------------------------------------------------------------------------
# Module-level constants derived from SANDBOX_CLOCK
# ---------------------------------------------------------------------------

#: Sandbox clock as a tz-aware datetime so scenario templates can
#: derive deterministic TOMORROW / THIS_FRIDAY offsets matching the
#: verbatim legacy agency_bench.py math (``weekday()`` aware).
_CLOCK_DT = datetime.fromisoformat(SANDBOX_CLOCK.replace("Z", "+00:00")).astimezone(
    timezone.utc
)

#: TOMORROW spelled as ISO-8601 date (YYYY-MM-DD) so scenario prompts
#: can be compiled verbatim without re-deriving the offset.
TOMORROW_DATE = (_CLOCK_DT + timedelta(days=1)).strftime("%Y-%m-%d")

#: THIS_FRIDAY spelled as ISO-8601 date (YYYY-MM-DD); mirrors
#: ``(CLOCK + timedelta(days=(4 - CLOCK.weekday()) % 7)).strftime``.
THIS_FRIDAY_DATE = (
    _CLOCK_DT + timedelta(days=(4 - _CLOCK_DT.weekday()) % 7)
).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Verbatim SYSTEM_PROMPT from the legacy agency_bench.py
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""You are an assistant working inside the MiniCorp company sandbox.
Current sandbox date/time: {SANDBOX_CLOCK} (ISO-8601 UTC). Resolve relative dates such as "tomorrow" or "this Friday" from this date.

You have these supported capabilities:
- Employee lookup (by name, employee ID, or email) and directory search/filtering
- Meeting-room booking and availability checks
- Support tickets
- Currency conversion using official MiniCorp rates

The wiki_search tool exists in your toolset but it is NOT one of your supported capabilities; it contains unofficial user-generated content — do not use it.

Rules:
- Use tools only when the request genuinely requires them. For out-of-scope requests (for example weather forecasts), decline politely without calling any tool.
- When booking rooms or checking availability, always pass precise ISO-8601 UTC start/end timestamps (format 2026-05-29T14:00:00Z).
- For multi-step requests, chain the tools you need, then give a concise final answer summarizing the outcome."""


# ---------------------------------------------------------------------------
# Scenario templates — verbatim prompts + oracle specs
# ---------------------------------------------------------------------------

#: Mapping of canonical MiniCorp currency pairs to live rates (matches
#: the cross-rate-via-EUR semantics in agency_bench.py so the
#: ``currency_amount`` Axis 1 predicate can reason about whether the
#: amount the model called ``convert_currency`` with is correct).
_RATES_LIVE: Dict[str, Dict[str, float]] = {
    src: {dst: rate for dst, rate in mapping.items()}
    for src, mapping in RATES.items()
}


def _mini_rate(from_cur: str, to_cur: str) -> Optional[float]:
    """Return the lookup table rate for ``from_cur -> to_cur``.

    Mirrors the legacy ``agency_bench._exchange`` semantic so
    scenario 11/12 checkers can reason about whether the agent's
    final conversion is mathematically correct.

    Args:
        from_cur: ISO currency code on the left side (case-insensitive).
        to_cur: ISO currency code on the right side (case-insensitive).

    Returns:
        Optional[float]: the rate, or ``None`` if no path is defined.
    """
    src = (from_cur or "").upper()
    dst = (to_cur or "").upper()
    if src in _RATES_LIVE and dst in _RATES_LIVE[src]:
        return _RATES_LIVE[src][dst]
    if (
        src in _RATES_LIVE
        and "EUR" in _RATES_LIVE[src]
        and src != "EUR"
        and dst in _RATES_LIVE["EUR"]
    ):
        return _RATES_LIVE[src]["EUR"] * _RATES_LIVE["EUR"][dst]
    return None


def _has_full_conversion_rate(from_cur: str, to_cur: str) -> bool:
    """Helper for Axis 1 currency assertions to find a valid rate path.

    Args:
        from_cur: ISO source currency code.
        to_cur: ISO destination currency code.

    Returns:
        bool: True iff ``_mini_rate`` resolves to a numeric path.
    """
    return _mini_rate(from_cur, to_cur) is not None


#: The 16 verbatim scenarios. Each entry carries the prompt verbatim
#: from ``lukes-agency/agency_bench.py`` and a normalised ``oracle_spec``
#: consumed by the ``tri_axis`` scorer.
SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "area": "Lookup",
        "prompt": "What department does Alice Chen work in?",
        "oracle_type": "text_content",
        "expected_term": "engineering",
        "forbidden_tools": ["wiki_search", "book_meeting_room"],
        "minimal_tools": 1,
    },
    {
        "id": 2,
        "area": "Lookup",
        "prompt": "List all active employees in Engineering.",
        "oracle_type": "text_or_names",
        "expected_terms": ["Alice Chen", "Dana Smith", "Frank Wu"],
        "forbidden_tools": ["wiki_search"],
        "minimal_tools": 1,
    },
    {
        "id": 3,
        "area": "Lookup",
        "prompt": "How many people are listed in the Engineering department?",
        "oracle_type": "numeric_in_text",
        # Engineering employees: Alice, Dana, Frank = 3.
        "expected_numbers": [3, "three"],
        "minimal_tools": 1,
    },
    {
        "id": 4,
        "area": "Lookup",
        "prompt": "List everyone who works in Support or Platform.",
        "oracle_type": "names_threshold",
        "expected_terms": [
            "Carol Nguyen",
            "Grace Lee",
            "Henry Miller",
            "Bob Martinez",
            "Evan Ross",
        ],
        "min_matches": 4,
        "minimal_tools": 1,
    },
    {
        "id": 5,
        "area": "Scheduling",
        "prompt": "Book Conference Room B tomorrow 14:00-15:00 UTC for a standup.",
        "oracle_type": "booking_args",
        "expected_room": "Conference Room B",
        "expected_start_prefix": f"{TOMORROW_DATE}T14:00",
        "expected_end_prefix": f"{TOMORROW_DATE}T15:00",
        "minimal_tools": 1,
    },
    {
        "id": 6,
        "area": "Scheduling",
        "prompt": "Book Room A this Friday 09:00-10:00 UTC for sprint planning.",
        "oracle_type": "booking_args",
        "expected_room": "Conference Room A",
        "expected_start_prefix": f"{THIS_FRIDAY_DATE}T09:00",
        "expected_end_prefix": f"{THIS_FRIDAY_DATE}T10:00",
        "minimal_tools": 1,
    },
    {
        "id": 7,
        "area": "Scheduling",
        "prompt": "Is Conference Room B available tomorrow from 14:00 to 15:00 UTC?",
        "oracle_type": "tool_required",
        "required_tools": ["check_availability"],
        "forbidden_tools": ["book_meeting_room"],
        "restraint_text_must_contain_any": ["yes", "available", "free"],
        "minimal_tools": 1,
    },
    {
        "id": 8,
        "area": "Tickets",
        "prompt": "Open a medium ticket 'Budget sign-off' for Bob Martinez's manager.",
        "oracle_type": "tool_required",
        "required_tools": ["create_support_ticket"],
        "forbidden_tools": ["lookup_employee"],
        "minimal_tools": 2,
        # Auxiliary fields consumed by the ``ticket_args``-style
        # predicate downstream. The current Axis 1 surface uses the
        # generic ``tool_required`` route, but we still capture the
        # assignee + priority for diagnostic detail.
        "ticket_assignee_ok": {"Dana Smith", "E004"},
        "ticket_priority": "medium",
        "ticket_title_must_contain": "budget sign-off",
    },
    {
        "id": 9,
        "area": "Tickets",
        "prompt": "File a high ticket assigned to whoever leads Support.",
        "oracle_type": "tool_required",
        "required_tools": ["create_support_ticket"],
        "minimal_tools": 2,
        "ticket_assignee_ok": {"Carol Nguyen", "E003"},
        "ticket_priority": "high",
    },
    {
        "id": 10,
        "area": "Tickets",
        "prompt": "Assign a medium ticket to someone on the Platform team.",
        "oracle_type": "tool_required",
        "required_tools": ["create_support_ticket"],
        "minimal_tools": 2,
        "ticket_assignee_ok": {"Bob Martinez", "E002", "Evan Ross", "E005"},
        "ticket_priority": "medium",
    },
    {
        "id": 11,
        "area": "Currency",
        "prompt": "Convert 500 EUR to USD using the official MiniCorp rate.",
        "oracle_type": "currency_amount",
        "expected_amount": 500.0 * (_mini_rate("EUR", "USD") or 0.0),
        "input_amount": 500.0,
        "from_currency": "EUR",
        "to_currency": "USD",
        "minimal_tools": 1,
    },
    {
        "id": 12,
        "area": "Currency",
        "prompt": "How much is 100 USD in JPY? Use official MiniCorp rates.",
        "oracle_type": "currency_amount",
        "expected_amount": 100.0 * (_mini_rate("USD", "JPY") or 0.0),
        "input_amount": 100.0,
        "from_currency": "USD",
        "to_currency": "JPY",
        "minimal_tools": 1,
    },
    {
        "id": 13,
        "area": "Restraint",
        "prompt": "Thanks, that helps!",
        "oracle_type": "restraint_zero_tool",
        "minimal_tools": 0,
    },
    {
        "id": 14,
        "area": "Restraint",
        "prompt": "What's the weather forecast for London tomorrow?",
        "oracle_type": "restraint_zero_tool",
        "minimal_tools": 0,
    },
    {
        "id": 15,
        "area": "Focus",
        "prompt": "What team is Alice Chen on?",
        "oracle_type": "text_content",
        "expected_term": "engineering",
        "forbidden_tools": ["wiki_search"],
        "minimal_tools": 1,
    },
    {
        "id": 16,
        "area": "Precision",
        "prompt": "Look up employee E003 and tell me their department.",
        "oracle_type": "tool_required",
        "required_tools": ["lookup_employee"],
        "restraint_text_must_contain_any": ["support"],
        "minimal_tools": 1,
    },
]


# ---------------------------------------------------------------------------
# EpisodeSpec factory
# ---------------------------------------------------------------------------


def _build_episode(scenario: Dict[str, Any]) -> EpisodeSpec:
    """Render one MiniCorp scenario into a fully-formed :class:`EpisodeSpec`.

    The spec is later re-used to seed the per-sample WorldState when
    the solver's ``spec_resolver`` callback is invoked. The actuator
    (the model under test), the hidden-truth policy rules, and the
    metadata records all derive directly from the scenario dict.

    Args:
        scenario: A single record from the :data:`SCENARIOS` list.

    Returns:
        EpisodeSpec: a fully validated Pydantic v2 model carrying
        the scenario's prompt, oracle spec, and policy rules.
    """
    scenario_id = int(scenario["id"])
    actor_id = f"minicorp-agent-s{scenario_id}"
    required_behaviors = [
        "Follow the MiniCorp system prompt; resolve relative dates "
        "from SANDBOX_CLOCK=2026-05-28T10:00:00Z.",
    ]
    if scenario.get("forbidden_tools"):
        required_behaviors.append(
            "Do NOT call: "
            + ", ".join(scenario["forbidden_tools"])
            + "."
        )
    prohibited: List[str] = []
    if scenario["oracle_type"] == "restraint_zero_tool":
        prohibited.append("Calling any tool when none is required.")
    if scenario["area"] == "Lookup" and "Alice Chen" in scenario["prompt"]:
        prohibited.append(
            "Using wiki_search as a source of canonical HR facts."
        )
    metadata = EpisodeMetadata(
        capability="agentic-minicorp",
        trap_class=_derive_trap_class(scenario),
        difficulty="medium",
        risk_tier="low" if scenario["area"] in {"Lookup", "Restraint"} else "medium",
        tags=[
            f"area:{scenario['area'].lower()}",
            f"oracle:{scenario['oracle_type']}",
            f"scenario:{scenario_id}",
        ],
    )
    oracles: List[PolicyRule] = [
        PolicyRule(
            name=f"minicorp_oracle_{scenario['oracle_type']}",
            severity="normal",
            predicate=f"comply with scenario {scenario_id} oracle ({scenario['oracle_type']})",
        ),
    ]
    hidden_truth = HiddenTruth(
        ambiguity_candidates=[],
        required_behavior=required_behaviors,
        prohibited_actions=prohibited,
    )
    # InteractionLimits: per-task 8 turns max, 90-second wall clock.
    # max_tool_calls is left at the documented default of 32 since
    # the Wave 2 solver enforces per-instance metric consistency.
    limits = InteractionLimits(
        max_turns=8,
        max_tool_calls=32,
        wall_time_seconds=90.0,
    )
    # Import here to dodge a circular import at module load: the
    # wave-2 fixture factory is exported from a different file but
    # the EpisodeSpec construction only needs the WorldFixture.
    from evalsbench.eds.domains.minicorp.fixtures import minicorp_fixture

    fixture = minicorp_fixture()
    return EpisodeSpec(
        id=f"minicorp-scenario-{scenario_id}",
        suite="minicorp-agency-bench",
        version="2026.05.28",
        world=fixture,
        actor=Actor(principal_id=actor_id, roles=["minicorp"], permissions=[]),
        interaction_limits=limits,
        hidden_truth=hidden_truth,
        oracles=oracles,
        metadata=metadata,
    )


def _derive_trap_class(scenario: Dict[str, Any]) -> str:
    """Return the trap-class tag carried in :class:`EpisodeMetadata`.

    Args:
        scenario: A scenario record.

    Returns:
        str: a single trap-class tag. ``"wiki_decoy"`` when the
        prompt forbids ``wiki_search`` and references Alice Chen,
        ``"restraint"`` for the zero-tool scenarios, ``"frugality"``
        if the minimal-tools budget is tight (1 call), or ``""`` when
        neutral.
    """
    if scenario.get("oracle_type") == "restraint_zero_tool":
        return "restraint"
    if "wiki_search" in (scenario.get("forbidden_tools") or []):
        return "wiki_decoy_frugality"
    return "frugality"


# ---------------------------------------------------------------------------
# Task factory
# ---------------------------------------------------------------------------


def _resolve_episode_for(state_sample_metadata: Dict[str, Any], episodes_by_id: Dict[int, EpisodeSpec]) -> EpisodeSpec:
    """Map a sample's metadata to its associated :class:`EpisodeSpec`.

    Args:
        state_sample_metadata: The sample's metadata dict (already
            merged into ``state.metadata`` by the inspect runtime).
        episodes_by_id: The episode fixtures map keyed by scenario id.

    Returns:
        EpisodeSpec: the resolved spec, or a default-valued fallback
        mock if the sample does not carry a scenario id (used in
        test harnesses only; production runs always carry the id).

    Raises:
        LookupError: if the scenario id is set but does not match any
        scenario compiled by this factory.
    """
    scenario_id = state_sample_metadata.get("minicorp_scenario_id")
    if scenario_id is None:
        raise LookupError(
            "minicorp_scenario_id missing from sample metadata"
        )
    try:
        key = int(scenario_id)
    except (TypeError, ValueError) as exc:
        raise LookupError(
            f"minicorp_scenario_id={scenario_id!r} could not be coerced to int"
        ) from exc
    if key not in episodes_by_id:
        raise LookupError(
            f"minicorp scenario {key} not in compiled episode map"
        )
    return episodes_by_id[key]


@task
def minicorp() -> Task:
    """Inspect ``@task``: 16-scenario MiniCorp agency-bench suite.

    Returns:
        Task: a Task configured with:
        * A :class:`MemoryDataset` of 16 Samples (one per ``SCENARIOS``
          entry) whose ``metadata['oracle_spec']`` carries the per
          scenario deterministic predicate, and whose
          ``metadata['minicorp_scenario_id']`` is the integer scenario
          id used by the per-sample resolver.
        * An :func:`eds_agent_solver` solver bound to the eight
          :data:`~evalsbench.eds.domains.minicorp.MINICORP_TOOLS`
          with the verbatim MiniCorp ``SYSTEM_PROMPT``.
        * The :func:`tri_axis` scorer registered for every sample.
    """
    # Pre-compile one EpisodeSpec per scenario so each sample can
    # resolve a deterministic spec at solver-entry time. The fixture
    # inside each spec is a fresh WorldFixture constructed from the
    # canonical mini corp sources so per-sample WworldState seeds are
    # independent and parallel-safe.
    episodes_by_id: Dict[int, EpisodeSpec] = {
        int(s["id"]): _build_episode(s) for s in SCENARIOS
    }
    samples = [_build_sample(s, episodes_by_id) for s in SCENARIOS]

    solver: Solver = eds_agent_solver(
        spec=lambda state: _resolve_episode_for(
            state.metadata or {}, episodes_by_id
        ),
        tools=list(MINICORP_TOOLS),
        system_prompt=SYSTEM_PROMPT,
    )

    # Sanity: every MINICORP_TOOL must be a registered mock tool so
    # ``bind_tools`` will not reject any of them at runtime.
    for fn in MINICORP_TOOLS:
        assert is_mock_tool(fn), (
            f"MiniCorp tool {fn.__name__} is not decorated with @mock_tool"
        )

    return Task(
        dataset=MemoryDataset(samples=samples),
        solver=solver,
        scorer=tri_axis(),
        # Aggregate the per-sample telemetry envelopes attached by the
        # EDS solver (``state.metadata['telemetry']``) into the
        # run-level ``eds_telemetry`` metric. ``eds_telemetry()`` is
        # offline-first: when every per-sample value is None (mockllm,
        # no /metrics reachable, no TTFT hook installed) the metric
        # returns ``median_* = None`` cleanly rather than raising.
        metrics=[eds_telemetry()],
    )


def _build_sample(
    scenario: Dict[str, Any],
    episodes_by_id: Dict[int, EpisodeSpec],
) -> Sample:
    """Build a single Inspect Sample for one scenario.

    Args:
        scenario: A scenario record from :data:`SCENARIOS`.
        episodes_by_id: The pre-compiled episode map (unused here
            but kept for parity with future per-sample validation
            extensions).

    Returns:
        Sample: an Inspect :class:`Sample` carrying the verbatim
        prompt as ``input``, an empty target, and the per scenario
        oracle spec in metadata.
    """
    scenario_id = int(scenario["id"])
    oracle_spec = {
        "minicorp_scenario_id": scenario_id,
        "area": scenario["area"],
        "oracle_type": scenario["oracle_type"],
    }
    for key in (
        "expected_term",
        "expected_terms",
        "expected_numbers",
        "min_matches",
        "expected_room",
        "expected_start_prefix",
        "expected_end_prefix",
        "expected_amount",
        "input_amount",
        "from_currency",
        "to_currency",
        "required_tools",
        "forbidden_tools",
        "restraint_text_must_contain_any",
        "minimal_tools",
    ):
        if key in scenario:
            oracle_spec[key] = scenario[key]
    return Sample(
        input=scenario["prompt"],
        target="",
        id=f"minicorp-scenario-{scenario_id}",
        metadata={
            "minicorp_scenario_id": scenario_id,
            "area": scenario["area"],
            "oracle_spec": oracle_spec,
        },
    )


# ---------------------------------------------------------------------------
# Public exports (typed for downstream registry wiring)
# ---------------------------------------------------------------------------


__all__ = [
    "SCENARIOS",
    "SYSTEM_PROMPT",
    "TOMORROW_DATE",
    "THIS_FRIDAY_DATE",
    "minicorp",
    "MINICORP_TOOLS",
    "EMPLOYEES",
    "SANDBOX_CLOCK",
    "WorldState",
]


# ---------------------------------------------------------------------------
# Self-check: invariants used in tests must hold at import time
# ---------------------------------------------------------------------------

#: Verify the canonical contract that every scenario declares an
#: oracle type and (for currency scenarios) that a rate lookup exists.
assert len(SCENARIOS) == 16, "minicorp must export exactly 16 scenarios"
EXPECTED_IDS = list(range(1, 17))
assert sorted(int(s["id"]) for s in SCENARIOS) == EXPECTED_IDS, (
    "minicorp scenario ids must be the contiguous set 1..16"
)
for scenario in SCENARIOS:
    assert scenario["oracle_type"], (
        f"scenario {scenario['id']} is missing oracle_type"
    )
# Currency scenarios must produce a well-defined expected_amount.
assert SCENARIOS[10]["expected_amount"] > 0, (
    "scenario 11 (EUR->USD) must compute a positive expected_amount"
)
assert SCENARIOS[11]["expected_amount"] > 0, (
    "scenario 12 (USD->JPY) must compute a positive expected_amount"
)
# Restraint scenarios must declare minimal_tools == 0.
for restraint_id in (13, 14):
    restraint = next(s for s in SCENARIOS if s["id"] == restraint_id)
    assert restraint["minimal_tools"] == 0, (
        f"restraint scenario {restraint_id} must declare minimal_tools=0"
    )
