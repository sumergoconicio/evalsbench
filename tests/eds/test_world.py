"""
Unit tests for evalsbench.eds.world.WorldState copy-on-write isolation,
append-only trace behavior, and structural mutation diffing.
"""

import copy

import pytest

from evalsbench.eds.models import (
    Provenance,
    TaggedEntity,
    ToolEvent,
    WorldFixture,
)
from evalsbench.eds.world import WorldState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_fixture(state: dict) -> WorldFixture:
    return WorldFixture(
        name="kitchen",
        fixture_version="v1",
        state=state,
        entities={
            "door.locked": TaggedEntity(
                provenance=Provenance.CANONICAL,
                payload={"default": True},
            ),
        },
    )


# ---------------------------------------------------------------------------
# Copy-on-write isolation of the upstream WorldFixture
# ---------------------------------------------------------------------------


def test_world_state_constructor_does_not_mutate_fixture_state():
    fixture = _build_fixture(
        {"rooms": {"kitchen": {"lights": "off"}}, "score": 0, "tools": ["knife"]}
    )
    initial_state = copy.deepcopy(fixture.state)
    WorldState(fixture)
    # The upstream fixture state must remain pristine after construction.
    assert fixture.state == initial_state


def test_mutating_world_state_leaves_fixture_unchanged():
    fixture = _build_fixture(
        {"rooms": {"kitchen": {"lights": "off"}}, "score": 0}
    )
    initial_state = copy.deepcopy(fixture.state)
    initial_entities = copy.deepcopy(fixture.entities)

    world = WorldState(fixture)
    world.set_entity("rooms.kitchen.lights", "on")
    world.set_entity("score", 99)
    world.set_entity("rooms.lobby.couch", 1)
    # Mutating nested dictionary in-place must also be safe.
    world._state["rooms"]["kitchen"]["windows"] = 4

    assert fixture.state == initial_state
    assert fixture.entities == initial_entities
    # But the world itself records every change as expected.
    assert world.get_entity("rooms.kitchen.lights") == "on"
    assert world.get_entity("score") == 99
    assert world.get_entity("rooms.lobby.couch") == 1


def test_working_copy_is_topologically_independent_from_pristine_snapshot():
    fixture = _build_fixture({"rooms": {"kitchen": {"lights": "off"}}})
    world = WorldState(fixture)
    world.set_entity("rooms.kitchen.lights", "on")
    assert world._initial["rooms"]["kitchen"]["lights"] == "off"
    # Plain identity check: working state must not share nested objects with the snapshot.
    assert world._initial is not world._state
    assert world._initial["rooms"] is not world._state["rooms"]


# ---------------------------------------------------------------------------
# Entity lookup
# ---------------------------------------------------------------------------


def test_get_entity_resolves_dotted_paths_and_missing_defaults():
    fixture = _build_fixture(
        {"rooms": {"kitchen": {"lights": "off"}}, "score": 0}
    )
    world = WorldState(fixture)
    assert world.get_entity("rooms.kitchen.lights") == "off"
    assert world.get_entity("rooms.kitchen.fridge.units") is None
    assert (
        world.get_entity("rooms.kitchen.fridge.units", default="missing")
        == "missing"
    )
    assert world.get_entity("") is None
    assert world.get_entity("", default=42) == 42


def test_getattr_top_level_facade_and_reserved_names():
    fixture = _build_fixture({"rooms": {"kitchen": {"lights": "off"}}, "score": 0})
    world = WorldState(fixture)
    assert world.score == 0
    assert world.rooms == {"kitchen": {"lights": "off"}}
    # Unknown names must raise AttributeError as standard Python behavior.
    with pytest.raises(AttributeError):
        _ = world.does_not_exist


def test_set_entity_creates_intermediate_dicts_and_rejects_empty_path():
    fixture = _build_fixture({"rooms": {}})
    world = WorldState(fixture)
    world.set_entity("a.b.c", 1)
    assert world.get_entity("a.b.c") == 1
    with pytest.raises(ValueError):
        world.set_entity("", 1)


# ---------------------------------------------------------------------------
# Append-only trace
# ---------------------------------------------------------------------------


def test_trace_accumulates_immutable_events_in_order():
    fixture = _build_fixture({"rooms": {"kitchen": {"lights": "off"}}})
    world = WorldState(fixture)
    ev1 = world.record_event(
        tool="look", actor="agent-L", outcome="ok", args={"room": "kitchen"}
    )
    ev2 = world.record_event(
        tool="open",
        actor="agent-L",
        outcome="PreconditionFailed",
        args={"fridge": True},
        error="fridge closed",
    )
    ev3 = world.record_event(
        tool="delete",
        actor="agent-L",
        outcome="PolicyViolation",
        error="delete forbidden",
    )
    assert world.trace == [ev1, ev2, ev3]
    assert [ev.outcome for ev in world.trace] == [
        "ok",
        "PreconditionFailed",
        "PolicyViolation",
    ]
    assert isinstance(ev1, ToolEvent)
    assert ev2.error == "fridge closed"


def test_record_event_rejects_unsupported_outcome_tag():
    fixture = _build_fixture({"rooms": {}})
    world = WorldState(fixture)
    with pytest.raises(ValueError):
        world.record_event(tool="x", actor="a", outcome="Crash")


def test_trace_events_are_immutable():
    fixture = _build_fixture({"rooms": {}})
    world = WorldState(fixture)
    world.record_event(tool="look", actor="agent", outcome="ok")
    assert len(world.trace) == 1
    # Mutating an already-recorded event must be rejected by the frozen model.
    with pytest.raises(Exception):
        world.trace[0].tool = "mutate"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Structural diff
# ---------------------------------------------------------------------------


def test_snapshot_diff_records_individual_scalar_mutations():
    fixture = _build_fixture(
        {"rooms": {"kitchen": {"lights": "off"}}, "score": 0}
    )
    world = WorldState(fixture)
    world.set_entity("rooms.kitchen.lights", "on")
    world.set_entity("score", 7)
    diff = world.snapshot_diff()
    assert diff["rooms.kitchen.lights"]["before"] == "off"
    assert diff["rooms.kitchen.lights"]["after"] == "on"
    assert diff["score"]["before"] == 0
    assert diff["score"]["after"] == 7


def test_snapshot_diff_records_list_and_added_subtree_mutations():
    fixture = _build_fixture(
        {"rooms": {"kitchen": {"lights": "off"}}, "tools": ["knife"]}
    )
    world = WorldState(fixture)
    world.set_entity("tools", ["knife", "spoon"])
    world.set_entity("rooms.lobby.couch", 1)
    diff = world.snapshot_diff()
    assert diff["tools"]["before"] == ["knife"]
    assert diff["tools"]["after"] == ["knife", "spoon"]
    assert diff["rooms.lobby.couch"]["added"] == 1


def test_snapshot_diff_on_no_mutations_is_empty():
    fixture = _build_fixture({"rooms": {"kitchen": {"lights": "off"}}, "score": 0})
    world = WorldState(fixture)
    assert world.snapshot_diff() == {}
