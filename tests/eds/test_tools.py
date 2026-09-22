"""
Unit tests for evalsbench.eds.tools MockToolSpec capture, exception
classification, and per-sample tool binding.

Covers the basic contract: a valid call mutates the bound world and
appends an 'ok' ToolEvent; precondition failures are converted into
descriptive error strings tagged 'PreconditionFailed'; policy
violations likewise with the 'PolicyViolation' outcome; unexpected
exceptions are logged and surfaced as internal-error strings without
crashing the loop; bind_tools produces per-sample closures that do
not bleed across siblings.

The project does not depend on ``pytest-asyncio``; every async tool
invocation is driven by ``asyncio.run`` inside a synchronous test
function.
"""

import asyncio

import pytest

from evalsbench.eds.models import (
    PolicyViolation,
    PreconditionFailed,
    Provenance,
    TaggedEntity,
    WorldFixture,
)
from evalsbench.eds.tools import (
    MockToolSpec,
    bind_tools,
    is_mock_tool,
    mock_tool,
)
from evalsbench.eds.world import WorldState


# ---------------------------------------------------------------------------
# Sync helper
# ---------------------------------------------------------------------------


def _run(coro):
    """Drive an async coroutine to completion synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_fixture() -> WorldFixture:
    return WorldFixture(
        name="meeting-room-tooling",
        fixture_version="v1",
        state={
            "rooms": {
                "Boardroom": {
                    "bookings": [
                        {"start": "10:00", "end": "11:00", "who": "ops"}
                    ]
                },
                "Huddle": {"bookings": []},
            }
        },
        entities={
            "BookingPolicy": TaggedEntity(
                provenance=Provenance.CANONICAL,
                payload={"lookback": "no_overlap"},
            )
        },
    )


# ---------------------------------------------------------------------------
# Schema capture (mock_tool decorator)
# ---------------------------------------------------------------------------


def test_mock_tool_records_spec_with_public_parameters():
    @mock_tool
    def book(
        world: WorldState,
        room: str,
        start: str,
        end: str,
    ) -> bool:
        """Book a room slot.

        Args:
            room: Name of the room to book.
            start: ISO timestamp for slot start.
            end: ISO timestamp for slot end.
        """
        return True

    assert is_mock_tool(book)
    spec = book.__eds_spec__
    assert isinstance(spec, MockToolSpec)
    assert spec.name == "book"
    assert "Book a room slot." in spec.description
    # The world parameter MUST be filtered out of the public schema.
    assert "world" not in spec.parameters.properties
    public_keys = set(spec.parameters.properties.keys())
    assert public_keys == {"room", "start", "end"}
    assert sorted(spec.parameters.required or []) == ["end", "room", "start"]


def test_mock_tool_supports_world_by_name_convention():
    @mock_tool
    def read(world, key: str = "score") -> int:
        """Read a key from world.

        Args:
            key: Lookup key.
        """
        return 1

    spec = read.__eds_spec__
    assert spec.parameters.properties.keys() == {"key"}


def test_mock_tool_rejects_missing_world_binding():
    with pytest.raises(ValueError, match="WorldState binding"):

        @mock_tool
        def broken(value: int) -> int:
            """No world slot.

            Args:
                value: First operand.
            """
            return value


def test_mock_tool_rejects_multiple_world_bindings():
    with pytest.raises(ValueError, match="multiple world"):

        @mock_tool
        def broken(world: WorldState, world_state: WorldState, value: int) -> int:
            """Two world slots.

            Args:
                value: First operand.
            """
            return value


def test_mock_tool_allows_zero_public_parameters():
    @mock_tool
    def read_status(world: WorldState) -> int:
        """Read status (no model-visible arguments)."""
        return 1

    spec = read_status.__eds_spec__
    assert spec.parameters.properties == {}
    assert (spec.parameters.required or []) == []


def test_mock_tool_placeholder_rejects_direct_invocation():
    @mock_tool
    def pass_through(world: WorldState, x: str = "y") -> str:
        """Pass.

        Args:
            x: Argument.
        """
        return x

    with pytest.raises(RuntimeError, match="bind_tools"):
        pass_through(x="value")


# ---------------------------------------------------------------------------
# Tool execution and event capture (via bind_tools + invoke)
# ---------------------------------------------------------------------------


@mock_tool
def book_room(
    world: WorldState,
    room: str,
    start: str,
    end: str,
) -> bool:
    """Book a room slot.

    Args:
        room: Name of the room to book.
        start: ISO timestamp for slot start.
        end: ISO timestamp for slot end.
    """
    existing = world.get_entity(f"rooms.{room}.bookings", default=[])
    for slot in existing:
        if slot.get("start") == start and slot.get("end") == end:
            raise PreconditionFailed(
                f"Room {room!r} is already booked from {start} to {end} UTC",
                tool="book_room",
            )
    world.set_entity(
        f"rooms.{room}.bookings",
        existing + [{"start": start, "end": end, "who": "agent-A"}],
    )
    return True


@mock_tool
def override_security(world: WorldState, target: str = "vault") -> bool:
    """Attempt to override a security control.

    Args:
        target: System to override.
    """
    raise PolicyViolation(
        f"Override of {target!r} is forbidden by EDS policy.",
        rule="no_override",
        tool="override_security",
    )


@mock_tool
def explode(world: WorldState, payload: str = "") -> str:
    """Raise an unexpected exception for the wrapper to capture.

    Args:
        payload: Free-text payload.
    """
    raise RuntimeError(f"boom: {payload}")


@mock_tool
def read_score(world: WorldState, key: str = "score") -> int:
    """Read a top-level key.

    Args:
        key: Lookup key.
    """
    return int(world.get_entity(key, default=0))


# ---------------------------------------------------------------------------
# Valid-call path mutates world and records 'ok' ToolEvent
# ---------------------------------------------------------------------------


def test_valid_call_mutates_world_and_records_ok():
    fixture = _build_fixture()
    world = WorldState(fixture)
    bound = bind_tools(world, [book_room, read_score], actor="agent-A")

    result = _run(bound[0](room="Huddle", start="13:00", end="14:00"))
    assert result is True
    # The world state has the new booking appended.
    assert world.get_entity("rooms.Huddle.bookings") == [
        {"start": "13:00", "end": "14:00", "who": "agent-A"}
    ]
    # Exactly one ToolEvent recorded with outcome='ok'.
    assert len(world.trace) == 1
    event = world.trace[0]
    assert event.outcome == "ok"
    assert event.tool == "book_room"
    assert event.actor == "agent-A"
    assert event.args == {"room": "Huddle", "start": "13:00", "end": "14:00"}
    assert event.error is None


def test_valid_call_supports_reader_tool_return_strings():
    fixture = _build_fixture()
    world = WorldState(fixture)
    world.set_entity("score", 42)
    bound = bind_tools(world, [read_score], actor="agent-A")
    result = _run(bound[0](key="score"))
    # read_score returns int; the wrapper formats native values as-is.
    assert result == 42
    assert world.trace[0].outcome == "ok"


# ---------------------------------------------------------------------------
# Controlled exceptions return error string and record right outcome
# ---------------------------------------------------------------------------


def test_precondition_failure_returns_error_string_and_records_outcome():
    fixture = _build_fixture()
    world = WorldState(fixture)
    bound = bind_tools(world, [book_room], actor="agent-A")

    result = _run(bound[0](room="Boardroom", start="10:00", end="11:00"))
    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert "Boardroom" in result
    assert "10:00" in result and "11:00" in result
    # The world state MUST NOT have been mutated.
    assert world.get_entity("rooms.Boardroom.bookings") == [
        {"start": "10:00", "end": "11:00", "who": "ops"}
    ]
    # The trace recorded exactly one PreconditionFailed event.
    assert len(world.trace) == 1
    event = world.trace[0]
    assert event.outcome == "PreconditionFailed"
    assert event.tool == "book_room"
    assert event.actor == "agent-A"
    assert event.error is not None
    assert "Boardroom" in event.error


def test_policy_violation_returns_error_string_and_records_outcome():
    fixture = _build_fixture()
    world = WorldState(fixture)
    bound = bind_tools(world, [override_security], actor="agent-A")

    result = _run(bound[0](target="vault"))
    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert "vault" in result
    # No state mutation; trace carries exactly one PolicyViolation event.
    assert len(world.trace) == 1
    event = world.trace[0]
    assert event.outcome == "PolicyViolation"
    assert event.tool == "override_security"
    assert event.actor == "agent-A"
    assert event.error is not None
    assert "no_override" in event.error or "forbidden" in event.error


def test_unexpected_exception_logged_and_surfaces_as_error():
    fixture = _build_fixture()
    world = WorldState(fixture)
    bound = bind_tools(world, [explode], actor="agent-A")

    result = _run(bound[0](payload="kaboom"))
    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert "Internal error" in result
    # Unexpected exceptions are NOT tagged as critical violations so the
    # scorecard safety gate is never tripped by a wrapper bug.
    assert len(world.trace) == 1
    event = world.trace[0]
    assert event.outcome == "PreconditionFailed"
    assert event.tool == "explode"
    assert "boom: kaboom" in (event.error or "")


# ---------------------------------------------------------------------------
# Per-sample closure isolation
# ---------------------------------------------------------------------------


def test_bind_tools_creates_independent_closures_per_call():
    fixture_a = WorldFixture(
        name="alpha",
        fixture_version="v1",
        state={"tag": "A"},
        entities={},
    )
    fixture_b = WorldFixture(
        name="beta",
        fixture_version="v1",
        state={"tag": "B"},
        entities={},
    )
    world_a = WorldState(fixture_a)
    world_b = WorldState(fixture_b)
    bound_a = bind_tools(world_a, [read_score], actor="agent-A")
    bound_b = bind_tools(world_b, [read_score], actor="agent-B")

    # Mutate A's score; B's score MUST stay at its fixture initial.
    world_a.set_entity("score", 7)
    result_a = _run(bound_a[0](key="score"))
    result_b = _run(bound_b[0](key="score"))
    assert result_a == 7
    assert result_b == 0
    # The two bound callables are not the same Python object.
    assert bound_a[0] is not bound_b[0]
    # The trace actors differ.
    assert world_a.trace[0].actor == "agent-A"
    assert world_b.trace[0].actor == "agent-B"


def test_bind_tools_rejects_non_mock_tool_callable():
    fixture = _build_fixture()
    world = WorldState(fixture)
    with pytest.raises(ValueError, match="not an EDS mock tool"):

        def not_a_mock_tool(world, x: int = 0) -> int:
            """Bare function.

            Args:
                x: Oper.
            """
            return x

        bind_tools(world, [not_a_mock_tool], actor="agent")


# ---------------------------------------------------------------------------
# Sanity: the loop never crashes through a mix of outcomes
# ---------------------------------------------------------------------------


def test_loop_does_not_crash_on_outcome_mix():
    fixture = _build_fixture()
    world = WorldState(fixture)
    bound = bind_tools(
        world,
        [book_room, override_security, explode, read_score],
        actor="agent-A",
    )
    for callable_obj, kwargs in [
        (bound[0], {"room": "Huddle", "start": "10:00", "end": "11:00"}),  # ok
        (bound[0], {"room": "Boardroom", "start": "10:00", "end": "11:00"}),  # precfail
        (bound[1], {"target": "vault"}),  # policy
        (bound[2], {"payload": "x"}),  # unexpected
        (bound[3], {"key": "score"}),  # ok
    ]:
        out = _run(callable_obj(**kwargs))
        assert out is not None
    # Five events recorded, in invocation order.
    assert len(world.trace) == 5
    assert [ev.outcome for ev in world.trace] == [
        "ok",
        "PreconditionFailed",
        "PolicyViolation",
        "PreconditionFailed",
        "ok",
    ]
