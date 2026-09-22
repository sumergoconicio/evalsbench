"""
Hardware telemetry collection for the EDS (Evaluation Development System).

File:    evalsbench/eds/telemetry.py
Module:  evalsbench.eds
Purpose: Capture per-episode hardware telemetry (TTFT, decode TPS, MTP
         draft acceptance, wall time, rounds) and attach it to the
         Inspect AI ``state.metadata`` payload so downstream scorers
         can aggregate it across samples.

This module is **offline-first**: every telemetry field is optional,
and any failure in measurement degrades the corresponding field to
``None`` rather than raising. Network probes (vLLM ``/metrics`` HTTP
GET) are timeout-bounded and exception-safe so a downstream outage
cannot fail the run.

Architecture (locked Option A):

* The :class:`TelemetryCollector` exposes a per-episode context.
  The accompanying :func:`measure_generate` async context manager
  wraps each ``model.generate`` call so per-turn wall times and
  per-turn token counts are accumulated.
* TTFT cannot be derived from Inspect AI's API surface in a
  non-invasive way (it would require patching the OpenAI client's
  streaming internals). The collector therefore records
  ``ttft_s = None`` unless the production deployment supplies a
  custom hook via :meth:`TelemetryCollector.set_ttft_hook`.
  Decode tokens-per-second IS derived from
  ``ModelUsage.output_tokens`` divided by per-turn wall time; this
  is exactly what the Inspect AI ``mockllm`` provider populates
  and what every vLLM/OpenAI-compatible endpoint reports in the
  response ``usage`` object.
* MTP draft acceptance rate is computed as a DELTA of the vLLM
  ``/metrics`` counters ``spec_decode_num_{accepted,draft}_tokens``
  before and after each episode. The counter regex is ported
  verbatim from ``lukes-agency/agency_bench.py``. If the endpoint is
  unreachable, not vLLM, or times out, the rate is ``None``.

The collector MUST be created **inside** the per-sample
``solve(state, generate)`` closure (see Wave 1 invariant) so its
state never bleeds across sibling samples under
``max_connections > 1``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union


# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger("evalsbench.eds.telemetry")


# ---------------------------------------------------------------------------
# Tunables (overridable on TelemetryCollector construction)
# ---------------------------------------------------------------------------

#: Default HTTP timeout for the vLLM ``/metrics`` scrape, in seconds.
DEFAULT_METRICS_TIMEOUT_S: float = 5.0
#: Default wall-time threshold below which a per-turn decode-time is
#: too small to produce a stable TPS estimate (set to 0.0 -> None).
#: 1 microsecond is small enough to accommodate test fixtures while
#: still guarding against divide-by-near-zero in production runs.
DEFAULT_MIN_DECODE_TIME_S: float = 1e-6


# ---------------------------------------------------------------------------
# Counter parsing (ported from lukes-agency/agency_bench.py)
# ---------------------------------------------------------------------------

# Regex matching one Prometheus text line for any of the vLLM
# spec-decode counters we want to consume. We deliberately accept
# the same flavour of metric exposition as the existing
# ``fetch_metrics_counters`` helper so the snapshot is a
# drop-in replacement.
_SPEC_DECODE_COUNTER_RE = re.compile(
    r"^vllm:spec_decode_num_(accepted_tokens|draft_tokens|drafts)_total"
    r"\{[^}]*\}\s+([0-9.]+)",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class _TurnSampling:
    """Per-turn wall time + token bookkeeping."""

    wall_s: float = 0.0
    output_tokens: int = 0


@dataclass
class _MetricsSnapshot:
    """Snapshot of vLLM ``/metrics`` spec-decode counters."""

    accepted_tokens: Optional[float] = None
    draft_tokens: Optional[float] = None
    drafts: Optional[float] = None
    raw: Dict[str, float] = field(default_factory=dict)

    def delta(self, other: "_MetricsSnapshot") -> Dict[str, float]:
        """Return the per-counter delta from ``other`` (self - other).

        Missing counters in either snapshot are skipped so a
        non-vLLM server (or a partial scrape) degrades cleanly.
        """
        delta: Dict[str, float] = {}
        for key in ("accepted_tokens", "draft_tokens", "drafts"):
            mine = self.raw.get(key)
            theirs = other.raw.get(key)
            if mine is None or theirs is None:
                continue
            delta[key] = max(mine - theirs, 0.0)
        return delta


# ---------------------------------------------------------------------------
# Public collector
# ---------------------------------------------------------------------------


class TelemetryCollector:
    """Per-episode telemetry collector.

    Created **inside** the per-sample ``solve()`` closure so its
    state never leaks across siblings. Owns:

    * ``/metrics`` deltas (before/after the episode),
    * aggregated per-turn wall time + token counts,
    * round count,
    * an optional per-turn TTFT hook (production deployments may
      supply one; the default is ``None``).

    The collector never raises; failures degrade to ``None`` so
    callers can rely on the optional/None contract.

    Typical usage inside the solver:

    .. code-block:: python

        collector = TelemetryCollector(endpoint=endpoint_str)
        async with collector:
            for _ in range(limits.max_turns):
                async with collector.measure_generate() as sample:
                    output = await get_model().generate(...)
                    sample.set_usage(output)
    """

    def __init__(
        self,
        *,
        endpoint: Optional[str] = None,
        metrics_timeout_s: float = DEFAULT_METRICS_TIMEOUT_S,
        min_decode_time_s: float = DEFAULT_MIN_DECODE_TIME_S,
        ttft_hook: Optional[Callable[[float], Optional[float]]] = None,
    ) -> None:
        self._endpoint = endpoint
        self._metrics_timeout_s = float(metrics_timeout_s)
        self._min_decode_time_s = float(min_decode_time_s)
        self._ttft_hook = ttft_hook
        self._turns: List[_TurnSampling] = []
        self._first_ttft_s: Optional[float] = None
        self._rounds: int = 0
        self._started_monotonic: Optional[float] = None
        self._closed: bool = False
        self._before_snapshot = _MetricsSnapshot()
        self._after_snapshot = _MetricsSnapshot()

    # -- Lifecycle --------------------------------------------------------

    async def __aenter__(self) -> "TelemetryCollector":
        """Open the collector: record the start clock and snapshot /metrics.

        Returns:
            TelemetryCollector: ``self`` for chaining.
        """
        self._started_monotonic = time.monotonic()
        self._before_snapshot = await self._fetch_snapshot()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Close the collector: snapshot /metrics post-episode.

        Tolerates exceptions: the snapshot is best-effort and never
        propagates a metrics failure into the caller's exception
        chain.

        Args:
            exc_type: Exception type (ignored).
            exc: Exception value (ignored).
            tb: Traceback (ignored).
        """
        if self._closed:
            return
        self._after_snapshot = await self._fetch_snapshot()
        self._closed = True
        return None

    # -- Sampling hooks --------------------------------------------------

    def set_ttft_hook(
        self,
        hook: Optional[Callable[[float], Optional[float]]],
    ) -> None:
        """Install (or clear) a per-turn TTFT hook.

        The hook receives the per-turn wall time as a float and
        must return ``None`` or a float (seconds). Production
        deployments can supply a hook that intercepts the model's
        streaming first chunk. The default ``None`` leaves
        ``ttft_s`` unset at attach time.

        Args:
            hook: Callable accepting the turn wall time and
                returning a TTFT in seconds, or ``None`` to clear.
        """
        self._ttft_hook = hook

    @contextlib.asynccontextmanager
    async def measure_generate(self):
        """Time a single ``model.generate`` invocation.

        Yields a :class:`GenerateProbe` that lets the caller
        stamp the resulting output token count via
        :meth:`GenerateProbe.set_usage` (or pass the raw
        :class:`inspect_ai.model.ModelOutput` directly). Without
        such a stamp the turn contribution to ``decode_tps`` is
        zero on that turn.

        Yields:
            GenerateProbe: Per-turn sampler bound to ``self``.
        """
        started = time.monotonic()
        probe = GenerateProbe(self)
        try:
            yield probe
        finally:
            wall = time.monotonic() - started
            self._rounds += 1
            self._turns.append(
                _TurnSampling(
                    wall_s=float(wall),
                    output_tokens=int(probe._output_tokens),
                )
            )
            if self._ttft_hook is not None and self._first_ttft_s is None:
                try:
                    hook_ttft = self._ttft_hook(wall)
                    if hook_ttft is not None:
                        self._first_ttft_s = float(hook_ttft)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "EDS telemetry: ttft_hook raised: %s", exc
                    )

    # -- Attachment -------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-safe telemetry payload (defensive copy).

        All entries are optional and may be ``None``; downstream
        consumers must skip ``None`` values rather than treating
        zero as a measurement.

        Returns:
            dict: Telemetry payload decorated with all measured
            metrics. Always carries the documented keys, even when
            each value is ``None``.
        """
        wall_s = (
            time.monotonic() - self._started_monotonic
            if self._started_monotonic is not None
            else None
        )
        decode_tps = self._compute_decode_tps(wall_s)
        mtp_delta = self._after_snapshot.delta(self._before_snapshot)
        accepted = mtp_delta.get("accepted_tokens")
        drafts = mtp_delta.get("draft_tokens")
        acceptance_rate: Optional[float] = None
        if accepted is not None and drafts not in (None, 0.0):
            acceptance_rate = accepted / drafts
        return {
            "ttft_s": self._first_ttft_s,
            "decode_tps": decode_tps,
            "wall_s": wall_s,
            "rounds": self._rounds,
            "accepted_tokens": accepted,
            "draft_tokens": drafts,
            "mtp_acceptance": acceptance_rate,
        }

    def attach(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Write the telemetry snapshot onto a metadata dict (in place).

        Always returns the same dict for chaining. Mutates
        ``metadata["telemetry"]`` so the Inspect AI eval log carries
        the per-episode telemetry payload.

        Args:
            metadata: The ``state.metadata`` dict. Mutated in place.

        Returns:
            dict: The same dict, now carrying the telemetry key.
        """
        if not isinstance(metadata, dict):
            raise TypeError(
                f"TelemetryCollector.attach expects a dict, "
                f"got {type(metadata).__name__}."
            )
        metadata["telemetry"] = self.snapshot()
        return metadata

    # -- Internal helpers ------------------------------------------------

    def _compute_decode_tps(
        self,
        wall_s: Optional[float],
    ) -> Optional[float]:
        """Compute aggregate decode tokens/sec from per-turn data.

        Returns ``None`` when total decode time falls below the
        configured floor (avoids divide-by-near-zero noise) or when
        no tokens were produced.

        Args:
            wall_s: Total episode wall time (caller's monotonic
                arithmetic). May be ``None`` if the collector was
                never entered.

        Returns:
            Optional[float]: Aggregate decode TPS, or ``None``.
        """
        if not self._turns:
            return None
        total_tokens = sum(turn.output_tokens for turn in self._turns)
        if total_tokens <= 0:
            return None
        # Prefer the per-turn wall sum so tool execution time
        # between turns does not inflate the decode denominator.
        # Falls back to the episode wall when per-turn accounting
        # did not record any duration.
        per_turn_wall = sum(turn.wall_s for turn in self._turns)
        denom = per_turn_wall if per_turn_wall > 0 else wall_s
        if denom is None or denom < self._min_decode_time_s:
            return None
        return float(total_tokens) / float(denom)

    async def _fetch_snapshot(self) -> _MetricsSnapshot:
        """Fetch /metrics from the configured endpoint (best-effort).

        Returns an empty :class:`_MetricsSnapshot` on any failure
        (network error, non-vLLM server, timeout, non-200 status).
        Never raises.

        Returns:
            _MetricsSnapshot: Parsed snapshot, or empty on failure.
        """
        if not self._endpoint:
            return _MetricsSnapshot()
        url = _strip_v1_suffix(self._endpoint) + "/metrics"
        try:
            payload = await asyncio.to_thread(self._scrape, url)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "EDS telemetry: /metrics scrape failed for %s -> %s",
                url,
                exc,
            )
            return _MetricsSnapshot()
        if payload is None:
            return _MetricsSnapshot()
        return _parse_metrics(payload)

    @staticmethod
    def _scrape(url: str) -> Optional[str]:
        """Synchronous HTTP GET with a hard timeout.

        Args:
            url: Absolute HTTP URL to scrape.

        Returns:
            Optional[str]: Body text on 200 OK, else ``None``.

        Raises:
            urllib.error.URLError: Network failure (logged outer).
        """
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(
            request, timeout=DEFAULT_METRICS_TIMEOUT_S
        ) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            data = resp.read()
            if isinstance(data, bytes):
                return data.decode("utf-8", "replace")
            return str(data)


