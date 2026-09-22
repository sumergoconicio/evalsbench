"""
Unit tests for evalsbench.eds.telemetry and evalsbench.eds.scorers.

Covers three layers:

1. **Collector unit tests**: TelemetryCollector construction, async
   lifecycle (start/close), /metrics counter parsing, MTP delta
   math, decode TPS from usage numbers, attach() shape, and
   resilience to unreachable /metrics endpoints and to missing
   ttft hooks.

2. **Metric unit tests**: The ``eds_telemetry`` Inspect ``@metric``
   must aggregate across heterogeneous SampleScore payloads
   (some with telemetry, some without), handle ``None``/non-numeric
   fields gracefully, and emit a stable shape with coverage
   metadata.

3. **Integration-style test**: Drive a tiny Inspect AI eval_async
   run through mockllm, asserting ``state.metadata["telemetry"]``
   is populated by :class:`TelemetryCollector` integration. The
   integration test reaches the real Inspect AI driver so the
   per-sample closure isolation contract from Wave 1 still holds
   end-to-end.
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import Any, Dict, Optional

import pytest

# inspect_ai imports used to drive the integration-style eval.
from inspect_ai import eval_async, task
from inspect_ai.dataset import MemoryDataset, Sample

from evalsbench.eds.telemetry import (
    DEFAULT_METRICS_TIMEOUT_S,
    TelemetryCollector,
    _parse_metrics,
    _strip_v1_suffix,
    derive_endpoint,
)
from evalsbench.eds.scorers import eds_telemetry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Drive an async coroutine from a synchronous pytest case.

    The project does not depend on ``pytest-asyncio``; using
    ``asyncio.run`` keeps every test a vanilla synchronous pytest
    function — consistent with the rest of the EDS suite.

    Args:
        coro: Awaitable coroutine.

    Returns:
        Any: Coroutine return value.
    """
    return asyncio.run(coro)


def _build_metrics_text(spec_decode_payload: str) -> str:
    """Wrap vLLM spec-decode counter lines with surrounding metrics text.

    Args:
        spec_decode_payload: Pre-formatted counter lines (passed
            through verbatim).

    Returns:
        str: Prometheus exposition body suitable for parsing.
    """
    header = (
        "# HELP vllm:spec_decode_num_accepted_tokens_total Spec decode accepted tokens\n"
        "# TYPE vllm:spec_decode_num_accepted_tokens_total counter\n"
    )
    return header + spec_decode_payload.lstrip("\n")


def _counter_line(label: str, value: float) -> str:
    """Render a single vLLM spec-decode counter line."""
    return (
        f'vllm:spec_decode_num_{label}_total{{model="test",instance="0"}} '
        f"{value:.6f}\n"
    )


# ---------------------------------------------------------------------------
# TelemetryCollector unit tests
# ---------------------------------------------------------------------------


def test_strip_v1_suffix_handles_trailing_slash_and_no_suffix():
    assert _strip_v1_suffix("http://localhost:2468/v1") == "http://localhost:2468"
    assert (
        _strip_v1_suffix("http://localhost:2468/v1/")
        == "http://localhost:2468"
    )
    assert _strip_v1_suffix("http://localhost:2468") == "http://localhost:2468"
    assert (
        _strip_v1_suffix("http://localhost:2468/models")
        == "http://localhost:2468/models"
    )


def test_derive_endpoint_returns_none_when_input_is_none():
    assert derive_endpoint(None) is None


def test_derive_endpoint_strips_v1_from_inspect_style_base():
    assert (
        derive_endpoint("http://localhost:2468/v1")
        == "http://localhost:2468"
    )


def test_parse_metrics_aggregates_repeated_counter_labels():
    text = _build_metrics_text(
        _counter_line("accepted_tokens", 1.0)
        + 'vllm:spec_decode_num_accepted_tokens_total{'
        'model="test",instance="1"} 2.0\n'
        + _counter_line("draft_tokens", 4.0)
    )
    snapshot = _parse_metrics(text)
    assert snapshot.accepted_tokens == pytest.approx(3.0)
    assert snapshot.draft_tokens == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Stubs used to fake Inspect AI ModelOutput for type probing.
# ---------------------------------------------------------------------------


class _FakeUsage:
    """Minimal stand-in for ``inspect_ai.model._model_output.ModelUsage``."""

    def __init__(self, output_tokens: int = 0) -> None:
        self.output_tokens = int(output_tokens)


