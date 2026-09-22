"""
Concurrency / race-condition regression guard for the EDS WorldState
mutation surface.

Audit claim under test (Blocker 2 from the EDS reviewer):
    "Inspect AI runs tool calls concurrently in asyncio.gather.
    Neither WorldState.set_entity nor record_event uses locks, causing
    race conditions in parallel tool turns."

Empirical verdict (evidence captured in this file):
    Under the realistic execution paths deployed by
    :func:`evalsbench.eds.tools.bind_tools` (sync tool bodies wrapped
    by an ``async def`` dispatcher with no internal ``await``) the
    ``set_entity`` and ``record_event`` mutations are atomic with
    respect to other in-loop tool coroutines. This holds jointly with
    the parallel-stage scheduling that ``inspect_ai`` performs via
    :func:`inspect_ai.model._call_tools.execute_tools` (anyio task
    group underneath).

The tests below act as a regression guard. If a future maintainer
introduces an ``await`` between a tool body's
``world.set_entity`` / ``world.record_event`` pair, or otherwise
widens the scheduler (threads, off-thread executors) without an
explicit locking decision, the structural invariant below will trip
and force the maintainer to either (a) introduce a lock and the
``tests/eds/test_world_concurrency`` assertions together, or (b)
document the deviation in :mod:`evalsbench.eds.world`.
"""

import asyncio
import inspect

from evalsbench.eds.models import (
    Provenance,
    TaggedEntity,
    WorldFixture,
)
from evalsbench.eds.tools import bind_tools, mock_tool
from evalsbench.eds.world import WorldState


# ---------------------------------------------------------------------------
# Shared helpers and fixtures
# ---------------------------------------------------------------------------


def _build_world() -> WorldState:
    """Construct a fresh WorldState against a minimal counter fixture."""
    return WorldState(
        WorldFixture(
            name="concurrency-guard",
            fixture_version="v1",
            state={"counter": 0, "log": []},
            entities={
                "counter": TaggedEntity(
                    provenance=Provenance.CANONICAL,
                    payload={"default": 0},
                ),
            },
        )
    )


@mock_tool
def increment_counter(world: WorldState, tag: str = "") -> str:
    """Increment ``world.counter`` and append ``tag`` to ``world.log``.

    Sync body (no internal ``await``) -> atomic with respect to other
    coroutines on the same event loop. Mirrors the production MiniCorp
    tool bodies.

    Args:
        tag: Per-call identifier stamped on the log entry.

    Returns:
        The same tag passed in, so the dispatcher records the call.
    """
    current = int(world.get_entity("counter", default=0))
    world.set_entity("counter", current + 1)
    existing = list(world.get_entity("log", default=[]))
    existing.append(tag)
    world.set_entity("log", existing)
    return tag


def _record_event_outcomes(world: WorldState) -> list:
    return [event.outcome for event in world.trace]


# ---------------------------------------------------------------------------
# Regression guard 1: asyncio.gather does NOT lose updates
# ---------------------------------------------------------------------------


def test_asyncio_gather_preserves_count_and_trace_for_sync_tool():
    """Concurrent ``bound[0](...)`` coroutines via ``asyncio.gather``.

    The wrapper's ``async def execute(...)`` has no inner ``await``
    between ``spec.raw_fn(...)`` and ``world.record_event(...)`` so all
    invocations run atomically on a single event-loop thread. This pins
    the no-race invariant under the realistic mini-bench footprint.
    """
    world = _build_world()
    bound = bind_tools(world, [increment_counter], actor="agent-A")
    n = 1000

    async def drive() -> None:
        await asyncio.gather(
            *(bound[0](tag=f"t{i:04d}") for i in range(n))
        )

    asyncio.run(drive())

    assert world.get_entity("counter") == n, (
        "Lost-update race on counter under asyncio.gather of sync tool."
    )
    assert len(world.trace) == n, (
        f"Expected {n} ToolEvent records, got {len(world.trace)}."
    )
    assert _record_event_outcomes(world) == ["ok"] * n, (
        "Mixed-outcome trace indicates wrapper concurrency broke ordering."
    )
    assert len(world.get_entity("log", default=[])) == n


# ---------------------------------------------------------------------------
# Regression guard 2: actual inspect_ai dispatch path
# ---------------------------------------------------------------------------


def test_inspect_ai_execute_tools_path_preserves_count_and_trace():
    """Drive the public ``inspect_ai.model._call_tools.execute_tools``.

    This is the executor the EDS solver relies on
    (:mod:`evalsbench.eds.solver`). Using the real path proves the
    per-tool isolation is preserved across the inspect_ai anyio task
    group.
    """
    from inspect_ai.model import ChatMessageAssistant
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.tool import ToolCall

    world = _build_world()
    bound = bind_tools(world, [increment_counter], actor="agent")
    n = 250

    calls = [
        ToolCall(
            id=f"call_{i}",
            function="increment_counter",
            arguments={"tag": f"i{i:04d}"},
        )
        for i in range(n)
    ]
    message = ChatMessageAssistant(content="forced_for_test", tool_calls=calls)

    async def drive() -> None:
        await execute_tools([message], list(bound))

    asyncio.run(drive())

    assert world.get_entity("counter") == n
    assert len(world.trace) == n