# ---------------------------------------------------------------------------
# Per-turn probe yielded by TelemetryCollector.measure_generate
# ---------------------------------------------------------------------------


class GenerateProbe:
    """Per-turn sampler returned by :meth:`TelemetryCollector.measure_generate`.

    Lets the caller stamp the resulting
    :class:`inspect_ai.model.ModelOutput` (or a bare token int)
    onto the in-flight turn. Tokens stamped here are folded into
    the parent collector's aggregate ``decode_tps`` once the
    context manager exits.

    Args:
        collector: The owning :class:`TelemetryCollector`.
    """

    def __init__(self, collector: TelemetryCollector) -> None:
        self._collector = collector
        self._output_tokens: int = 0

    def set_usage(
        self,
        usage_or_tokens: Union[int, Any],
    ) -> int:
        """Stamp the per-turn output token count.

        Accepts either an ``int`` token count or an Inspect AI
        :class:`ModelOutput` (or anything with a ``usage`` field
        carrying ``output_tokens``). Negative or missing values are
        coerced to zero so a buggy mock provider cannot stamp a
        negative delta onto the cumulative ``decode_tps``.

        Args:
            usage_or_tokens: Either an int or an object exposing
                ``.usage.output_tokens``.

        Returns:
            int: The token count actually recorded.
        """
        tokens = self._extract_tokens(usage_or_tokens)
        self._output_tokens = tokens
        return tokens

    @staticmethod
    def _extract_tokens(usage_or_tokens: Union[int, Any]) -> int:
        """Return the integer output_tokens from either an int or a ModelOutput.

        Args:
            usage_or_tokens: Either a raw int or an Inspect AI
                :class:`ModelOutput` exposing ``.usage.output_tokens``.

        Returns:
            int: The coerced, non-negative token count. Non-int
            / non-ModelOutput inputs degrade to zero.
        """
        if isinstance(usage_or_tokens, int):
            return max(int(usage_or_tokens), 0)
        usage = getattr(usage_or_tokens, "usage", None)
        if usage is None:
            return 0
        try:
            return max(int(getattr(usage, "output_tokens", 0) or 0), 0)
        except (TypeError, ValueError):
            return 0


