"""
Unit tests for the MiniCorp EDS mock tools.

Covers:
    * Happy path for every one of the eight MiniCorp tools
      (``lookup_employee``, ``directory_search``,
      ``book_meeting_room``, ``check_availability``,
      ``create_support_ticket``, ``get_exchange_rate``,
      ``convert_currency``, ``wiki_search``).
    * The booking-conflict path: a duplicate reservation raises
      :class:`PreconditionFailed`, returns the descriptive error
      string ``"Error: Room 'X' is already booked from A to B UTC"``,
      and does NOT mutate :attr:`WorldState.bookings`.
    * Cross-rate conversion math for the two anchor scenarios
      (``500 EUR -> USD = 550.0``, ``100 USD -> JPY = 15000.0``).
    * The wiki decoy returns the Alice Chen trap text and stamps the
      advisory provenance tier via the entity map.
    * The aggregate ``MINICORP_TOOLS`` exposes all eight tools in the
      canonical order (no spurious cancel_booking / submit_expense
      entries).
    * Every successful tool invocation appends exactly one
      ``ToolEvent`` with outcome ``"ok"`` to ``world.trace``.

The project does not depend on ``pytest-asyncio``; every async tool
invocation is driven by ``asyncio.run`` inside a synchronous test
function.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from evalsbench.eds.domains.minicorp import (
    MINICORP_TOOLS,
    SANDBOX_CLOCK,
    minicorp_fixture,
)
from evalsbench.eds.domains.minicorp.tools import (
    book_meeting_room,
    check_availability,
    convert_currency,
    create_support_ticket,
    directory_search,
    get_exchange_rate,
    lookup_employee,
    wiki_search,
)
from evalsbench.eds.models import (
    PreconditionFailed,
    Provenance,
    TaggedEntity,
    WorldFixture,
)
from evalsbench.eds.tools import bind_tools, is_mock_tool
from evalsbench.eds.world import WorldState


# ---------------------------------------------------------------------------
# Sync helper
# ---------------------------------------------------------------------------


def _run(coro):
    """Drive an async coroutine to completion synchronously."""
    return asyncio.run(coro)


def _build_world() -> WorldState:
    """Return a fresh WorldState seeded from the canonical MiniCorp fixture."""
    return WorldState(minicorp_fixture())


def _bind(world: WorldState, *tool_fns):
    """Pin a set of MiniCorp tools to a per-sample world."""
    return bind_tools(world, list(tool_fns), actor="minicorp-agent")


def _json_payload(result):
    """Reverse the EDS wrapper's json.dumps for dict-returning tools."""
    if isinstance(result, dict):
        return result
    try:
        return json.loads(result)
    except (TypeError, ValueError):
        # Errors are surfaced as plain strings; return raw so callers can
        # assert on the descriptive message prefix directly.
        return result


# ---------------------------------------------------------------------------
# Aggregate MINICORP_TOOLS surface
# ---------------------------------------------------------------------------


def test_minicorp_tools_are_eight_and_match_canonical_names():
    """Eight tools in the canonical order from agency_bench.py."""
    expected = (
        lookup_employee,
        directory_search,
        book_meeting_room,
        check_availability,
        create_support_ticket,
        get_exchange_rate,
        convert_currency,
        wiki_search,
    )
    assert MINICORP_TOOLS == expected
    assert len(MINICORP_TOOLS) == 8
    for fn in MINICORP_TOOLS:
        assert is_mock_tool(fn)


def test_minicorp_tools_exclude_invented_names():
    """The implementation plan referenced cancel_booking and submit_expense;
    neither exists in the canonical source harness and both must be absent."""
    canonical_names = {fn.__name__ for fn in MINICORP_TOOLS}
    assert "cancel_booking" not in canonical_names
    assert "submit_expense" not in canonical_names


# ---------------------------------------------------------------------------
# lookup_employee (read tool, no mutation)
# ---------------------------------------------------------------------------