class _FakeOutput:
    """Minimal stand-in for ``inspect_ai.model.ModelOutput``."""

    def __init__(self, output_tokens: int = 0) -> None:
        self.usage = _FakeUsage(output_tokens)


def test_telemetry_collector_resilient_when_endpoint_down():
    """Collector must never raise when /metrics is unreachable."""

    async def _body():
        closed_port = _closed_local_port()
        endpoint = f"http://127.0.0.1:{closed_port}"
        collector = TelemetryCollector(endpoint=endpoint)
        # Enter + close must succeed despite the closed port.
        async with collector:
            await collector._fetch_snapshot()  # internal probe, swallows
        return collector.snapshot()

    payload = _run(_body())
    assert payload["ttft_s"] is None
    assert payload["mtp_acceptance"] is None
    # Decode TPS without recorded usage is None.
    assert payload["decode_tps"] is None
    assert payload["accepted_tokens"] is None
    assert payload["draft_tokens"] is None


def test_telemetry_collector_works_with_no_endpoint():
    """No endpoint configured -> all metrics degrade to None, never raise."""

    async def _body():
        collector = TelemetryCollector(endpoint=None)
        async with collector:
            async with collector.measure_generate() as probe:
                probe.set_usage(_FakeOutput(output_tokens=42))
        return collector.snapshot()

    payload = _run(_body())
    # Without endpoint, MTP cannot be derived.
    assert payload["mtp_acceptance"] is None
    assert payload["accepted_tokens"] is None
    assert payload["draft_tokens"] is None
    # Decode TPS is derived from per-turn samples (we recorded 42 tokens).
    assert payload["decode_tps"] is not None
    assert payload["rounds"] == 1


def test_telemetry_collector_compute_decode_tps_from_usage():
    """decode_tps = total_output_tokens / per_turn_wall_time."""

    async def _body():
        collector = TelemetryCollector(endpoint=None)
        async with collector.measure_generate() as probe:
            probe.set_usage(_FakeOutput(output_tokens=10))
        # Force a deterministic denominator: zero out the actual
        # measured wall time then set a known value.
        last = collector._turns[-1]
        last.wall_s = 0.05
        return collector.snapshot()

    payload = _run(_body())
    # 10 tokens / 0.05s = 200 TPS.
    assert payload["decode_tps"] == pytest.approx(200.0, abs=1e-6)


def test_telemetry_collector_decode_tps_none_for_zero_tokens():

    async def _body():
        collector = TelemetryCollector(endpoint=None)
        async with collector.measure_generate():
            # No usage stamped -> tokens stay 0.
            pass
        return collector.snapshot()

    payload = _run(_body())
    assert payload["decode_tps"] is None


def test_telemetry_collector_attach_writes_to_metadata():

    async def _body():
        collector = TelemetryCollector(endpoint=None)
        metadata: Dict[str, Any] = {}
        async with collector:
            async with collector.measure_generate() as probe:
                probe.set_usage(5)
        collector.attach(metadata)
        return collector, metadata

    collector, metadata = _run(_body())
    assert "telemetry" in metadata
    payload = metadata["telemetry"]
    assert payload["decode_tps"] is not None
    assert payload["rounds"] == 1
    # All optional fields must be JSON-safe.
    json.dumps(payload)


def test_telemetry_collector_attach_rejects_non_dict_metadata():
    collector = TelemetryCollector(endpoint=None)
    with pytest.raises(TypeError):
        collector.attach(metadata=["not", "a", "dict"])  # type: ignore[arg-type]


def test_telemetry_collector_set_usage_accepts_int_and_object():
    collector = TelemetryCollector(endpoint=None)

    async def _body():
        async with collector.measure_generate() as probe:
            recorded = probe.set_usage(7)
            return recorded

    assert _run(_body()) == 7
    # Now an object-mode stamp.
    async def _body2():
        async with collector.measure_generate() as probe:
            return probe.set_usage(_FakeOutput(output_tokens=11))

    assert _run(_body2()) == 11


# ---------------------------------------------------------------------------
# MTP delta math
# ---------------------------------------------------------------------------


