"""
Run-level telemetry aggregation for the EDS subpackage.

File:    evalsbench/eds/scorers/telemetry_scorer.py
Module:  evalsbench.eds.scorers
Purpose: Aggregate per-sample telemetry snapshots attached by
         :mod:`evalsbench.eds.telemetry` into run-level metrics
         (median TTFT, median decode TPS, median MTP draft
         acceptance). The metric is exposed as a native Inspect AI
         ``@metric`` callable so any scorer can declare it under
         a custom name.

The aggregation contract:

* Inputs are the ``SampleScore`` payloads of every sample in a
  run. The hardware telemetry envelope written by
  :class:`~evalsbench.eds.telemetry.TelemetryCollector` to
  ``state.metadata['telemetry']`` is surfaced on
  ``SampleScore.sample_metadata`` at metric-aggregation time.
  Missing telemetry or ``None`` fields degrade to ``None`` rather
  than crashing.
* Outputs are **only** flat scalars (every value is ``int``,
  ``float``, or ``None``). Inspect AI's metric machinery invokes
  :func:`float` on every top-level value; nested mappings would
  crash the run. We therefore expose the per-field coverage
  fraction under flat keys (``coverage_median_ttft_s``,
  ``coverage_median_decode_tps``, ``coverage_median_mtp_acceptance``)
  alongside ``sample_count``, ``median_ttft_s``,
  ``median_decode_tps``, and ``median_mtp_acceptance``. Each
  median is the median of the non-``None`` samples for that
  field, or ``None`` when no sample carries a valid value.
* The metric registrar holds the configured default name
  (``eds_telemetry``). Inspect AI's metric machinery accepts a
  list-valued return: each scalar is emitted under a stable key
  so downstream dashboards can address them individually.

Influencing the project contract (see AGENTS.md, Rule 6):

* All bounded execution happens inside the solver; the scorer
  itself never opens a network connection. It is purely a
  read-side aggregator over in-memory snapshots.
* No code paths here raise on missing data; the metric returns
  the same shape regardless of coverage so dashboards can
  detect the absence of telemetry rather than crashing.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

from inspect_ai.scorer import SampleScore, metric
from inspect_ai.scorer._metric import Metric, Value


# ---------------------------------------------------------------------------
# Stability: keys we extract from each per-sample telemetry payload.
# ---------------------------------------------------------------------------

_TELEMETRY_FIELDS: Dict[str, str] = {
    "median_ttft_s": "ttft_s",
    "median_decode_tps": "decode_tps",
    "median_mtp_acceptance": "mtp_acceptance",
}

#: Default name registered for the metric callable.
DEFAULT_METRIC_NAME = "eds_telemetry"


# ---------------------------------------------------------------------------
# Metric implementation
# ---------------------------------------------------------------------------


def _coerce_sample_payload(score: Any) -> Optional[Dict[str, Any]]:
    """Extract the per-sample hardware telemetry payload.

    Inspect AI surfaces the per-sample :class:`TaskState.metadata`
    on :attr:`SampleScore.sample_metadata`, so the
    :class:`~evalsbench.eds.telemetry.TelemetryCollector` snapshot the
    solver attached to ``state.metadata['telemetry']`` is reachable
    via ``score.sample_metadata['telemetry']`` at metric-aggregation
    time. This is the production path (the ``Score.value`` only
    carries the scorecard payload, not the hardware envelope).

    For backward compatibility with the Wave-6 unit-test stubs
    (which pass a duck-typed ``value=`` directly) we also inspect
    ``score.value['telemetry']`` as a fallback. Both paths are
    optional: if neither yields a dict, we return ``None`` and the
    sample is treated as having no telemetry data.

    Args:
        score: A :class:`SampleScore` from Inspect AI or a stub
            used by the unit tests.

    Returns:
        Optional[Dict[str, Any]]: Telemetry sub-dict (or ``None``
        when the sample carries no telemetry data).
    """
    seen: List[Dict[str, Any]] = []
    seen.extend(_telemetry_payloads_in(score))
    # Prefer the first candidate that actually carries a recognised
    # telemetry field, falling back to the first candidate we saw.
    recognised = set(_TELEMETRY_FIELDS.values())
    for candidate in seen:
        if any(key in candidate for key in recognised):
            return candidate
    return seen[0] if seen else None


def _telemetry_payloads_in(score: Any) -> List[Dict[str, Any]]:
    """Return every telemetry sub-dict reachable on ``score``.

    Iterates the two known sources in priority order:

    1. ``score.sample_metadata['telemetry']`` — populated by the
       :func:`eds_agent_solver` wrapper; this is the real
       production path that wires the collector snapshot into the
       Inspect AI run.
    2. ``score.value['telemetry']`` — the legacy stub path used by
       Wave-6 unit tests; never the production path because the
       actual :class:`Score.value` only carries the scorecard
       dict (axes 1–3) on this codebase, not the hardware envelope.

    Args:
        score: A :class:`SampleScore` or test stub.

    Returns:
        List[Dict[str, Any]]: every telemetry dict we found (in
        priority order). May be empty.
    """
    payloads: List[Dict[str, Any]] = []
    sample_metadata = getattr(score, "sample_metadata", None)
    if isinstance(sample_metadata, dict):
        candidate = sample_metadata.get("telemetry")
        if isinstance(candidate, dict):
            payloads.append(candidate)
    raw_value = getattr(score, "value", None)
    if isinstance(raw_value, dict):
        candidate = raw_value.get("telemetry")
        if isinstance(candidate, dict):
            payloads.append(candidate)
    return payloads


def _safe_median(samples: List[float]) -> Optional[float]:
    """Return the median of ``samples`` or ``None`` if empty."""
    if not samples:
        return None
    try:
        return float(statistics.median(samples))
    except statistics.StatisticsError:
        return None


@metric(name=DEFAULT_METRIC_NAME)
def eds_telemetry() -> Metric:
    """Inspect ``@metric``: aggregate per-sample telemetry medians.

    The metric returns a dict whose **only** values are scalars
    (``int`` / ``float`` / ``None``). Inspect AI's metric
    :func:`~inspect_ai._eval.task.results.scorer_for_metrics`
    pipeline iterates ``metric_value.items()`` and calls
    :func:`float` on every non-None value; nested mappings would
    raise ``TypeError`` and abort the run. We therefore surface
    coverage per median field as a sibling scalar key
    (``coverage_<median_key>``) instead of nesting under a
    sub-dict.

    Returns:
        Metric: Callable taking a List[SampleScore] and returning
        a Value-shaped flat dict.
    """

    def _metric(scores: List[SampleScore]) -> Value:
        """Inner aggregation closure.

        Walks the supplied ``SampleScore`` list, classifies each
        entry's per-sample telemetry payload via
        :func:`_coerce_sample_payload`, and emits the run-level
        flat aggregate dict described in the module docstring.
        ``None`` and non-numeric values are skipped without
        raising so a partial telemetry record never crashes the
        metric.

        Args:
            scores: All per-sample scores for the run.

        Returns:
            Value: Aggregate dict with the keys below; every value
            is a scalar (``int`` / ``float`` / ``None``) and
            inspect-ai-safe.

            Keys:

            * ``sample_count``: ``int`` number of samples whose
              payload exposed a telemetry envelope.
            * ``median_ttft_s``: median of per-sample ``ttft_s``.
            * ``median_decode_tps``: median of ``decode_tps``.
            * ``median_mtp_acceptance``: median of
              ``mtp_acceptance``.
            * ``coverage_median_ttft_s``: fraction (0–1) of
              samples that contributed a valid ``ttft_s``.
            * ``coverage_median_decode_tps``: same for
              ``decode_tps``.
            * ``coverage_median_mtp_acceptance``: same for
              ``mtp_acceptance``.
        """
        per_field_values: Dict[str, List[float]] = {
            telemetry_key: [] for telemetry_key in _TELEMETRY_FIELDS.values()
        }
        sample_count = 0
        for score in scores or []:
            telemetry = _coerce_sample_payload(score)
            if telemetry is None:
                continue
            sample_count += 1
            for telemetry_key in per_field_values:
                value = telemetry.get(telemetry_key)
                if isinstance(value, bool) or value is None:
                    continue
                try:
                    per_field_values[telemetry_key].append(float(value))
                except (TypeError, ValueError):
                    # Silently skip non-numeric values; degrading
                    # telemetry is preferable to crashing the metric.
                    continue
        result: Dict[str, Any] = {"sample_count": int(sample_count)}
        for output_key, telemetry_key in _TELEMETRY_FIELDS.items():
            samples_for_key = per_field_values[telemetry_key]
            result[output_key] = _safe_median(samples_for_key)
            # Per-field coverage: fraction of samples carrying a
            # valid value, rounded to 4 decimals. Emitted as a
            # flat top-level scalar (``coverage_<output_key>``)
            # because Inspect AI's metric pipeline calls
            # :func:`float` on every returned value.
            if sample_count > 0:
                coverage = round(
                    float(len(samples_for_key)) / float(sample_count), 4
                )
            else:
                coverage = 0.0
            result[f"coverage_{output_key}"] = coverage
        return result

    return _metric