def test_lookup_employee_returns_canonical_format_for_alice_chen():
    world = _build_world()
    bound = _bind(world, lookup_employee)
    result = _run(bound[0](name="Alice Chen"))
    payload = _json_payload(result)
    assert "employee" in payload
    # The format string is preserved verbatim from _fmt in agency_bench.
    assert (
        payload["employee"]
        == "Alice Chen (employee id E001, Engineer, department Engineering, "
        "team Eng Core, status Active)"
    )


def test_lookup_employee_by_employee_id_case_insensitive():
    world = _build_world()
    bound = _bind(world, lookup_employee)
    result = _run(bound[0](employee_id="e003"))
    payload = _json_payload(result)
    assert payload["employee"].startswith("Carol Nguyen")


def test_lookup_employee_returns_error_when_not_found():
    world = _build_world()
    bound = _bind(world, lookup_employee)
    result = _run(bound[0](name="Nobody Here"))
    payload = _json_payload(result)
    assert payload == {"error": "employee not found"}


# ---------------------------------------------------------------------------
# directory_search
# ---------------------------------------------------------------------------


def test_directory_search_filters_by_department():
    world = _build_world()
    bound = _bind(world, directory_search)
    # department=Engineering → 4 employees (Alice, Dana, Frank + ...)
    result = _run(bound[0](department="Engineering"))
    payload = _json_payload(result)
    assert payload["count"] == 3
    assert all("department Engineering" in row for row in payload["employees"])


def test_directory_search_active_only_excludes_inactive_employees():
    world = _build_world()
    bound = _bind(world, directory_search)
    result = _run(bound[0](active_only=True))
    payload = _json_payload(result)
    # Ivy Patel (E009) is Inactive and must be excluded.
    assert payload["count"] == 9
    assert not any("Ivy Patel" in row for row in payload["employees"])
    assert any("Jack Brown" in row for row in payload["employees"])


def test_directory_search_team_filter_combines_with_active_only():
    world = _build_world()
    bound = _bind(world, directory_search)
    result = _run(bound[0](team="Support", active_only=True))
    payload = _json_payload(result)
    names = [row.split(" (")[0] for row in payload["employees"]]
    assert payload["count"] == 3
    assert set(names) == {"Carol Nguyen", "Grace Lee", "Henry Miller"}


# ---------------------------------------------------------------------------
# book_meeting_room and check_availability
# ---------------------------------------------------------------------------


def test_book_meeting_room_success_writes_through_worldstate():
    world = _build_world()
    bound = _bind(world, book_meeting_room, check_availability)
    start = "2026-05-29T14:00:00Z"
    end = "2026-05-29T15:00:00Z"
    result = _run(bound[0](room="Conference Room B", start=start, end=end))
    payload = _json_payload(result)
    assert payload["status"] == "booked"
    assert payload["room"] == "Conference Room B"
    assert payload["start"] == start and payload["end"] == end
    assert payload["booking_id"] == "BK-0001"
    # The mutation is recorded on the world.
    assert world.get_entity("bookings") == [
        {"room": "Conference Room B", "start": start, "end": end}
    ]


def test_book_meeting_room_conflict_returns_descriptive_error_and_does_not_mutate():
    world = _build_world()
    bound = _bind(world, book_meeting_room)
    # Seed one booking through the public WorldState mutation API so the
    # fixture-style empty bookings list is exercised end-to-end.
    world.set_entity(
        "bookings",
        [{"room": "Boardroom", "start": "10:00", "end": "11:00"}],
    )
    initial_bookings = list(world.get_entity("bookings"))

    # An overlapping window must trip Option A: a descriptive error
    # string that the model sees verbatim, plus zero state change.
    result = _run(
        bound[0](room="Boardroom", start="10:30", end="11:30")
    )
    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert "'Boardroom'" in result
    assert "10:00" in result and "11:00" in result
    # The bookings list remains untouched.
    assert world.get_entity("bookings") == initial_bookings
    # The ToolEvent records a PreconditionFailed outcome with the same error.
    assert len(world.trace) == 1
    event = world.trace[0]
    assert event.outcome == "PreconditionFailed"
    assert event.tool == "book_meeting_room"
    assert event.error and "Boardroom" in event.error


