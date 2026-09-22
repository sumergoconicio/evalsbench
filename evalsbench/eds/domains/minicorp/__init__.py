"""
MiniCorp domain for the EDS subpackage.

Provides the ``minicorp_fixture`` factory (Wave 2 deliverable) and the
eight :func:`@mock_tool <evalsbench.eds.tools.mock_tool>`-decorated
tools (lookup, directory, booking, ticket, currency, wiki) ported
verbatim from the canonical ``lukes-agency/agency_bench.py`` source so
that scenario checkers can be migrated to the EDS episode model without
re-authoring any tool semantics.

The accompanying ``tasks.py`` carrying the EpisodeSpec templates and
scenario checkers is owned by another wave and intentionally not
included here.
"""

from .fixtures import (
    BOOKINGS,
    EMPLOYEES,
    RATES,
    ROOMS,
    SANDBOX_CLOCK,
    WIKI,
    minicorp_fixture,
)
from .tools import (
    MINICORP_TOOLS,
    book_meeting_room,
    check_availability,
    convert_currency,
    create_support_ticket,
    directory_search,
    get_exchange_rate,
    lookup_employee,
    wiki_search,
)

__all__ = [
    "SANDBOX_CLOCK",
    "EMPLOYEES",
    "RATES",
    "ROOMS",
    "BOOKINGS",
    "WIKI",
    "minicorp_fixture",
    "MINICORP_TOOLS",
    "lookup_employee",
    "directory_search",
    "book_meeting_room",
    "check_availability",
    "create_support_ticket",
    "get_exchange_rate",
    "convert_currency",
    "wiki_search",
]
