"""
EDS scorer utilities (Wave 6 telemetry aggregation).

This subpackage hosts Inspect AI ``@scorer`` and ``@metric``
constructs used to project per-sample telemetry payloads attached
by ``evalsbench.eds.telemetry.TelemetryCollector`` into
run-level aggregates (median TTFT, median decode TPS, median
MTP draft acceptance). Every metric here is offline-first and
returns an empty/``None``-able view when no telemetry data has
been recorded.
"""

from .telemetry_scorer import eds_telemetry

__all__ = ["eds_telemetry"]