def test_book_meeting_room_conflict_supports_non_overlapping_window():
    """Adjacent-but-disjoint windows must NOT collide."""
    world = _build_world()
    world.set_entity(
        "bookings",
        [{"room": "Boardroom", "start": "10:00", "end": "11:00"}],
    )
    bound = _bind(world, book_meeting_room)
    result = _run(
        bound[0](room="Boardroom", start="11:00", end="12:00")
    )
    payload = _json_payload(result)
    assert payload["status"] == "booked"
    assert payload["start"] == "11:00"
    # Successful booking appended.
    assert len(world.get_entity("bookings")) == 2
    assert world.get_entity("bookings")[1] == {
        "room": "Boardroom",
        "start": "11:00",
        "end": "12:00",
    }


def test_check_availability_returns_true_when_free():
    world = _build_world()
    bound = _bind(world, check_availability)
    result = _run(
        bound[0](
            room="Conference Room A",
            start="2026-05-29T09:00:00Z",
            end="2026-05-29T10:00:00Z",
        )
    )
    payload = _json_payload(result)
    assert payload["available"] is True
    assert "conflict" not in payload


def test_check_availability_returns_conflict_dict_when_busy():
    world = _build_world()
    world.set_entity(
        "bookings",
        [
            {
                "room": "Conference Room A",
                "start": "2026-05-29T09:00:00Z",
                "end": "2026-05-29T10:00:00Z",
            }
        ],
    )
    bound = _bind(world, check_availability)
    result = _run(
        bound[0](
            room="Conference Room A",
            start="2026-05-29T09:30:00Z",
            end="2026-05-29T10:30:00Z",
        )
    )
    payload = _json_payload(result)
    assert payload["available"] is False
    assert payload["conflict"]["room"] == "Conference Room A"
    assert payload["conflict"]["start"] == "2026-05-29T09:00:00Z"


# ---------------------------------------------------------------------------
# create_support_ticket
# ---------------------------------------------------------------------------


def test_create_support_ticket_resolves_assignee_to_canonical_name():
    world = _build_world()
    bound = _bind(world, create_support_ticket)
    result = _run(
        bound[0](title="Budget sign-off", priority="medium", assignee="E004")
    )
    payload = _json_payload(result)
    assert payload["status"] == "created"
    assert payload["ticket_id"] == "TCK-0001"
    assert payload["title"] == "Budget sign-off"
    assert payload["priority"] == "medium"
    # E004 resolves to Dana Smith, the Head of Engineering.
    assert payload["assignee"] == "Dana Smith"


def test_create_support_ticket_passes_through_unresolved_assignee():
    world = _build_world()
    bound = _bind(world, create_support_ticket)
    result = _run(
        bound[0](title="Out-of-band", priority="high", assignee="Zxx Unknown")
    )
    payload = _json_payload(result)
    assert payload["assignee"] == "Zxx Unknown"


# ---------------------------------------------------------------------------
# Currency tools (cross-rate math)
# ---------------------------------------------------------------------------


def test_get_exchange_rate_direct_pair_eur_usd():
    world = _build_world()
    bound = _bind(world, get_exchange_rate)
    result = _run(bound[0](from_currency="EUR", to_currency="USD"))
    payload = _json_payload(result)
    assert payload == {"pair": "EUR/USD", "rate": 1.1}


def test_convert_currency_500_eur_to_usd_is_550_dot_zero():
    """Anchor scenario: 500 EUR -> USD via direct rate 1.1 = 550.0."""
    world = _build_world()
    bound = _bind(world, convert_currency)
    result = _run(
        bound[0](amount=500, from_currency="EUR", to_currency="USD")
    )
    payload = _json_payload(result)
    assert payload["amount"] == 550.0
    assert payload["currency"] == "USD"
    assert payload["rate_used"] == 1.1