# ---------------------------------------------------------------------------
# Regression guard 3: structural invariant pinned in code
# ---------------------------------------------------------------------------


def test_wrapper_execute_has_no_internal_await_between_raw_fn_and_record():
    """Pin the no-await invariant on the wrapper execute() coroutine.

    The reason ``set_entity`` and the wrapper's ``record_event`` can
    run without a lock is that the dispatcher's async ``execute()``
    function injects NO ``await`` between ``spec.raw_fn(...)`` and
    ``world.record_event(...)``. If any code lands that turns one
    of those into a coroutine suspension point, the single-loop
    atomicity argument changes and an explicit lock must be added.
    This test pins that contract.
    """
    world = _build_world()
    bound = bind_tools(world, [increment_counter], actor="agent")
    bound_callable = bound[0]

    # 1. The wrapper IS an async coroutine function integrating with
    #    inspect_ai's `await tool_def.tool(...)` call site.
    assert inspect.iscoroutinefunction(bound_callable)

    # 2. The wrapper body must NOT contain `await` between
    #    `spec.raw_fn(...)` invocation and the closing
    #    `world.record_event(...)` call. We assert this structurally
    #    by inspecting the source and locating the two markers.
    source = inspect.getsource(bound_callable)
    raw_fn_idx = source.find("spec.raw_fn(world=world,")
    record_event_idx = source.find("world.record_event(")
    assert raw_fn_idx != -1, "Wrapper must call spec.raw_fn(...)"
    assert record_event_idx != -1, (
        "Wrapper must call world.record_event(...) at least once."
    )
    # Slice the wrapper body between the raw_fn call and the FIRST
    # world.record_event call AFTER it. Any await keyword in this
    # region breaks the single-loop atomicity argument.
    region = source[raw_fn_idx:record_event_idx]
    # We tolerate `or` control flow but NOT `await`.
    assert "await" not in region, (
        "Wrapper execute() contains an `await` between the raw_fn "
        "call and the next record_event call. This breaks the "
        "single-event-loop-thread atomicity invariant; either remove "
        "the await or introduce a lock on WorldState.set_entity / "
        ".record_event and update the concurrency regression guard."
    )


# ---------------------------------------------------------------------------
# Regression guard 4: out-of-scope smoke for forced threaded execution
# ---------------------------------------------------------------------------


def test_thread_pool_smoke_assumption_is_documented():
    """Document the threading assumption made by EDS solver.

    The project's :func:`evalsbench.eds.solver.eds_agent_solver` builds
    its per-sample world inside the inner ``solve`` closure and never
    bridges the world into a worker thread. If that policy ever
    changes, the CPython GIL today papers over the simple
    get+set+append triple for moderate N, but the responsible action
    is to introduce an explicit threading lock rather than depend on
    the GIL. This test exists only as a known-limit marker; it does
    NOT assert that the count is correct.
    """
    world = _build_world()
    n = 200
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drive_threaded(world, n))
    finally:
        loop.close()

    # We do NOT assert ``counter == n``. The test simply proves the
    # project can be invoked under threading without crashing; the
    # correctness contract remains unverified by design.
    assert isinstance(world.get_entity("counter"), int)
    assert isinstance(len(world.trace), int)


async def _drive_threaded(world: WorldState, n: int) -> None:
    loop = asyncio.get_running_loop()

    def mutate(i: int) -> None:
        current = int(world.get_entity("counter", default=0))
        world.set_entity("counter", current + 1)
        world.record_event(
            tool="threaded_smoke",
            actor="agent",
            outcome="ok",
            args={"i": i},
        )

    await asyncio.gather(
        *(loop.run_in_executor(None, mutate, i) for i in range(n))
    )


# ---------------------------------------------------------------------------
# Regression guard 5: per-sample isolation survives concurrency
# ---------------------------------------------------------------------------


def test_concurrent_gather_preserves_per_sample_isolation():
    """Two independent WorldState objects must not bleed across siblings.

    Reproduces the closure-isolation invariant validated by
    ``scratch/probe_inspect_closures.py``: each bound Tool closes over
    its own world's reference; a high-fanout concurrent run leaves
    each side's counter == its own N.
    """
    world_a = _build_world()
    world_b = _build_world()
    bound_a = bind_tools(world_a, [increment_counter], actor="agent-A")
    bound_b = bind_tools(world_b, [increment_counter], actor="agent-B")
    n = 200

    async def drive() -> None:
        await asyncio.gather(
            *(bound_a[0](tag=f"a{i:03d}") for i in range(n)),
            *(bound_b[0](tag=f"b{i:03d}") for i in range(n)),
        )

    asyncio.run(drive())

    assert world_a.get_entity("counter") == n
    assert world_b.get_entity("counter") == n
    assert len(world_a.trace) == n
    assert len(world_b.trace) == n
    assert all(ev.actor == "agent-A" for ev in world_a.trace)
    assert all(ev.actor == "agent-B" for ev in world_b.trace)
