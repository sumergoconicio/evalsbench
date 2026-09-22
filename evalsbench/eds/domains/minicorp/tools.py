"""
MiniCorp mock tools for the EDS subpackage.

File:    evalsbench/eds/domains/minicorp/tools.py
Module:  evalsbench.eds.domains.minicorp
Purpose: The eight canonical MiniCorp tools as
         :func:`@mock_tool <evalsbench.eds.tools.mock_tool>`-decorated
         functions operating on the per-sample
         :class:`~evalsbench.eds.world.WorldState`. All payloads
         inside the ``{"employee": ...}``/``{"available": ...}``/
         ``{"wiki_result": ...}`` envelope shape are kept verbatim from
         the legacy ``lukes-agency/agency_bench.py`` so that scenario
         checkers can be migrated to the EDS episode model without
         re-authoring any assertion logic.

Mutation policy:
    * Reads (``lookup_employee``, ``directory_search``,
      ``check_availability``, ``get_exchange_rate``,
      ``convert_currency``, ``wiki_search``) are pure and never
      write through the world.
    * Writes (``book_meeting_room``, ``create_support_ticket``)
      route through :meth:`WorldState.set_entity <evalsbench.eds.world.WorldState.set_entity>`
      so every mutation is reflected in ``snapshot_diff()``.

Error protocol (Option A):
    Booking conflicts raise :class:`PreconditionFailed` with a
    descriptive message of the form
    ``"Room 'Boardroom' is already booked from 14:00 to 15:00 UTC"``.
    The ``@mock_tool`` decorator wraps that exception into the
    Inspect-safe ``"Error: <message>"`` string the multi-turn loop
    already expects, so the agent never crashes on a precondition
    trip.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...models import PreconditionFailed
from ...tools import mock_tool
from ...world import WorldState
from .fixtures import RATES, ROOMS, SANDBOX_CLOCK, WIKI


# ---------------------------------------------------------------------------
# Module-level helpers (ported verbatim from agency_bench.py)
# ---------------------------------------------------------------------------


def _employee(
    world: WorldState,
    name: Optional[str] = None,
    emp_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Look up the canonical HR record matching ``name`` or ``emp_id``.

    Args:
        world: Per-sample :class:`WorldState` whose ``employees`` list
            is searched.
        name: Free-text name substring (case-insensitive). Whitespace
            is stripped.
        emp_id: Exact employee id (case-insensitive). Compared
            against ``record['id']``.

    Returns:
        A shallow copy of the matching record, or ``None`` when no
        record matches.
    """
    roster = world.get_entity("employees", default=[]) or []
    q = (name or "").strip().lower()
    for record in roster:
        if emp_id and (record.get("id") or "").upper() == emp_id.upper():
            return dict(record)
        if name and q and q in (record.get("name") or "").lower():
            return dict(record)
    return None


def _fmt(record: Dict[str, Any]) -> str:
    """Render an HR record into the canonical one-line text format.

    Args:
        record: A canonical HR record (must carry ``name``, ``id``,
            ``title``, ``department``, ``team``, ``status``).

    Returns:
        str: the single-line employee description that the model
        sees verbatim across scenario checkers.
    """
    return (
        f"{record['name']} (employee id {record['id']}, {record['title']}, "
        f"department {record['department']}, team {record['team']}, "
        f"status {record['status']})"
    )


def _exchange(from_currency: str, to_currency: str) -> Optional[float]:
    """Look up the official conversion rate between two currencies.

    Mirrors the legacy cross-rate-via-EUR behavior so an arbitrary
    supported pair always produces a value (or ``None`` for an
    unsupported code).

    Args:
        from_currency: ISO currency code on the left side of the
            pair (case-insensitive).
        to_currency: ISO currency code on the right side of the pair
            (case-insensitive).

    Returns:
        The conversion rate as a :class:`float`, or ``None`` when no
        conversion path is registered.
    """
    from_up = (from_currency or "").upper()
    to_up = (to_currency or "").upper()
    if from_up in RATES and to_up in RATES[from_up]:
        return RATES[from_up][to_up]
    if (
        from_up in RATES
        and "EUR" in RATES[from_up]
        and from_up != "EUR"
        and to_up in RATES["EUR"]
    ):
        return RATES[from_up]["EUR"] * RATES["EUR"][to_up]
    return None


def _overlaps(
    start_a: str,
    end_a: str,
    start_b: str,
    end_b: str,
) -> bool:
    """Return True iff two booking windows overlap.

    The comparison is performed as direct string inequality on the
    ISO-8601 timestamps because the canonical MiniCorp timestamps
    (``YYYY-MM-DDTHH:MM:SSZ`` and bare ``HH:MM``) are both lexically
    sortable. Two windows [start, end) collide when neither window
    end equals-or-precedes the other window's start; this matches
    the legacy ``lukes-agency`` predicate verbatim so the conflict
    envelope semantics stay identical across the port.

    Args:
        start_a: ISO start of window A.
        end_a: ISO end of window A.
        start_b: ISO start of window B.
        end_b: ISO end of window B.

    Returns:
        bool: True iff a collision is detected.
    """
    return not ((end_a or "") <= (start_b or "") or (start_a or "") >= (end_b or ""))