def test_mtp_acceptance_from_metrics_deltas():
    """End-to-end delta math driven by a stubbed vLLM endpoint."""
    # First scrape: 1 accepted / 4 drafts; second scrape: add 3 / add 6.
    initial = _build_metrics_text(
        _counter_line("accepted_tokens", 1.0)
        + _counter_line("draft_tokens", 4.0)
    )
    after = _build_metrics_text(
        _counter_line("accepted_tokens", 4.0)
        + _counter_line("draft_tokens", 10.0)
    )
    served_states = iter([initial, after])

    def _handler(client_socket):
        try:
            payload = next(served_states).encode()
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain; version=0.0.4\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + payload
            )
            client_socket.sendall(response)
        finally:
            client_socket.close()

    async def _body():
        port = _start_local_http_server(_handler)
        url = f"http://127.0.0.1:{port}"
        collector = TelemetryCollector(endpoint=url)
        # Drive two separate scrapes so the server serves each
        # payload in turn; the __aenter__/__aexit__ machinery does
        # not help here because it only fetches once per lifecycle.
        before = await collector._fetch_snapshot()
        after = await collector._fetch_snapshot()
        collector._before_snapshot = before
        collector._after_snapshot = after
        return collector.snapshot()

    snapshot = _run(_body())
    # expected delta: 3 accepted / 6 drafts => 0.5 acceptance
    assert snapshot["accepted_tokens"] == pytest.approx(3.0)
    assert snapshot["draft_tokens"] == pytest.approx(6.0)
    assert snapshot["mtp_acceptance"] == pytest.approx(0.5)


def test_mtp_acceptance_none_when_endpoint_returns_no_counters():
    """Empty /metrics body -> mtp_acceptance is None, no crash."""
    text = "# HELP some_other_metric foo\n# TYPE some_other_metric counter\n"
    served_states = iter([text, text])

    def _handler(client_socket):
        try:
            payload = next(served_states).encode()
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain; version=0.0.4\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + payload
            )
            client_socket.sendall(response)
        finally:
            client_socket.close()

    async def _body():
        port = _start_local_http_server(_handler)
        url = f"http://127.0.0.1:{port}"
        collector = TelemetryCollector(endpoint=url)
        before = await collector._fetch_snapshot()
        after = await collector._fetch_snapshot()
        collector._before_snapshot = before
        collector._after_snapshot = after
        return collector.snapshot()

    snapshot = _run(_body())
    assert snapshot["mtp_acceptance"] is None
    assert snapshot["accepted_tokens"] is None
    assert snapshot["draft_tokens"] is None


# ---------------------------------------------------------------------------
# ttft hook
# ---------------------------------------------------------------------------


def test_ttft_hook_populated_first_call_only():

    async def _body():
        collector = TelemetryCollector(
            endpoint=None,
            ttft_hook=lambda wall_s: wall_s * 0.5,
        )
        async with collector.measure_generate() as probe:
            probe.set_usage(1)
        async with collector.measure_generate() as probe:
            probe.set_usage(1)
        return collector.snapshot()

    payload = _run(_body())
    assert payload["ttft_s"] is not None
    # The first non-zero wall time should be recorded (no leaks
    # across turns).
    assert isinstance(payload["ttft_s"], float)


def test_ttft_hook_exceptions_do_not_crash_collector():

    async def _body():
        def bad_hook(_wall: float) -> Optional[float]:
            raise RuntimeError("boom")

        collector = TelemetryCollector(
            endpoint=None,
            ttft_hook=bad_hook,
        )
        async with collector.measure_generate() as probe:
            probe.set_usage(1)
        return collector.snapshot()

    payload = _run(_body())
    assert payload["ttft_s"] is None


def test_ttft_hook_clearable_via_set_ttft_hook_none():

    async def _body():
        collector = TelemetryCollector(
            endpoint=None,
            ttft_hook=lambda wall_s: 0.5,
        )

        async def _turn() -> float:
            async with collector.measure_generate() as probe:
                probe.set_usage(1)
            snap = collector.snapshot()
            return snap["ttft_s"]

        recorded = await _turn()
        collector.set_ttft_hook(None)
        async with collector.measure_generate() as probe:
            probe.set_usage(1)
        snap_after = collector.snapshot()
        return recorded, snap_after["ttft_s"], snap_after["rounds"]

    recorded, ttft_after, rounds = _run(_body())
    # The hook was set before the first turn; the second turn
    # ran with the hook cleared, so ttft_s should NOT have moved.
    assert recorded is not None
    assert ttft_after == pytest.approx(recorded, abs=1e-6)
    assert rounds == 2


# ---------------------------------------------------------------------------
# Metric aggregation
# ---------------------------------------------------------------------------


def _score(value: Any) -> Any:
    """Build a stubbed ``SampleScore`` for the metric test."""

    class _Stub:
        def __init__(self, value: Any) -> None:
            self.value = value
            self.score = None
            self.explanation = None
            self.metadata: Dict[str, Any] = {}

    return _Stub(value)


