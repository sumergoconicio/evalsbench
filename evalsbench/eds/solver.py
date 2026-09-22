"""
EDS agent solver for the EvalsBench EDS subpackage.

File:    evalsbench/eds/solver.py
Module:  evalsbench.eds
Purpose: Build an Inspect AI ``Solver`` that drives a single EDS episode
         per :class:`inspect_ai.dataset.Sample` while honouring the
         per-sample isolation contract verified by
         ``scratch/probe_inspect_closures.py``.

The factory returned by :func:`eds_agent_solver` exposes an inner
``async def solve(state, generate)`` closure. In the closure (per
sample) we:

1. Resolve the per-sample :class:`EpisodeSpec` — from the explicit
   argument, from the sample's metadata (``state.sample.metadata``),
   or from a caller-supplied callable.
2. Build a fresh :class:`WorldState` from the spec's
   :class:`WorldFixture`. The newly constructed object is the
   authoritative per-sample world: every tool dispatch closes over
   this specific instance and no other sample's tools can reach it.
3. Bind the supplied :func:`@mock_tool <mock_tool>` functions through
   :func:`~evalsbench.eds.tools.bind_tools`, attaching the per-sample
   world and actor to each tool's closure. The bound tools replace
   ``state.tools`` so all subsequent ``generate()`` calls see only
   this sample's tool surface.
4. Push the episode's system prompt as the first message.
5. Drive the multi-turn look-bounded loop until the model stops
   issuing tool calls or the per-episode
   :class:`~evalsbench.eds.models.InteractionLimits` thresholds fire.

This mirrors the closure isolation mechanism validated in
``scratch/probe_inspect_closures.py``: the per-sample world is built
*inside* the inner ``solve`` closure so it cannot be shared across
siblings even when ``max_connections > 1``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, List, Optional, Union

from inspect_ai.model import ChatMessageSystem, get_model
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.solver import Generate, Solver, TaskState, solver

from .models import EpisodeSpec
from .telemetry import TelemetryCollector, derive_endpoint
from .tools import MockToolSpec, bind_tools, is_mock_tool
from .world import WorldState


# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger("evalsbench.eds.solver")


# ---------------------------------------------------------------------------
# Episode resolution helpers
# ---------------------------------------------------------------------------


# Metadata key the sample-level resolver writes into ``state.metadata``
# when a scripted turning drive has been pre-loaded by a test harness.
_SCRIPTED_TURNS_KEY = "__eds_scripted_turns__"


# Metadata key the resolver sets when it could not locate an
# ``EpisodeSpec`` for the current sample; downstream scorers can use
# this signal to mark the episode unrunnable.
_UNRESOLVED_KEY = "__eds_unresolved__"


def eds_agent_solver(
    spec: Union[EpisodeSpec, Callable[[TaskState], EpisodeSpec], None] = None,
    tools: Optional[List[Callable[..., Any]]] = None,
    *,
    fixture: Any = None,
    actor: Optional[str] = None,
    system_prompt: Optional[str] = None,
    fixture_resolver: Optional[Callable[[TaskState], EpisodeSpec]] = None,
    telemetry: bool = True,
) -> Solver:
    r"""Build the EDS agent solver factory.

    Accepts either a single shared :class:`EpisodeSpec` (applied to every
    sample identically) or a callable that maps a :class:`TaskState`
    to a per-sample spec. Per-sample fixture / tool overrides allow the
    caller to drive diagnostic isolation tests such as
    ``tests/eds/test_solver.py``.

    The inner ``solve(state, generate)`` closure is invoked once per
    sample. World state, tool bindings, and the trace are constructed
    inside this closure so per-sample closure isolation holds under
    concurrent execution — exactly the same invariant as
    ``scratch/probe_inspect_closures.py``.

    Args:
        spec: Either a single :class:`EpisodeSpec` shared across all
            samples, or a callable ``EpisodeSpecResolver`` mapping a
            :class:`TaskState` to a per-sample :class:`EpisodeSpec`.
            When ``None``, the resolver is reconstructed lazily via
            ``state.metadata["eds_spec"]`` or a configured
            ``fixture_resolver``.
        tools: Optional list of :func:`@mock_tool <mock_tool>`-decorated
            functions made available to the model for every sample. The
            list is bound per sample inside the inner ``solve``
            closure so that no per-sample state leaks across siblings.
        fixture: Optional alternative to ``spec``: a bare
            :class:`~evalsbench.eds.models.WorldFixture`. When supplied,
            a degenerate :class:`EpisodeSpec` is constructed on the
            fly (used for legacy fixtures that lack full episode
            metadata).
        actor: Override for the actor id stamped on every recorded
            :class:`~evalsbench.eds.models.ToolEvent`. Defaults to the
            :class:`~evalsbench.eds.models.Actor.principal_id` field
            on the resolved spec, or the literal ``"actor"`` when a
            fixture-only configuration is used.
        system_prompt: Optional override for the per-sample system
            message. When set, this value replaces any
            ``EpisodeSpec.hidden_truth.required_behavior``
            concatenation and is pushed as the first message of the
            sample's conversation.
        fixture_resolver: Optional callable mapping a
            :class:`TaskState` to a fully-formed per-sample
            :class:`EpisodeSpec`. Useful for tests that need
            different fixtures per sample.
        telemetry: When ``True`` (default), wrap each ``model.generate``
            call in a per-sample :class:`~evalsbench.eds.telemetry.TelemetryCollector`
            and attach the resulting envelope to
            ``state.metadata['telemetry']`` after the loop completes.
            The collector is allocated INSIDE this factory's inner
            ``solve`` closure so its state never bleeds across
            siblings (the same per-sample isolation invariant as
            the WorldState). Defaults to ``True`` so downstream
            tasks (notably the MiniCorp ``@task``) automatically
            forward hardware telemetry into the run-level
            ``eds_telemetry`` metric without per-call wiring. Set
            to ``False`` to disable telemetry collection entirely
            (e.g., for tests that exercise the resolver path
            without spawning a real model).

    Returns:
        Solver: an Inspect AI ``Solver`` whose inner ``solve``
        closure may be invoked once per sample.
    """
    if fixture is not None and spec is None:
        if not isinstance(fixture, EpisodeSpec):
            raise TypeError(
                "fixture alternative must be an EpisodeSpec instance; "
                "for a raw WorldFixture, supply it through "
                "spec_resolver or fixture_resolver."
            )
        spec = fixture

    def _resolver(state: TaskState) -> EpisodeSpec:
        sample_metadata = state.metadata or {}
        if callable(spec) and not isinstance(spec, EpisodeSpec):
            resolved = spec(state)
            if not isinstance(resolved, EpisodeSpec):
                raise TypeError(
                    f"Spec resolver returned {type(resolved).__name__}; "
                    "EpisodeSpec required."
                )
            return resolved
        if isinstance(spec, EpisodeSpec):
            return spec
        if fixture_resolver is not None:
            resolved = fixture_resolver(state)
            if not isinstance(resolved, EpisodeSpec):
                raise TypeError(
                    f"fixture_resolver returned {type(resolved).__name__}; "
                    "EpisodeSpec required."
                )
            return resolved
        embedded = sample_metadata.get("eds_spec")
        if isinstance(embedded, EpisodeSpec):
            return embedded
        raise LookupError(
            "eds_agent_solver could not resolve an EpisodeSpec for the "
            "current sample; pass `spec`, a callable spec resolver, "
            "fixture_resolver, or embed `metadata['eds_spec']`."
        )

    @solver
    def _eds_agent_solver() -> Solver:  # type: ignore[no-redef]
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # ----- 1. Resolve per-sample EpisodeSpec -----
            try:
                episode = _resolver(state)
            except LookupError as exc:
                state.metadata[_UNRESOLVED_KEY] = str(exc)
                logger.warning("EDS solver: %s; sample cannot proceed.", exc)
                return state

            # ----- 2. Build per-sample WorldState -----
            # Bound *inside* this closure -> per-sample isolation holds
            # even with max_connections > 1.
            world = WorldState(episode.world)
            # Live in-memory reference for in-eval consumers (scorers,
            # checkpoints) that hold the same TaskState lifetime.
            state.metadata["world"] = world
            # JSON-serializable companion state mirroring the world for
            # post-eval assertions: world_trace_json holds the canonical
            # ToolEvent dump; world_fixture_name preserves the source
            # identity for per-sample sanity checks.
            state.metadata["world_trace_json"] = []
            state.metadata["world_fixture_name"] = episode.world.name
            # ----- 3. Bind tools to this sample's world + actor -----
            episode_actor = episode.actor.principal_id
            sample_actor = actor or episode_actor
            state.metadata["world_actor"] = sample_actor
            state.metadata["episode_spec"] = episode.model_dump(mode="python")

            bound_tools: List[Any] = bind_tools(
                world=world,
                tool_fns=list(tools or []),
                actor=sample_actor,
            )
            state.tools = list(bound_tools)

            # ----- 4. Push system prompt from the episode -----
            system_text = system_prompt or _compose_system_prompt(episode)
            if system_text:
                state.messages.append(
                    ChatMessageSystem(content=system_text)
                )

            # ----- 4.5 Build per-sample TelemetryCollector (opt-in) -----
            # Created INSIDE this per-sample solve() closure so its
            # state never bleeds across siblings under max_connections
            # > 1 (the same invariant as the WorldState allocation
            # above). The collector never raises: a missing endpoint
            # -> None metrics, a degraded /metrics scrape -> None MTP
            # counters, an exception during __aenter__ / __aexit__
            # is swallowed so the offline-first contract holds.
            collector: Optional[TelemetryCollector] = None
            if telemetry:
                try:
                    endpoint = _resolve_telemetry_endpoint()
                    collector = TelemetryCollector(endpoint=endpoint)
                    await collector.__aenter__()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "EDS solver: telemetry collector init failed: %s",
                        exc,
                    )
                    collector = None

            try:
                # ----- 5. Optional scripted-drive test path -----
                scripted = state.metadata.get(_SCRIPTED_TURNS_KEY)
                if scripted:
                    await _run_scripted_turns(state, bound_tools, scripted)
                else:
                    # ----- 6. Multi-turn tool-calling loop with limits -----
                    limits = episode.interaction_limits
                    start = time.monotonic()
                    for turn_index in range(limits.max_turns):
                        if not state.tools:
                            break
                        elapsed = time.monotonic() - start
                        if elapsed > limits.wall_time_seconds:
                            logger.info(
                                "EDS solver: terminating sample after %.2fs "
                                "(wall_time_seconds=%.2f).",
                                elapsed,
                                limits.wall_time_seconds,
                            )
                            break
                        try:
                            if collector is not None:
                                async with collector.measure_generate() as probe:
                                    state.output = await get_model().generate(
                                        input=state.messages,
                                        tools=state.tools,
                                    )
                                    probe.set_usage(state.output)
                            else:
                                state.output = await get_model().generate(
                                    input=state.messages, tools=state.tools
                                )
                        except Exception as exc:  # noqa: BLE001
                            logger.exception(
                                "EDS solver: model.generate failed "
                                "(turn %d): %s",
                                turn_index,
                                exc,
                            )
                            break
                        state.messages.append(state.output.message)
                        tool_calls = state.output.message.tool_calls
                        if not tool_calls:
                            break
                        try:
                            tool_results, _ = await execute_tools(
                                [state.output.message],
                                state.tools,
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.exception(
                                "EDS solver: execute_tools failed "
                                "(turn %d): %s",
                                turn_index,
                                exc,
                            )
                            break
                        state.messages.extend(tool_results)
            finally:
                # ----- 6.5 Close + attach telemetry snapshot (best-effort) -----
                # The detach + attach sequence never raises; we log at
                # DEBUG on failure so a transient telemetry outage
                # cannot fail the run.
                if collector is not None:
                    try:
                        await collector.__aexit__(None, None, None)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "EDS solver: telemetry __aexit__ failed: %s",
                            exc,
                        )
                    try:
                        collector.attach(state.metadata)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "EDS solver: telemetry attach failed: %s",
                            exc,
                        )
            # ----- 6.6 Promote telemetry into SampleScore.sample_metadata -----
            # Inspect AI's run-loop scorer chain (see
            # ``inspect_ai/_eval/task/run.py``: ``for name in
            # solver_score_names: results[name] = SampleScore(...)``)
            # captures ``state.scores`` keys BEFORE the scorer chain runs
            # and emits a :class:`SampleScore` per pre-existing entry whose
            # ``sample_metadata`` is the live ``state.metadata``. We push
            # a sentinel placeholder so the :class:`~evalsbench.eds.telemetry.TelemetryCollector`
            # snapshot we just attached carries through to the run-level
            # ``eds_telemetry`` metric without requiring each downstream
            # task to register a custom scorer.
            try:
                if state.scores is None:
                    state.scores = {}
                from inspect_ai.scorer import Score

                state.scores["__eds_telemetry_only__"] = Score(
                    value=0.0,
                    answer="",
                    explanation=(
                        "eds_telemetry payload carrier; the metric "
                        "consumes ``sample_metadata['telemetry']`` "
                        "rather than ``value``."
                    ),
                    metadata={"_eds_telemetry_only_": True},
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "EDS solver: telemetry payload carrier failed: %s",
                    exc,
                )
            # Snapshot the append-only trace as JSON-serializable data
            # so it survives pydantic round-trip during post-eval
            # assertions; the live world reference above still owns
            # the structured trace for in-eval consumers.
            state.metadata["world_trace_json"] = [
                event.model_dump(mode="json") for event in world.trace
            ]
            state.metadata["world_diff_json"] = world.snapshot_diff()
            return state

        return solve

    return _eds_agent_solver()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_telemetry_endpoint() -> Optional[str]:
    """Best-effort lookup of the OpenAI-compatible endpoint for telemetry.

    Reads the currently registered Inspect AI model and prefers
    ``model.explicit_base_url`` (the URL the caller pinned via
    ``--base-url`` or model args), falling back to the provider's
    resolved ``model.api.base_url``. Returns ``None`` when neither
    is populated (mockllm, defaults) or any exception fires —
    :class:`~evalsbench.eds.telemetry.TelemetryCollector` accepts
    ``None`` and degrades every scrape-derived field to ``None``.

    The helper is invoked INSIDE each per-sample ``solve`` closure
    so any model swap mid-eval is honoured on the next sample.

    Returns:
        Optional[str]: ``/v1``-stripped endpoint URL, or ``None``.
    """
    try:
        model_obj = get_model()
    except Exception as exc:  # noqa: BLE001
        logger.debug("EDS solver: telemetry get_model() failed: %s", exc)
        return None
    explicit = getattr(model_obj, "explicit_base_url", None)
    if isinstance(explicit, str) and explicit:
        return derive_endpoint(explicit)
    api = getattr(model_obj, "api", None)
    base = getattr(api, "base_url", None) if api is not None else None
    if isinstance(base, str) and base:
        return derive_endpoint(base)
    return None


def _compose_system_prompt(episode: EpisodeSpec) -> str:
    """Build a default system prompt from an :class:`EpisodeSpec`.

    The prompt concatenates the episode's hidden required-behavior
    strings and policy rules into a single directive. If both inputs
    are empty the prompt is the literal ``"You are an EDS agent."`` so
    the model always sees at least one system message.

    Args:
        episode: The resolved per-sample episode specification.

    Returns:
        str: a concatenated directive suitable as a system message.
    """
    parts: List[str] = []
    hidden = episode.hidden_truth
    if hidden.required_behavior:
        parts.append(
            "Required behaviors:\n- "
            + "\n- ".join(hidden.required_behavior)
        )
    if hidden.prohibited_actions:
        parts.append(
            "Prohibited actions:\n- "
            + "\n- ".join(hidden.prohibited_actions)
        )
    if episode.oracles:
        parts.append(
            "Policies:\n- "
            + "\n- ".join(
                f"{rule.name} ({rule.severity}): {rule.predicate}"
                for rule in episode.oracles
            )
        )
    parts.append("You are an EDS agent.")
    return "\n\n".join(parts)


async def _run_scripted_turns(
    state: TaskState,
    bound_tools: List[Any],
    scripted: Any,
) -> None:
    """Drive pre-scripted tool turns without invoking the language model.

    Used by tests that exercise the per-sample isolation invariant
    without depending on a live model provider. Each entry in
    ``scripted`` is a tuple ``(tool_name, kwargs)``; the matching
    bound callable is invoked directly and its result is recorded in
    the message list as a ``ChatMessageTool`` mock so subsequent test
    assertions can inspect the trace.

    Args:
        state: The current :class:`TaskState`. Mutated in place to
            carry the scripted tool results.
        bound_tools: The per-sample bound Tools returned from
            :func:`bind_tools`.
        scripted: Iterable of ``(tool_name, kwargs)`` tuples. Any
            iterable (list, tuple, generator) is accepted.

    Returns:
        None. Mutates ``state.messages`` and ``state.metadata`` in place.

    Raises:
        TypeError: if a scripted entry is not a 2-tuple.
        LookupError: if no bound tool matches the specified tool name.
    """
    tool_index = {getattr(callable_obj, "__name__", str(i)): callable_obj
                  for i, callable_obj in enumerate(bound_tools)}
    for entry in scripted:
        if not (
            isinstance(entry, (list, tuple))
            and len(entry) == 2
        ):
            raise TypeError(
                f"Scripted turn entry must be (tool_name, kwargs); "
                f"got {entry!r}"
            )
        tool_name, kwargs = entry
        if tool_name not in tool_index:
            raise LookupError(
                f"No bound tool named {tool_name!r}; available: "
                f"{sorted(tool_index.keys())}"
            )
        result = await tool_index[tool_name](**kwargs)
        state.metadata.setdefault("eds_scripted_results", []).append(
            (tool_name, dict(kwargs), result)
        )
