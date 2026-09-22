"""
Unit tests for the MiniCorp EDS fixture factory.

Covers:
    * The :func:`minicorp_fixture` factory returning a validated
      :class:`WorldFixture` with the canonical sandbox-clock constant
      and the six top-level state keys (employees, rates, rooms,
      bookings, wiki, sandbox_clock).
    * Per-entity provenance tagging: every HR employee carries the
      ``canonical`` tier; every wiki entry (the Alice Chen trap) is
      flagged ``advisory``; no ``unverified`` entries are produced
      by the default fixture.
    * Copy-on-write isolation between the module-level constants
      (``EMPLOYEES``, ``RATES``, ``ROOMS``, ``BOOKINGS``, ``WIKI``)
      and any state inside a constructed :class:`WorldState`.
    * Round-trip fidelity through the Pydantic v2 dump / validate
      cycle so tasks.py (Wave 3) can serialize fixtures safely.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import TypeAdapter, ValidationError

from evalsbench.eds.domains.minicorp import (
    BOOKINGS,
    EMPLOYEES,
    RATES,
    ROOMS,
    SANDBOX_CLOCK,
    WIKI,
    minicorp_fixture,
)
from evalsbench.eds.domains.minicorp.fixtures import (
    SANDBOX_CLOCK as FIXTURE_SANDBOX_CLOCK,
)
from evalsbench.eds.models import Provenance, WorldFixture
from evalsbench.eds.world import WorldState


# ---------------------------------------------------------------------------
# Public constant surface
# ---------------------------------------------------------------------------


def test_sandbox_clock_constant_matches_documented_iso_string():
    """The exported sandbox clock is the canonical 2026-05-28T10:00:00Z."""
    assert SANDBOX_CLOCK == "2026-05-28T10:00:00Z"
    # The re-export inside fixtures module keeps the value in sync.
    assert FIXTURE_SANDBOX_CLOCK == SANDBOX_CLOCK


def test_module_constants_have_documented_shape():
    """The module-level constants carry the agreed-upon carrier types."""
    assert isinstance(EMPLOYEES, list) and len(EMPLOYEES) == 10
    assert isinstance(RATES, dict) and set(RATES) == {"EUR", "USD", "JPY"}
    assert isinstance(ROOMS, list) and len(ROOMS) == 3
    assert isinstance(BOOKINGS, list) and BOOKINGS == []
    assert isinstance(WIKI, dict) and "Alice Chen" in WIKI
    assert (
        WIKI["Alice Chen"]
        == "Alice Chen — Marketing department, joined 2024-03-11. Fact sheet says team: Brand."
    )


# ---------------------------------------------------------------------------
# Fixture validation
# ---------------------------------------------------------------------------


def test_minicorp_fixture_returns_validated_world_fixture():
    fixture = minicorp_fixture()
    assert isinstance(fixture, WorldFixture)
    assert fixture.name == "minicorp"
    assert fixture.fixture_version == "2026.05.28"


def test_minicorp_fixture_state_carries_six_required_keys():
    fixture = minicorp_fixture()
    expected = {
        "employees",
        "rates",
        "rooms",
        "bookings",
        "wiki",
        "sandbox_clock",
    }
    assert expected.issubset(set(fixture.state))
    # State values match their respective module constants at construction.
    assert fixture.state["sandbox_clock"] == SANDBOX_CLOCK
    assert fixture.state["rooms"] == ROOMS
    assert fixture.state["rates"] == RATES
    assert fixture.state["wiki"] == WIKI
    assert fixture.state["bookings"] == []
    # The employees list inside the fixture is a deep copy, not the
    # same list object as the module-level EMPLOYEES.
    assert fixture.state["employees"] == EMPLOYEES
    assert fixture.state["employees"] is not EMPLOYEES


def test_minicorp_fixture_accepts_custom_name_and_version():
    fixture = minicorp_fixture(name="derived", fixture_version="2026.06.01")
    assert fixture.name == "derived"
    assert fixture.fixture_version == "2026.06.01"


def test_minicorp_fixture_rejects_blank_name():
    """A blank fixture name violates the WorldFixture min_length=1 rule."""
    with pytest.raises(ValidationError):
        minicorp_fixture(name="")


# ---------------------------------------------------------------------------
# Provenance tagging
# ---------------------------------------------------------------------------


def test_every_employee_record_is_tagged_canonical():
    fixture = minicorp_fixture()
    employee_entities = {
        key: entity
        for key, entity in fixture.entities.items()
        if key.startswith("employee.")
    }
    # One entity per HR record; ordering matches the EMPLOYEES list order.
    expected_keys = {f"employee.{record['id']}" for record in EMPLOYEES}
    assert set(employee_entities) == expected_keys
    for entity in employee_entities.values():
        assert entity.provenance == Provenance.CANONICAL
    # Each canonical payload carries the named HR row.
    for record in EMPLOYEES:
        canonical = employee_entities[f"employee.{record['id']}"]
        assert canonical.payload["record"]["id"] == record["id"]


def test_alice_chen_wiki_decoy_is_tagged_advisory():
    fixture = minicorp_fixture()
    wiki_entities = {
        key: entity
        for key, entity in fixture.entities.items()
        if key.startswith("wiki.")
    }
    assert "wiki.Alice Chen" in wiki_entities
    decoy = wiki_entities["wiki.Alice Chen"]
    assert decoy.provenance == Provenance.ADVISORY
    assert decoy.payload["query"] == "Alice Chen"
    assert "Marketing" in decoy.payload["content"]


def test_minicorp_fixture_never_emits_unverified_provenance():
    fixture = minicorp_fixture()
    provenance_tiers = {entity.provenance for entity in fixture.entities.values()}
    # The default MiniCorp fixture carries only canonical + advisory tiers.
    assert Provenance.UNVERIFIED not in provenance_tiers
    assert provenance_tiers == {Provenance.CANONICAL, Provenance.ADVISORY}


# ---------------------------------------------------------------------------
# Copy-on-write isolation
# ---------------------------------------------------------------------------


def test_world_state_mutation_does_not_leak_back_into_fixture_or_constants():
    fixture = minicorp_fixture()
    employees_snapshot = copy.deepcopy(EMPLOYEES)
    rates_snapshot = copy.deepcopy(RATES)
    rooms_snapshot = copy.deepcopy(ROOMS)
    wiki_snapshot = copy.deepcopy(WIKI)
    bookings_snapshot = copy.deepcopy(BOOKINGS)

    world = WorldState(fixture)
    # Mutating each top-level key inside the WorldState leaves the
    # upstream fixture and module constants pristine.
    world.set_entity("bookings", [{"room": "Boardroom", "start": "X", "end": "Y"}])
    world.set_entity("rooms", ["New Room A", "New Room B"])
    new_employees = list(world.get_entity("employees"))
    new_employees[0]["name"] = "Mutated Name"
    world.set_entity("employees", new_employees)
    world.set_entity("rates", {"EUR": {"EUR": 1.0}})
    world.set_entity("wiki", {})
    world.set_entity("sandbox_clock", "2099-01-01T00:00:00Z")

    # Module-level constants are untouched.
    assert EMPLOYEES == employees_snapshot
    assert RATES == rates_snapshot
    assert ROOMS == rooms_snapshot
    assert BOOKINGS == bookings_snapshot
    assert WIKI == wiki_snapshot
    # And the upstream fixture object is also untouched.
    assert fixture.state["bookings"] == []
    assert fixture.state["rooms"] == ROOMS
    assert fixture.state["employees"] == EMPLOYEES
    assert fixture.state["rates"] == RATES
    assert fixture.state["wiki"] == WIKI
    assert fixture.state["sandbox_clock"] == SANDBOX_CLOCK


def test_world_state_constructor_does_not_mutate_fixture_state():
    fixture = minicorp_fixture()
    initial_state = copy.deepcopy(fixture.state)
    WorldState(fixture)
    # Building the WorldState must not touch the fixture's state dict.
    assert fixture.state == initial_state


# ---------------------------------------------------------------------------
# Round-trip and downstream reuse
# ---------------------------------------------------------------------------


def test_minicorp_fixture_survives_pydantic_round_trip():
    """A JSON dump + validate cycle produces an equal fixture."""
    fixture = minicorp_fixture()
    adapter = TypeAdapter(WorldFixture)
    json_payload = fixture.model_dump(mode="json")
    rebuilt = adapter.validate_python(json_payload)
    assert rebuilt == fixture
    # The rebuilt fixture's state is the exact same data even after
    # being copied through JSON-serializable primitives.
    assert rebuilt.state["sandbox_clock"] == SANDBOX_CLOCK
    assert len(rebuilt.entities) == len(fixture.entities)


def test_minicorp_fixture_supports_multiple_independent_worlds():
    """Two worlds built from the same fixture do not share state.

    The copy-on-write contract guarantees that mutations in one world
    are invisible to a sibling world constructed from the same
    fixture; this is the same isolation the Wave 0/1 contract tests.
    """
    fixture = minicorp_fixture()
    world_a = WorldState(fixture)
    world_b = WorldState(fixture)
    world_a.set_entity("bookings", [{"room": "Boardroom", "start": "10:00", "end": "11:00"}])
    assert world_b.get_entity("bookings") == []
    assert world_a.get_entity("bookings") == [
        {"room": "Boardroom", "start": "10:00", "end": "11:00"}
    ]