def test_convert_currency_100_usd_to_jpy_is_15000_dot_zero():
    """Anchor scenario: 100 USD -> JPY via direct rate 150 = 15000.0."""
    world = _build_world()
    bound = _bind(world, convert_currency)
    result = _run(
        bound[0](amount=100, from_currency="USD", to_currency="JPY")
    )
    payload = _json_payload(result)
    assert payload["amount"] == 15000.0
    assert payload["currency"] == "JPY"
    assert payload["rate_used"] == 150.0


def test_convert_currency_returns_error_when_rate_unavailable():
    """An unsupported currency code yields the legacy error envelope."""
    world = _build_world()
    bound = _bind(world, convert_currency)
    result = _run(
        bound[0](amount=10, from_currency="XYZ", to_currency="EUR")
    )
    payload = _json_payload(result)
    assert payload == {"error": "rate unavailable"}


# ---------------------------------------------------------------------------
# wiki_search (the Alice Chen decoy route)
# ---------------------------------------------------------------------------


def test_wiki_search_returns_alice_chen_decoy_text():
    """The wiki yields the Marketing/Brand decoy text — NOT canonical HR."""
    world = _build_world()
    bound = _bind(world, wiki_search)
    result = _run(bound[0](query="Alice Chen"))
    payload = _json_payload(result)
    assert "wiki_result" in payload
    decoy = payload["wiki_result"]
    assert "Marketing" in decoy
    assert "Brand" in decoy


def test_wiki_search_returns_none_for_unknown_query():
    world = _build_world()
    bound = _bind(world, wiki_search)
    result = _run(bound[0](query="Nobody"))
    payload = _json_payload(result)
    assert payload == {"wiki_result": None}


def test_wiki_entry_in_fixture_is_tagged_advisory():
    """The provenance of the Alice Chen decoy is locked at ``advisory``."""
    fixture = minicorp_fixture()
    decoy_entity = fixture.entities.get("wiki.Alice Chen")
    assert decoy_entity is not None
    assert isinstance(decoy_entity, TaggedEntity)
    assert decoy_entity.provenance == Provenance.ADVISORY


# ---------------------------------------------------------------------------
# ToolEvent integration (every successful call records ``outcome == "ok"``)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_fn, kwargs",
    [
        (lookup_employee, {"name": "Alice Chen"}),
        (directory_search, {"department": "Engineering"}),
        (book_meeting_room, {
            "room": "Conference Room A",
            "start": "2026-05-29T09:00:00Z",
            "end": "2026-05-29T10:00:00Z",
        }),
        (check_availability, {
            "room": "Conference Room A",
            "start": "2026-05-29T11:00:00Z",
            "end": "2026-05-29T12:00:00Z",
        }),
        (create_support_ticket, {
            "title": "Follow-up",
            "priority": "low",
            "assignee": "Grace Lee",
        }),
        (get_exchange_rate, {"from_currency": "EUR", "to_currency": "JPY"}),
        (convert_currency, {
            "amount": 50,
            "from_currency": "EUR",
            "to_currency": "JPY",
        }),
        (wiki_search, {"query": "Alice Chen"}),
    ],
)
def test_each_tool_records_one_ok_tool_event(tool_fn, kwargs):
    """A successful invocation records exactly one ``ok`` ToolEvent."""
    world = _build_world()
    bound = _bind(world, tool_fn)
    result = _run(bound[0](**kwargs))
    assert result is not None
    assert len(world.trace) == 1
    event = world.trace[0]
    assert event.tool == tool_fn.__name__
    assert event.outcome == "ok"
    assert event.actor == "minicorp-agent"
    assert event.error is None
    # The recorded args match what we dispatched (the world binding slot
    # was filtered out by the @mock_tool decorator).
    assert set(event.args) == set(kwargs)