# ---------------------------------------------------------------------------
# Lookup tools
# ---------------------------------------------------------------------------


@mock_tool
def lookup_employee(
    world: WorldState,
    name: str = "",
    employee_id: str = "",
) -> Dict[str, Any]:
    """Find a specific person by name, employee ID, or email.

    Args:
        name: Person's name (substring match, case-insensitive).
        employee_id: Employee ID like ``"E003"`` (case-insensitive).

    Returns:
        A dict ``{"employee": "<canonical format>"}`` when a match is
        found, or ``{"error": "employee not found"}`` otherwise. The
        model always sees the JSON string emitted by the EDS wrapper.
    """
    record = _employee(world, name=name or None, emp_id=employee_id or None)
    if not record:
        return {"error": "employee not found"}
    return {"employee": _fmt(record)}


@mock_tool
def directory_search(
    world: WorldState,
    department: str = "",
    team: str = "",
    active_only: bool = False,
) -> Dict[str, Any]:
    """List or filter staff by department, team, or active status.

    Args:
        department: Department substring filter (case-insensitive);
            pass an empty string to skip.
        team: Team substring filter (case-insensitive); pass an
            empty string to skip.
        active_only: When True, only employees whose ``status`` is
            ``"Active"`` are returned.

    Returns:
        A dict ``{"employees": [<txt>, ...], "count": <int>}``.
    """
    dept = (department or "").strip().lower()
    team_q = (team or "").strip().lower()
    roster = world.get_entity("employees", default=[]) or []
    rows: List[str] = []
    for record in roster:
        if dept and dept not in (record.get("department") or "").lower():
            continue
        if team_q and team_q not in (record.get("team") or "").lower():
            continue
        if active_only and record.get("status") != "Active":
            continue
        rows.append(_fmt(record))
    return {"employees": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Meeting-room tools (mutation goes through WorldState.set_entity)
# ---------------------------------------------------------------------------


@mock_tool
def book_meeting_room(
    world: WorldState,
    room: str,
    start: str,
    end: str,
) -> Dict[str, Any]:
    """Reserve a room with precise ISO-8601 UTC timestamps.

    Args:
        room: Meeting room name; one of ``Conference Room A``,
            ``Conference Room B``, ``Boardroom``.
        start: ISO-8601 UTC start timestamp (e.g.
            ``"2026-05-29T14:00:00Z"``).
        end: ISO-8601 UTC end timestamp.

    Returns:
        A dict ``{"status": "booked", "room": ..., "start": ...,
        "end": ..., "booking_id": "BK-####"}`` on success.

    Raises:
        PreconditionFailed: if the requested window collides with an
            existing booking. The message follows the Option A
            contract (``"Room '<name>' is already booked from
            <start> to <end> UTC"``) and is surfaced to the model as
            an ``"Error: <message>"`` string.
    """
    existing = list(world.get_entity("bookings", default=[]) or [])
    for booking in existing:
        if (
            (booking.get("room") or "").lower() == (room or "").lower()
            and _overlaps(start, end, booking.get("start", ""), booking.get("end", ""))
        ):
            raise PreconditionFailed(
                (
                    f"Room {room!r} is already booked from "
                    f"{booking.get('start')} to {booking.get('end')} UTC"
                ),
                tool="book_meeting_room",
            )
    new_booking: Dict[str, str] = {"room": room, "start": start, "end": end}
    existing.append(new_booking)
    world.set_entity("bookings", existing)
    return {
        "status": "booked",
        "room": room,
        "start": start,
        "end": end,
        "booking_id": f"BK-{len(existing):04d}",
    }


@mock_tool
def check_availability(
    world: WorldState,
    room: str,
    start: str,
    end: str,
) -> Dict[str, Any]:
    """See whether a room is free for a given ISO-8601 UTC window.

    Args:
        room: Meeting room name.
        start: ISO-8601 UTC start timestamp.
        end: ISO-8601 UTC end timestamp.

    Returns:
        A dict ``{"available": True, "room": ..., "start": ...,
        "end": ...}`` when no collision is found, or
        ``{"available": False, "conflict": <booking>}`` when the
        window collides with an existing booking.
    """
    existing = world.get_entity("bookings", default=[]) or []
    for booking in existing:
        if (
            (booking.get("room") or "").lower() == (room or "").lower()
            and _overlaps(start, end, booking.get("start", ""), booking.get("end", ""))
        ):
            return {"available": False, "conflict": dict(booking)}
    return {"available": True, "room": room, "start": start, "end": end}


# ---------------------------------------------------------------------------
# Support ticket tool
# ---------------------------------------------------------------------------


@mock_tool
def create_support_ticket(
    world: WorldState,
    title: str,
    priority: str,
    assignee: str,
) -> Dict[str, Any]:
    """Log an issue with a priority and assignee.

    Args:
        title: Short text describing the issue.
        priority: Priority tier; one of ``"low"``, ``"medium"``,
            ``"high"``.
        assignee: Employee name or id; resolved to the canonical
            name when a directory match is found.

    Returns:
        A dict ``{"status": "created", "ticket_id": "TCK-0001",
        "title": ..., "priority": ..., "assignee": <resolved_name>}``.
    """
    resolved_employee = _employee(
        world, name=assignee or None, emp_id=assignee or None
    )
    resolved = resolved_employee["name"] if resolved_employee else assignee
    return {
        "status": "created",
        "ticket_id": "TCK-0001",
        "title": title,
        "priority": priority,
        "assignee": resolved,
    }


# ---------------------------------------------------------------------------
# Currency tools
# ---------------------------------------------------------------------------


@mock_tool
def get_exchange_rate(
    world: WorldState,
    from_currency: str,
    to_currency: str,
) -> Dict[str, Any]:
    """Look up an official MiniCorp currency rate.

    Args:
        from_currency: ISO source currency code (``"EUR"``, ``"USD"``,
            ``"JPY"``).
        to_currency: ISO destination currency code (``"EUR"``,
            ``"USD"``, ``"JPY"``).

    Returns:
        A dict ``{"pair": "<from>/<to>", "rate": <float>}`` on
        success, or ``{"error": "rate unavailable"}`` when the rate
        table has no path between the two currencies.
    """
    rate = _exchange(from_currency, to_currency)
    if rate is None:
        return {"error": "rate unavailable"}
    return {"pair": f"{from_currency}/{to_currency}", "rate": rate}


@mock_tool
def convert_currency(
    world: WorldState,
    amount: float,
    from_currency: str,
    to_currency: str,
) -> Dict[str, Any]:
    """Convert an amount between currencies using official MiniCorp rates.

    Cross-rates (e.g. ``USD -> JPY``) are chained through the EUR
    pivot when the direct table does not carry the pair; the helper
    also falls back through EUR when neither side is EUR so every
    supported pair resolves.

    Args:
        amount: Monetary amount to convert.
        from_currency: ISO source currency code (``"EUR"``, ``"USD"``,
            ``"JPY"``).
        to_currency: ISO destination currency code.

    Returns:
        A dict ``{"amount": <rounded>, "currency": <to>,
        "rate_used": <float>}`` on success, or ``{"error":
        "rate unavailable"}`` when the rate table has no path.
    """
    rate = _exchange(from_currency, to_currency)
    if rate is None:
        return {"error": "rate unavailable"}
    converted = round(float(amount) * float(rate), 2)
    return {
        "amount": converted,
        "currency": to_currency,
        "rate_used": rate,
    }


# ---------------------------------------------------------------------------
# Wiki tool (the source of the Alice Chen decoy)
# ---------------------------------------------------------------------------


@mock_tool
def wiki_search(world: WorldState, query: str) -> Dict[str, Any]:
    """Search the company wiki (unofficial user-generated content).

    Args:
        query: Free-text search string.

    Returns:
        A dict ``{"wiki_result": <text>`` when a key matches, or
        ``{"wiki_result": None}`` otherwise. The result is the
        verbatim decoy text for the trap class (e.g. Alice Chen
        claiming Marketing/Brand) and should never be treated as a
        source of canonical HR facts by scoring logic.
    """
    q = (query or "").strip()
    wiki = world.get_entity("wiki", default={}) or {}
    for key, value in wiki.items():
        if (key or "").lower() in q.lower() or q.lower() in (key or "").lower():
            return {"wiki_result": value}
    return {"wiki_result": None}


# ---------------------------------------------------------------------------
# Public aggregate (ordered list mirroring the source TOOLS enumeration)
# ---------------------------------------------------------------------------


#: Ordered tuple of every :func:`@mock_tool <mock_tool>`-decorated
#: MiniCorp tool. Order mirrors ``agency_bench.TOOLS`` so downstream
#: tooling can rebuild the Inspect tool surface deterministically.
MINICORP_TOOLS = (
    lookup_employee,
    directory_search,
    book_meeting_room,
    check_availability,
    create_support_ticket,
    get_exchange_rate,
    convert_currency,
    wiki_search,
)


# ---------------------------------------------------------------------------
# Public re-exports (typed constants for tests / scenario authors)
# ---------------------------------------------------------------------------


__all__ = [
    "MINICORP_TOOLS",
    "SANDBOX_CLOCK",
    "ROOMS",
    "book_meeting_room",
    "check_availability",
    "convert_currency",
    "create_support_ticket",
    "directory_search",
    "get_exchange_rate",
    "lookup_employee",
    "wiki_search",
]
