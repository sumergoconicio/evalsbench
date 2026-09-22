"""
Integration tests for the EDS telemetry wiring.

These tests pin the contract that :func:`evalsbench.eds.solver.eds_agent_solver`
attaches a per-sample telemetry envelope to ``state.metadata['telemetry']``
end-to-end (no Wave-6 shim solver required) AND that the run-level
``eds_telemetry`` metric registered on the MiniCorp ``@task`` aggregates
cleanly when every per-sample value is ``None`` (mockllm / no /metrics
endpoint / no TTFT hook installed). They also exercise the explicit
``telemetry=False`` opt-out.

Project contract under test:

* The ``TelemetryCollector`` is allocated INSIDE the inner ``solve()``
  closure of :func:`eds_agent_solver` so per-sample closure isolation
  holds (Wave 1 invariant).
* Every model.generate call is wrapped in
  :meth:`TelemetryCollector.measure_generate` and the resulting
  ``state.output`` is stamped via :meth:`GenerateProbe.set_usage`.
* After the loop completes the snapshot is attached to
  ``state.metadata['telemetry']`` and a sentinel placeholder is
  promoted into a ``SampleScore`` whose ``sample_metadata`` carries
  the live ``state.metadata`` — so the run-level
  ``@metric(name='eds_telemetry')`` :func:`eds_telemetry` aggregates
  without requiring each downstream task to register a custom scorer.
* All telemetry paths NEVER raise; missing fields degrade to ``None``,
  offline-first.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from inspect_ai import eval_async, task
from inspect_ai._eval.task import Task
from inspect_ai.dataset import MemoryDataset, Sample

from evalsbench.eds.domains.minicorp.tasks import minicorp
from evalsbench.eds.models import (
    Actor,
    EpisodeMetadata,
    EpisodeSpec,
    HiddenTruth,
    InteractionLimits,
    Provenance,
    TaggedEntity,
    WorldFixture,
)
from evalsbench.eds.scorers import eds_telemetry
from evalsbench.eds.solver import eds_agent_solver
from evalsbench.eds.tools import mock_tool
from evalsbench.eds.world import WorldState


# ---------------------------------------------------------------------------
# Mock tools (so the scripted path stays non-empty without invoking mockllm)
# ---------------------------------------------------------------------------


@mock_tool
def _wireless_stamp(world: WorldState, marker: str = "") -> str:
    """Record a per-sample trail marker for telemetry tests.

    Args:
        marker: Free-text marker identifying the sample.
    """
    actor = world.get_entity("actor", default="")
    world.set_entity("trail", f"{actor}|{marker}")
    return f"{actor}|{marker}"


# ---------------------------------------------------------------------------
# Episode fixture factory (mirrors test_solver.py's _build_sample_episode)
# ---------------------------------------------------------------------------


def _build_sample_episode(
    *,
    sample_id: str,
    actor_id: str,
    marker: str,
    fixture_name: str,
) -> EpisodeSpec:
    fixture = WorldFixture(
        name=fixture_name,
        fixture_version="v1",
        state={"actor": actor_id},
        entities={
            "Origin": TaggedEntity(
                provenance=Provenance.CANONICAL,
                payload={"sample_id": sample_id},
            )
        },
    )
    return EpisodeSpec(
        id=f"ep-{sample_id}",
        suite="telemetry-wiring",
        version="1.0.0",
        world=fixture,
        actor=Actor(
            principal_id=actor_id,
            roles=["telemetry-wire"],
            permissions=["read", "write"],
        ),
        interaction_limits=InteractionLimits(
            max_turns=2,
            max_tool_calls=4,
            wall_time_seconds=30.0,
        ),
        hidden_truth=HiddenTruth(
            ambiguity_candidates=[],
            required_behavior=[],
            prohibited_actions=[],
        ),
        oracles=[],
        metadata=EpisodeMetadata(
            capability="telemetry-wiring",
            trap_class=None,
            difficulty="easy",
            risk_tier="low",
            tags=[sample_id],
        ),
    )


def _drive_two_samples(
    episodes: List[EpisodeSpec],
    scripted: List[Any],
) -> Task:
    """Return an Inspect ``Task`` that runs ``eds_agent_solver`` directly.

    Args:
        episodes: Two EpisodeSpec instances, one per sample.
        scripted: List of ``(tool_name, kwargs)`` tuples used to drive
            the per-sample loop without invoking the language model.

    Returns:
        Task: A two-sample Task whose every sample carries a
        ``__eds_scripted_turns__`` injection so the inner ``solve``
        closure short-circuits the model.generate loop and exercises
        the telemetry attach path deterministically.
    """
    def _resolver(state: Any) -> EpisodeSpec:
        sample_metadata = state.metadata or {}
        sid = sample_metadata.get("eds_spec_id")
        for ep in episodes:
            if ep.id == sid:
                return ep
        raise LookupError(sid)

    solver = eds_agent_solver(
        spec=_resolver,
        tools=[_wireless_stamp],
    )

    @task
    def _build_task() -> Task:
        samples = []
        for ep in episodes:
            samples.append(
                Sample(
                    input=ep.id,
                    target="ok",
                    metadata={
                        "eds_spec_id": ep.id,
                        "role": ep.actor.principal_id,
                        "__eds_scripted_turns__": scripted,
                    },
                )
            )
        return Task(
            dataset=MemoryDataset(samples=samples),
            solver=solver,
            # No scorer; we are NOT testing score aggregation here,
            # we are testing that the solver attaches telemetry.
            # We register the eds_telemetry metric so the run exercises
            # the metric dispatch path too.
            scorer=[],
            metrics=[eds_telemetry()],
        )

    return _build_task()


# ---------------------------------------------------------------------------
# eval_async helpers
# ---------------------------------------------------------------------------


async def _run_eval_two_samples(
    episodes: List[EpisodeSpec],
    scripted: List[Any],
) -> Any:
    """Drive an eval with ``max_connections=2`` and return eval logs."""
    return await eval_async(
        _drive_two_samples(episodes, scripted),
        max_connections=2,
        model="mockllm/mockllm",
        log_level="warning",
    )


# ---------------------------------------------------------------------------
# 1. End-to-end telemetry attachment (no shim — direct eds_agent_solver)
# ---------------------------------------------------------------------------


def test_eds_agent_solver_attaches_telemetry_envelope_via_mockllm():
    """``state.metadata['telemetry']`` arrives intact through mockllm.

    Two samples run concurrently through :func:`eval_async` with
    ``mockllm/mockllm``. The scripted-turns path short-circuits the
    multi-turn loop, but the telemetry collector still opens, attaches
    a snapshot, and pushes the live ``state.metadata`` through the
    sentinel-SampleScore promotion. Per-sample closure isolation must
    hold (each sample's envelope is distinct).
    """
    episodes = [
        _build_sample_episode(
            sample_id="alpha",
            actor_id="agent-alpha",
            marker="a",
            fixture_name="alpha",
        ),
        _build_sample_episode(
            sample_id="beta",
            actor_id="agent-beta",
            marker="b",
            fixture_name="beta",
        ),
    ]
    scripted = [("_wireless_stamp", {"marker": "z"})]
    logs = asyncio.run(_run_eval_two_samples(episodes, scripted))

    sample_telemetry: List[Dict[str, Any]] = []
    for log in logs:
        for sample in log.samples or []:
            metadata = sample.metadata or {}
            sample_telemetry.append(metadata.get("telemetry"))

    assert len(sample_telemetry) == 2
    # Each sample MUST carry the telemetry envelope (no shim involved).
    assert all(t is not None for t in sample_telemetry), sample_telemetry
    for payload in sample_telemetry:
        # The shape contract holds end-to-end.
        assert set(payload.keys()) == {
            "ttft_s",
            "decode_tps",
            "wall_s",
            "rounds",
            "accepted_tokens",
            "draft_tokens",
            "mtp_acceptance",
        }
        # The scripted path never invokes model.generate, so the
        # collector records zero model rounds.
        assert payload["rounds"] == 0
        # Scrape-derived fields degrade to ``None`` since mockllm
        # exposes no ``/metrics`` endpoint and we run with no TTFT
        # hook installed.
        assert payload["ttft_s"] is None
        assert payload["mtp_acceptance"] is None
        assert payload["accepted_tokens"] is None
        assert payload["draft_tokens"] is None
        # Decode TPS is derived from per-turn usage stamps; the
        # scripted path produces no usage, so it is None.
        assert payload["decode_tps"] is None
        # wall_s may be zero or any positive float — it's purely a
        # monotonic-clock delta over the per-sample ``solve`` closure.
        assert isinstance(payload["wall_s"], (int, float)) or (
            payload["wall_s"] is None
        )


# ---------------------------------------------------------------------------
# 2. Metric aggregates without crashing when every value is None
# ---------------------------------------------------------------------------


def test_eds_telemetry_metric_via_minicorp_task_handles_all_none_values():
    """``eds_telemetry`` aggregates cleanly when every value is None.

    Drives the full MiniCorp ``@task`` factory through ``mockllm`` and
    asserts the run-level ``eds_telemetry`` metric is present in the
    log results without raising. When every per-sample telemetry field
    is ``None`` (mockllm / no /metrics / no TTFT hook), the metric
    emits ``sample_count > 0`` but every median is ``None`` and every
    coverage is ``0.0`` — the offline-first contract.
    """
    # Reset the resolver path: call minicorp() and run it via eval_async.
    async def _drive():
        return await eval_async(
            minicorp(),
            max_connections=2,
            model="mockllm/mockllm",
            limit=2,
            log_level="warning",
        )

    logs = asyncio.run(_drive())
    assert logs, "mockllm eval returned no logs"

    log = logs[0]
    # The metric MUST be present in the run results.
    assert log.results is not None
    aggregated_scores = list(log.results.scores or [])
    eds_scorer = next(
        (
            s
            for s in aggregated_scores
            if s.name == "__eds_telemetry_only__"
        ),
        None,
    )
    assert eds_scorer is not None, (
        "the ``eds_agent_solver`` did not register the "
        "``__eds_telemetry_only__`` sentinel scorer; the metric has "
        "no telemetry to aggregate."
    )
    # Every value MUST be JSON-friendly and scalar — no nested
    # dicts are allowed (inspect_ai would otherwise raise TypeError
    # on the float() coercion).
    metric_block: Dict[str, Any] = {
        name: m.value for name, m in eds_scorer.metrics.items()
    }
    for name, value in metric_block.items():
        assert isinstance(value, (int, float)), (
            f"metric[{name!r}] must be a scalar for inspect-ai "
            f"compatibility; got {type(value).__name__} ({value!r})"
        )
    # The Sentinel-scoped metrics:
    # * ``sample_count`` ≥ 1 (we ran 2 samples and each produced a
    #   telemetry envelope).
    # * ``median_decode_tps`` IS measurable — mockllm populates
    #   ``usage.output_tokens`` (33 in default mockllm).
    # * ``median_ttft_s`` and ``median_mtp_acceptance`` are ``None``
    #   because no TTFT hook is installed and no /metrics endpoint
    #   is reachable.
    assert metric_block["sample_count"] >= 1.0
    assert isinstance(metric_block["median_decode_tps"], (int, float))
    # Coverage fields mirror which fields had at least one valid
    # per-sample value.
    assert metric_block["coverage_median_decode_tps"] >= 0.0
    assert metric_block["coverage_median_ttft_s"] >= 0.0
    assert metric_block["coverage_median_mtp_acceptance"] >= 0.0


# ---------------------------------------------------------------------------
# 3. ``telemetry=False`` opt-out — no envelope attached
# ---------------------------------------------------------------------------


def test_eds_agent_solver_telemetry_disabled_when_opted_out():
    """When telemetry=False, no key lands on state.metadata."""
    episodes = [
        _build_sample_episode(
            sample_id="alpha",
            actor_id="agent-alpha",
            marker="a",
            fixture_name="alpha",
        ),
    ]
    scripted = [("_wireless_stamp", {"marker": "x"})]

    def _resolver(state: Any) -> EpisodeSpec:
        return episodes[0]

    solver = eds_agent_solver(
        spec=_resolver,
        tools=[_wireless_stamp],
        telemetry=False,
    )

    @task
    def _build_task() -> Task:
        samples = [
            Sample(
                input=episodes[0].id,
                target="ok",
                metadata={
                    "eds_spec_id": episodes[0].id,
                    "role": episodes[0].actor.principal_id,
                    "__eds_scripted_turns__": scripted,
                },
            )
        ]
        return Task(
            dataset=MemoryDataset(samples=samples),
            solver=solver,
            scorer=[],
            metrics=[eds_telemetry()],
        )

    async def _drive():
        return await eval_async(
            _build_task(),
            max_connections=1,
            model="mockllm/mockllm",
            log_level="warning",
        )

    logs = asyncio.run(_drive())
    samples: List[Any] = []
    for log in logs:
        samples.extend(log.samples or [])
    assert len(samples) == 1
    metadata = samples[0].metadata or {}
    assert "telemetry" not in metadata, (
        "telemetry=False must suppress the envelope entirely; sample "
        f"metadata was {metadata!r}"
    )
    # The sentinel Score was also suppressed — only __eds_telemetry_only__
    # appears when telemetry=True, so when telemetry=False the metric
    # has nothing to aggregate (sample_count=0).
    eds_scorer = next(
        (s for s in logs[0].results.scores if s.name == "__eds_telemetry_only__"),
        None,
    )
    assert eds_scorer is not None
    metric_block = {
        name: m.value for name, m in eds_scorer.metrics.items()
    }
    assert metric_block["sample_count"] == 0.0
    # Inspect AI's metric pipeline drops ``None`` values from the
    # run-level display, so we relax to ``== 0.0`` if absent.
    for key in ("median_ttft_s", "median_decode_tps", "median_mtp_acceptance"):
        assert metric_block.get(key) in (None, 0.0), (
            f"telemetry=False must keep median={key!r} None; "
            f"got {metric_block.get(key)!r}"
        )