# ---------------------------------------------------------------------------
# Free helpers
# ---------------------------------------------------------------------------


def _strip_v1_suffix(endpoint: str) -> str:
    """Strip a trailing ``/v1`` (with or without trailing slash).

    Args:
        endpoint: Base HTTP endpoint.

    Returns:
        str: Endpoint with ``/v1`` removed.
    """
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        return base[: -len("/v1")]
    return base


def _parse_metrics(text: str) -> _MetricsSnapshot:
    """Extract the three vLLM spec-decode counters from /metrics text.

    Mirrors ``fetch_metrics_counters`` in ``agency_bench.py``: every
    counter line is treated as additive across label combinations
    (vLLM exposes per-model/per-process breakdowns). Negative
    deltas are floored at ``0`` by the calling snapshot delta.

    Args:
        text: Raw Prometheus exposition body.

    Returns:
        _MetricsSnapshot: Per-counter sums (or None for missing).
    """
    snapshot = _MetricsSnapshot()
    for match in _SPEC_DECODE_COUNTER_RE.finditer(text):
        kind = match.group(1)
        value = float(match.group(2))
        snapshot.raw[kind] = snapshot.raw.get(kind, 0.0) + value
    # Promote the raw keys onto the convenience attributes so the
    # delta machinery can read them consistently.
    snapshot.accepted_tokens = snapshot.raw.get("accepted_tokens")
    snapshot.draft_tokens = snapshot.raw.get("draft_tokens")
    snapshot.drafts = snapshot.raw.get("drafts")
    return snapshot


def derive_endpoint(inspect_endpoint: Optional[str]) -> Optional[str]:
    """Resolve the metrics endpoint from an Inspect base URL.

    Inspect AI accept endpoints in the form ``http://host:port/v1``;
    vLLM exposes metrics on ``http://host:port/metrics``. This
    helper strips the ``/v1`` suffix (if present) so the collector
    can scrape the right host:port.

    Args:
        inspect_endpoint: The chat completions endpoint passed to
            the model provider. ``None`` disables scraping.

    Returns:
        Optional[str]: Host:port string with ``/v1`` removed, or
        ``None`` when the caller passes ``None``.
    """
    if not inspect_endpoint:
        return None
    return _strip_v1_suffix(str(inspect_endpoint))