def test_tool_event_recovers_precondition_failed_for_booking_conflict():
    """A failed booking path records the controlled-failure outcome."""
    world = _build_world()
    world.set_entity(
        "bookings",
        [{"room": "Boardroom", "start": "10:00", "end": "11:00"}],
    )
    bound = _bind(world, book_meeting_room)
    result = _run(bound[0](room="Boardroom", start="10:30", end="11:30"))
    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert len(world.trace) == 1
    event = world.trace[0]
    assert event.tool == "book_meeting_room"
    assert event.outcome == "PreconditionFailed"
    assert event.error is not None
    assert "'Boardroom'" in event.error


def test_full_scenario_no_world_state_bleed_across_samples():
    """Two parallel WorldStates do not share per-sample tool state."""
    fixture = minicorp_fixture()
    world_a = WorldState(fixture)
    world_b = WorldState(fixture)
    bound_a = _bind(world_a, book_meeting_room, lookup_employee)
    bound_b = _bind(world_b, book_meeting_room, lookup_employee)

    result_booking = _run(
        bound_a[0](
            room="Conference Room B",
            start="2026-05-29T14:00:00Z",
            end="2026-05-29T15:00:00Z",
        )
    )
    payload_booking = _json_payload(result_booking)
    assert payload_booking["status"] == "booked"
    # A's booking is visible only inside A.
    assert world_a.get_entity("bookings") and not world_b.get_entity("bookings")
    # A's bookings snapshot reflects the new entry.
    assert world_a.get_entity("bookings") == [
        {
            "room": "Conference Room B",
            "start": "2026-05-29T14:00:00Z",
            "end": "2026-05-29T15:00:00Z",
        }
    ]
    # Lookup runs on each world independently; both return Alice Chen.
    assert _json_payload(_run(bound_a[1](name="Alice Chen")))["employee"].startswith(
        "Alice Chen"
    )
    assert _json_payload(_run(bound_b[1](name="Alice Chen")))["employee"].startswith(
        "Alice Chen"
    )
    # The actor stamp is identical across both worlds (closured by bind_tools).
    assert {event.actor for event in world_a.trace} == {"minicorp-agent"}
    assert {event.actor for event in world_b.trace} == {"minicorp-agent"}
    # A's trace holds the 2 calls we made; B's trace holds only its 1 call.
    assert len(world_a.trace) == 2
    assert len(world_b.trace) == 1
    assert world_a.trace[0].tool == "book_meeting_room"
    assert world_a.trace[1].tool == "lookup_employee"
    assert world_b.trace[0].tool == "lookup_employee"
    # The clock is identical to the public re-export.
    assert world_a.get_entity("sandbox_clock") == SANDBOX_CLOCK


# ---------------------------------------------------------------------------
# Negative regression: docs reference PreconditionFailed as a typed exception
# ---------------------------------------------------------------------------


def test_precondition_failed_is_a_typed_domain_exception():
    """The Option A error contract is wired to a typed exception.

    The booking-conflict path raises :class:`PreconditionFailed` so the
    EDS tool wrapper (already covered in ``test_tools.py``) can convert
    it into the descriptive ``"Error: <message>"`` string without
    crashing the multi-turn loop.
    """
    world = _build_world()
    world.set_entity(
        "bookings",
        [{"room": "Boardroom", "start": "10:00", "end": "11:00"}],
    )
    with pytest.raises(PreconditionFailed) as exc_info:
        # Direct invocation of the raw mock tool function bypasses
        # bind_tools; that lets us prove the typed exception is raised
        # before the wrapper formats it into an error string.
        book_meeting_room.__eds_spec__.raw_fn(
            world=world, room="Boardroom", start="10:30", end="11:30"
        )
    message = str(exc_info.value)
    assert "'Boardroom'" in message
    assert "10:00" in message and "11:00" in message