def test_eds_telemetry_metric_aggregates_with_mixed_none_values():
    metric_fn = eds_telemetry()
    scores = [
        _score({"telemetry": {"ttft_s": 0.10, "decode_tps": 100.0,
                               "mtp_acceptance": 0.6}}),
        _score({"telemetry": {"ttft_s": 0.20, "decode_tps": 200.0,
                               "mtp_acceptance": 0.4}}),
        _score({"telemetry": {"ttft_s": None, "decode_tps": None,
                               "mtp_acceptance": None}}),
        _score({"other": "value"}),  # no telemetry key
    ]
    result = metric_fn(scores)
    assert isinstance(result, dict)
    # Median of 0.10 and 0.20 is 0.15
    assert result["median_ttft_s"] == pytest.approx(0.15, abs=1e-6)
    # Median of 100 and 200 is 150
    assert result["median_decode_tps"] == pytest.approx(150.0, abs=1e-6)
    # Median of 0.6 and 0.4 is 0.5
    assert result["median_mtp_acceptance"] == pytest.approx(0.5, abs=1e-6)
    assert result["sample_count"] == 3  # 1 has no telemetry key
    # 2/3 rounded to 4 decimals -> 0.6667. Inspect AI's metric pipeline
    # applies float() to every returned value, so coverage is exposed
    # at sibling scalar keys rather than under a nested dict.
    assert result["coverage_median_ttft_s"] == pytest.approx(0.6667, abs=1e-4)
    assert result["coverage_median_decode_tps"] == pytest.approx(
        0.6667, abs=1e-4
    )
    assert result["coverage_median_mtp_acceptance"] == pytest.approx(
        0.6667, abs=1e-4
    )
    # All returned values must be scalar so the inspect-ai driver can
    # call float() on them safely.
    for key, value in result.items():
        assert isinstance(value, (int, float, type(None))), (
            f"metric key {key!r} must be scalar for inspect-ai "
            f"compatibility; got {type(value).__name__}"
        )


def test_eds_telemetry_metric_returns_none_when_no_data():
    metric_fn = eds_telemetry()
    result = metric_fn([])
    assert result["median_ttft_s"] is None
    assert result["median_decode_tps"] is None
    assert result["median_mtp_acceptance"] is None
    assert result["sample_count"] == 0
    assert result["coverage_median_ttft_s"] == 0.0
    assert result["coverage_median_decode_tps"] == 0.0
    assert result["coverage_median_mtp_acceptance"] == 0.0


def test_eds_telemetry_metric_tolerates_non_dict_value():
    metric_fn = eds_telemetry()
    scores = [_score("not a dict"), _score(42), _score(None)]
    result = metric_fn(scores)
    assert result["median_ttft_s"] is None
    assert result["sample_count"] == 0
    # All values remain scalars; coverage keys never raise.
    assert result["coverage_median_ttft_s"] == 0.0


# ---------------------------------------------------------------------------
# Integration-style test through mockllm
# ---------------------------------------------------------------------------
#
# We exercise the TelemetryCollector through the real Inspect AI
# eval driver by wrapping the EDS solver with a thin telemetry
# shim inside the test. Wave 1's solver contract is preserved
# (no edits to solver.py) — the shim only reads in-eval sample
# metadata after the underlying solve() returns and stamps the
# telemetry snapshot onto the same dict before pydantic
# serialisation runs.


# Module-level imports + tool so `@mock_tool` can introspect
# ``world: WorldState`` without forward references.
from evalsbench.eds.tools import mock_tool as _mock_tool  # noqa: E402
from evalsbench.eds.world import WorldState as _WorldState  # noqa: E402


@_mock_tool
def _telemetry_stamp(world: _WorldState, value: str = "") -> str:
    """Record a marker for telemetry test purposes.

    Args:
        value: Free-text marker identifying the sample.
    """
    actor = world.get_entity("actor", default="")
    world.set_entity("trail", f"{actor}|{value}")
    return f"{actor}|{value}"


def _integration_episode(*, sample_id: str, fixture_name: str) -> Any:
    """Build a minimal EpisodeSpec for the integration test."""
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

    fixture = WorldFixture(
        name=fixture_name,
        fixture_version="v1",
        state={"counter": 0, "actor": f"actor-{sample_id}"},
        entities={
            "Origin": TaggedEntity(
                provenance=Provenance.CANONICAL,
                payload={"sample_id": sample_id},
            )
        },
    )
    return EpisodeSpec(
        id=f"ep-{sample_id}",
        suite="telemetry-integration",
        version="1.0.0",
        world=fixture,
        actor=Actor(
            principal_id=f"actor-{sample_id}",
            roles=["telemetry-test"],
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
            capability="telemetry",
            trap_class=None,
            difficulty="easy",
            risk_tier="low",
            tags=[sample_id],
        ),
    )


def test_telemetry_attachment_via_inspect_eval_async():
    """End-to-end check: eval_async preserves state.metadata["telemetry"]."""
    from inspect_ai.solver import Generate, Solver, TaskState, solver

    from evalsbench.eds.solver import eds_agent_solver

    episodes = [
        _integration_episode(sample_id="alpha", fixture_name="alpha"),
        _integration_episode(sample_id="beta", fixture_name="beta"),
    ]

    def _resolver(state: TaskState) -> Any:  # noqa: ANN401
        from evalsbench.eds.models import EpisodeSpec

        sid = (state.metadata or {}).get("eds_spec_id")
        for ep in episodes:
            if ep.id == sid:
                return ep
        raise LookupError(sid)

    inner_solver = eds_agent_solver(spec=_resolver, tools=[_telemetry_stamp])

    @solver
    def _wrap_with_telemetry() -> Solver:
        """Compose the EDS solver with a TelemetryCollector stamp.

        The collector is allocated INSIDE the per-sample solve()
        closure — same Wave 1 isolation invariant as the inner
        solver. ``state.metadata["telemetry"]`` is populated
        after the inner solve() returns and before the eval log
        is serialised.
        """

        async def _solve(state: TaskState, generate: Generate) -> TaskState:
            collector = TelemetryCollector(endpoint=None)
            async with collector:
                # Drive one synthetic model.generate turn through
                # the per-episode context manager so the snapshot
                # has a measurable ``decode_tps`` and ``rounds``.
                async with collector.measure_generate() as probe:
                    probe.set_usage(_FakeOutput(output_tokens=12))
                result = await inner_solver(state, generate)
            collector.attach(result.metadata)
            return result

        return _solve

    @task
    def _build_task():
        samples = []
        for ep in episodes:
            samples.append(
                Sample(
                    input=ep.id,
                    target="ok",
                    metadata={
                        "eds_spec_id": ep.id,
                        "role": ep.actor.principal_id,
                        "__eds_scripted_turns__": [
                            ("_telemetry_stamp", {"value": "ready"}),
                        ],
                    },
                )
            )
        from inspect_ai import Task
        return Task(
            dataset=MemoryDataset(samples=samples),
            solver=_wrap_with_telemetry(),
        )

    async def _drive():
        return await eval_async(
            _build_task(),
            max_connections=2,
            model="mockllm/mockllm",
            log_level="warning",
        )

    logs = _run(_drive())
    sample_objs = []
    for log in logs:
        sample_objs.extend(log.samples or [])
    assert len(sample_objs) == len(episodes)
    # Every sample's metadata MUST carry a telemetry dict after
    # the wrapper ran.
    telemetry_payloads = [
        s.metadata.get("telemetry") for s in sample_objs
    ]
    assert all(telemetry_payloads), sample_objs
    for payload in telemetry_payloads:
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
        # Decode TPS was measured; we tolerate either a float or
        # None depending on the actual per-turn wall time.
        assert payload["rounds"] >= 1
        # MTP fields degrade to None when no endpoint is set.
        assert payload["mtp_acceptance"] is None
        assert payload["accepted_tokens"] is None
        assert payload["draft_tokens"] is None


# ---------------------------------------------------------------------------
# Helpers (local HTTP / port discovery)
# ---------------------------------------------------------------------------


def _closed_local_port() -> int:
    """Return a TCP port that is bound then closed (unreachable)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _start_local_http_server(handler, max_connections: int = 8) -> int:
    """Spin up a multi-shot HTTP server on a random free port.

    Accepts up to ``max_connections`` connections (default 8), then
    closes. Each accepted client socket is handed to ``handler``
    which can serve a custom HTTP response.

    Args:
        handler: Callable taking the client socket.
        max_connections: How many connections to accept before
            shutting down.

    Returns:
        int: The TCP port the server is listening on.
    """
    import threading

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(8)
    port = server_sock.getsockname()[1]

    def _serve():
        try:
            for _ in range(max_connections):
                try:
                    client, _ = server_sock.accept()
                except OSError:
                    return
                try:
                    handler(client)
                finally:
                    try:
                        client.close()
                    except OSError:
                        pass
        finally:
            server_sock.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return port
