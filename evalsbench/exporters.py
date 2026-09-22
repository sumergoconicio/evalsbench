"""
Result exporting: Markdown reports, JSON telemetry, dynamic models.yaml, and ChAI sync.

Also contains the EDS (Evaluation Development System) aware extensions that
project a finished EDS/MiniCorp :class:`~inspect_ai.log.EvalLog` (or an
equivalent in-memory dict / on-disk ``.eval`` path) into a tri-axis scorecard
plus a telemetry envelope. The EDS exports degrade gracefully on
non-EDS logs: missing telemetry or score fields are surfaced as ``None``
or omitted, they never crash the existing export flow.
"""

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union
import yaml

from .config import CONFIGS_DIR, MODELS_YAML_PATH, CHAI_MODELS_DIR


# ---------------------------------------------------------------------------
# EDS specific constants (additive — names mirror the canonical
# keys emitted by :mod:`evalsbench.eds.scorers.tri_axis` and
# :mod:`evalsbench.eds.scorers.telemetry_scorer`).
# ---------------------------------------------------------------------------

#: Scorer name emitted by :mod:`evalsbench.eds.scorers.tri_axis`.
EDS_TRI_AXIS_SCORER: str = "tri_axis"

#: Metric name registered by :mod:`evalsbench.eds.scorers.telemetry_scorer`.
EDS_TELEMETRY_METRIC: str = "eds_telemetry"

#: Sentinel scorer column name created by
#: :mod:`evalsbench.eds.solver` solely to carry the ``eds_telemetry``
#: ``@metric`` payload through Inspect AI's run-loop scorer chain.
#: Its per-sample :class:`Score.value` is a dummy ``0.0``; the real
#: telemetry travels via :attr:`SampleScore.sample_metadata`. The
#: ``__`` prefix and trailing ``_`` namespace it so it cannot collide
#: with user-named scorers in :data:`EDS_TRI_AXIS_SCORER`. Functional
#: aggregates ignore it (they only read ``tri_axis`` scores); the
#: telemetry harvester MUST still scrape its metric entries so the
#: canonical ``median_*`` medians reach the export pipeline.
EDS_TELEMETRY_ONLY_SCORER: str = "__eds_telemetry_only__"

#: Canonical ``@metric`` field names produced by
#: :mod:`evalsbench.eds.scorers.telemetry_scorer`. Inspect AI's metric
#: flattener stores each scalar returned by the ``@metric`` callable
#: as a separately-named metric entry under
#: ``results.scores[*].metrics[<field_name>]``. The exporter pulls
#: every entry whose key is in this tuple so the REAL production
#: archive shape (not the legacy nested ``eds_telemetry`` block) is
#: ingested. Coverage siblings (``coverage_median_*``,
#: ``coverage_*``) are intentionally excluded so we do not surface
#: half-coverage counters as canonical aggregates.
EDS_TELEMETRY_MEDIAN_KEYS: Sequence[str] = (
    "median_ttft_s",
    "median_decode_tps",
    "median_mtp_acceptance",
)

#: Canonical aggregate keys we surface for EDS runs. Anything missing on
#: the source EvalLog collapses to ``None`` in the exported payload.
EDS_AGGREGATE_KEYS: Sequence[str] = (
    "samples",
    "functional_pass_rate",
    "mean_composite",
    "hygiene_index",
    "safety_gate_pass_rate",
    "safety_violations_total",
    "critical_violations_total",
    "axis1_pass_rate",
    "axis2_pass_rate",
    "axis3_safe_rate",
    "median_ttft_s",
    "median_decode_tps",
    "median_mtp_acceptance",
)

#: Benchmark keys treated as EDS runs in the dashboard pipeline.
EDS_BENCHMARK_KEYS: frozenset = frozenset({"minicorp", "eds_minicorp", "eds"})

#: Dashboard marker added to benchmark entries so the front-end knows to
#: render tri-axis columns. Pure data hint — never read by the scorer.
EDS_DASHBOARD_TAG: str = "eds_tri_axis"


# ---------------------------------------------------------------------------
# Lightweight EvalLog adapter (additive — does not assume inspect_ai is
# installed in every test environment).
# ---------------------------------------------------------------------------


def _coerce_eval_log(
    source: Union[str, Path, Mapping[str, Any], Any, None],
) -> Optional[Mapping[str, Any]]:
    """Resolve ``source`` to a dict-shaped EvalLog.

    Accepts (in order):

    * ``None`` → returns ``None``.
    * ``str | Path`` → if it points at a ``.eval`` Inspect log, read it
      via :func:`zipfile.ZipFile` and merge the per-sample scores into
      a normalized dict. Plain JSON files are loaded directly.
    * A mapping → returned as-is. The exporter treats it as the canonical
      EvalLog shape. Helpful for tests.
    * An :class:`inspect_ai.log.EvalLog` object → its :meth:`model_dump`
      output is used.

    Args:
        source: Path, dict, EvalLog, or ``None``.

    Returns:
        Optional[Mapping[str, Any]]: Normalized EvalLog dict, or
        ``None`` if the source cannot be resolved.
    """
    if source is None:
        return None
    if isinstance(source, (str, Path)):
        return _load_eval_log_from_path(Path(source))
    if isinstance(source, Mapping):
        return source
    # Pydantic v2 models expose ``model_dump``.
    model_dump = getattr(source, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json")
        except TypeError:
            dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    return None


def _load_eval_log_from_path(path: Path) -> Optional[Mapping[str, Any]]:
    """Load an Inspect AI ``.eval`` archive (or plain JSON) into a dict.

    The :mod:`inspect_ai` log writer stores results inside a Zstd- or
    DEFLATE-compressed Zip archive with one file per sample plus a
    ``header.json`` / ``summaries.json``. CPython's stdlib
    :mod:`zipfile` does **not** support Zstd (compression method 93),
    which is the default in modern ``inspect_ai`` releases; a real
    archive would raise :class:`NotImplementedError` on
    ``ZipFile.open()``. We therefore try the canonical
    :func:`inspect_ai.log.read_eval_log` reader first (it handles
    every compression scheme transparently), then fall back to the
    stdlib reader for legacy DEFLATE archives and plain ``.json``
    files. Every step is exception-safe so a malformed archive or
    absent :mod:`inspect_ai` install degrades to ``None`` rather
    than crashing the export pipeline.

    Args:
        path: File location on disk.

    Returns:
        Optional[Mapping[str, Any]]: Normalized EvalLog dict, or
        ``None`` if the file cannot be read.
    """
    if not path.exists():
        return None

    # 1. Inspect-native reader — handles Zstd (compress_type=93),
    # Zstandard-via-zip, DEFLATE, and any future Inspect scheme.
    try:
        from inspect_ai.log import read_eval_log  # type: ignore

        try:
            eval_log_obj = read_eval_log(str(path))
        except Exception:
            eval_log_obj = None
        if eval_log_obj is not None:
            # ``read_eval_log`` returns a Pydantic :class:`EvalLog`;
            # delegate to :func:`_coerce_eval_log` which knows how to
            # dispatch through ``model_dump`` (Pydantic v2 contract).
            normalized = _coerce_eval_log(eval_log_obj)
            if normalized is not None:
                return normalized
    except Exception:
        # :mod:`inspect_ai` not installed in this Python environment.
        pass

    # 2. Stdlib zipfile reader (legacy DEFLATE archives + plain JSON).
    try:
        if path.suffix.lower() == ".eval":
            with zipfile.ZipFile(path) as zf:
                with zf.open("header.json") as fp:
                    header = json.loads(fp.read().decode("utf-8"))
                samples: List[Dict[str, Any]] = []
                summaries: Dict[str, Any] = {}
                for name in zf.namelist():
                    if name.startswith("samples/") and name.endswith(".json"):
                        with zf.open(name) as fp:
                            samples.append(json.loads(fp.read().decode("utf-8")))
                    elif name == "summaries.json":
                        with zf.open(name) as fp:
                            summaries = json.loads(fp.read().decode("utf-8"))
                merged = dict(header)
                merged["samples"] = samples
                merged.setdefault("summaries", summaries)
                return merged
    except Exception:
        pass

    # 3. Plain JSON fallback.
    try:
        with open(path, "r", encoding="utf-8") as fp:
            loaded = json.load(fp)
            if isinstance(loaded, Mapping):
                return loaded
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# EDS metric extraction
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> Optional[float]:
    """Return ``value`` as float, or ``None`` if not coercible."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _iter_sample_scores(
    eval_log: Mapping[str, Any],
    scorer_name: str = EDS_TRI_AXIS_SCORER,
) -> List[Mapping[str, Any]]:
    """Return per-sample ``Score`` dicts for the named scorer.

    Inspect stores per-sample results under ``sample.scores`` keyed by
    scorer name. We tolerate either the canonical nested shape
    (``score.value`` may be a Mapping) or an already-flattened dict.

    Args:
        eval_log: Normalized EvalLog dict.
        scorer_name: Which scorer to read.

    Returns:
        List[Mapping[str, Any]]: Detected per-sample score dicts.
    """
    samples = eval_log.get("samples") or []
    extracted: List[Mapping[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        score = (sample.get("scores") or {}).get(scorer_name)
        if isinstance(score, Mapping):
            extracted.append(score)
            continue
        # Some EvalLog variants place the scorer output under
        # ``sample.results.scores`` or ``sample.score``.
        for container_key in ("results", "score"):
            container = sample.get(container_key)
            if isinstance(container, Mapping):
                sub = container.get("scores") if isinstance(container.get("scores"), Mapping) else None
                if isinstance(sub, Mapping) and isinstance(sub.get(scorer_name), Mapping):
                    extracted.append(sub[scorer_name])
                    break
                if isinstance(container.get(scorer_name), Mapping):
                    extracted.append(container[scorer_name])
                    break
    return extracted


def _iter_metric_payloads(
    eval_log: Mapping[str, Any],
    metric_name: str = EDS_TELEMETRY_METRIC,
) -> List[Mapping[str, Any]]:
    """Return every metric payload exposing EDS telemetry medians.

    Inspect AI surfaces ``@metric`` outputs in three observed shapes —
    we must accept all of them so the canonical ``median_ttft_s`` /
    ``median_decode_tps`` / ``median_mtp_acceptance`` aggregates
    flow into the exported payload regardless of Inspect AI version:

    1. **Legacy nested** — ``results.scores[*].metrics[metric_name]``
       is itself a mapping whose keys are the canonical median names.
       This is the shape the exporter tests use and the path that
       older Inspect versions emitted under the metric callable name.
    2. **Sentinel column** — a scorer entry named
       ``__eds_telemetry_only__`` is added by :mod:`evalsbench.eds.solver`
       precisely to carry the telemetry metric. Its per-sample
       :class:`Score.value` is a dummy; the real telemetry lives on
       :attr:`SampleScore.sample_metadata`. The metric flattener then
       emits ``median_*`` / ``coverage_*`` / ``sample_count`` entries
       under ``__eds_telemetry_only__.metrics``. The exporter must
       scrape those entries while still IGNORING this scorer for
       functional aggregates (only ``tri_axis`` scores feed those —
       preserved by :func:`_iter_sample_scores`'s default ``scorer_name``).
    3. **Individually-named metrics** — :class:`tri_axis` (and other
       scorers) also carry an ``eds_telemetry`` ``@metric`` registration
       whose outputs Inspect flattens into ``results.scores[*].metrics``
       keyed by the *individual* metric field name, e.g.
       ``results.scores[*].metrics["median_ttft_s"] = {"value": 0.18, "name": "median_ttft_s", "group": "eds_telemetry", ...}``
       (a dict with a canonical ``value`` key) OR — sometimes, on
       older Inspect versions — a direct scalar
       (``results.scores[*].metrics["median_ttft_s"] = 0.18``).
       Each metric entry also carries a ``group`` attribute that
       equals ``"eds_telemetry"``; we treat that as a positive
       signal that the field belongs to our schema but do NOT
       hard-filter on it because the canonical field name is
       decisive.

    The function returns a list of payload mappings so the caller
    can apply its own ``first-wins`` semantics. Across all scorers,
    the individually-named fields are merged into a single
    ``combined_flat`` aggregate with **last-wins** precedence — the
    sentinel column (``__eds_telemetry_only__``) is conventionally the
    last entry in ``results.scores`` so its values overwrite the
    zero-valued metrics attached to ``tri_axis``. The combined flat
    aggregate is appended **last** to the payload list so legacy
    payloads still win on overlap (preserves backward compat with
    the original nested test fixtures) while ensuring the
    individually-named harvest always reaches the caller.

    Args:
        eval_log: Normalized EvalLog dict.
        metric_name: Legacy nested key to harvest (default
            ``eds_telemetry``; backward-compat with the previous test
            fixtures).

    Returns:
        List[Mapping[str, Any]]: Located metric dicts (possibly empty).
    """
    payloads: List[Mapping[str, Any]] = []
    combined_flat: Dict[str, Any] = {}

    results = eval_log.get("results")
    if isinstance(results, Mapping):
        scores = results.get("scores") or []
        if isinstance(scores, list):
            for scorer in scores:
                if not isinstance(scorer, Mapping):
                    continue
                metrics = scorer.get("metrics")
                if not isinstance(metrics, Mapping):
                    continue
                # (a) Legacy nested shape — preserve for backward compat.
                legacy = metrics.get(metric_name)
                if isinstance(legacy, Mapping):
                    payloads.append(legacy)
                # (b) Individually-named shape — REAL Inspect AI format.
                # Each metrics key like ``median_ttft_s`` maps either to a
                # scalar or to a typed mapping with a ``value`` field.
                for median_key in EDS_TELEMETRY_MEDIAN_KEYS:
                    if median_key not in metrics:
                        continue
                    scalar = _coerce_metric_scalar_via_value(metrics[median_key])
                    if scalar is not None:
                        combined_flat[median_key] = scalar

    summaries = eval_log.get("summaries")
    if isinstance(summaries, Mapping):
        for key, value in summaries.items():
            if not isinstance(value, Mapping):
                continue
            inner_metrics = value.get("metrics")
            if not isinstance(inner_metrics, Mapping):
                continue
            # Legacy shape at summary level.
            legacy = inner_metrics.get(metric_name)
            if isinstance(legacy, Mapping):
                payloads.append(legacy)
            # Individually-named entries at summary level feed the same
            # combined_flat aggregate so a final value wins consistently.
            for median_key in EDS_TELEMETRY_MEDIAN_KEYS:
                if median_key not in inner_metrics:
                    continue
                scalar = _coerce_metric_scalar_via_value(
                    inner_metrics[median_key]
                )
                if scalar is not None:
                    combined_flat[median_key] = scalar

    # Append the merged individually-named aggregate LAST so legacy
    # payloads (which may carry domain-specific extras) win on field
    # overlap, but the canonical median_* fields always have a
    # last-wins guarantee from ``combined_flat``.
    if combined_flat:
        payloads.append(combined_flat)

    return payloads


def _coerce_metric_scalar_via_value(entry: Any) -> Optional[float]:
    """Coerce an Inspect AI ``@metric`` entry to a numeric scalar.

    The metric flattener in modern Inspect AI emits each scalar
    returned by an ``@metric`` callable as its own keyspaced entry.
    The entry value can take three observed shapes — we accept all
    of them and silently degrade to ``None`` if no numeric
    representation is reachable:

    * ``bool`` — return ``None`` (booleans are not telemetry).
    * ``int | float`` — direct return cast to ``float``.
    * ``Mapping`` — prefer the canonical ``"value"`` key (the
      Inspect AI wrapping convention) ; fall back to scanning the
      mapping for any numeric field ignoring the ``name``, ``group``,
      ``params``, and ``metadata`` keys (control-plane fields that
      have no numeric meaning here).
    * ``str`` — :func:`_safe_float` coerces a numeric literal;
      arbitrary strings return ``None``.

    Args:
        entry: Either a scalar or a dict-shaped metric entry.

    Returns:
        Optional[float]: Numeric scalar, or ``None`` if not coercible.
    """
    if isinstance(entry, bool):
        return None
    if isinstance(entry, (int, float)):
        return float(entry)
    if isinstance(entry, Mapping):
        canonical = entry.get("value")
        scalar = _safe_float(canonical)
        if scalar is not None:
            return scalar
        # Fallback: any numeric field other than control-plane keys.
        control_keys = {"name", "group", "params", "metadata"}
        for sub_key, sub_value in entry.items():
            if sub_key in control_keys:
                continue
            scalar = _safe_float(sub_value)
            if scalar is not None:
                return scalar
        return None
    return _safe_float(entry)


def extract_eds_metrics(
    source: Union[str, Path, Mapping[str, Any], Any, None],
) -> Dict[str, Any]:
    """Extract the run-level EDS aggregates from an EvalLog source.

    The function is fully defensive against missing fields:
    non-EDS logs return an empty ``{}`` so the caller can detect "no
    EDS data" rather than crashing the wider export. Any metric
    that cannot be located is omitted from the returned dict, never
    surfaced as a stale ``None`` that downstream code might mistake
    for a recorded zero.

    Args:
        source: EvalLog path, dict, or Inspect ``EvalLog`` object.

    Returns:
        Dict[str, Any]: Aggregate dict keyed by
        :data:`EDS_AGGREGATE_KEYS`. Missing fields are omitted so the
        export pipeline can distinguish "unknown" from "zero".
    """
    eval_log = _coerce_eval_log(source)
    if not eval_log:
        return {}

    aggregates: Dict[str, Any] = {}

    # 1. Per-sample tri-axis rollup.
    tri_scores = _iter_sample_scores(eval_log)
    if tri_scores:
        functionals: List[float] = []
        composites: List[float] = []
        hygiene_indices: List[float] = []
        safety_violations_total = 0
        critical_violations_total = 0
        axis1_passed = 0
        axis2_passed = 0
        axis3_safe = 0
        safety_gate_active = 0
        for score in tri_scores:
            value = score.get("value")
            if not isinstance(value, Mapping):
                continue
            # Use explicit ``in`` checks so legitimate zero values
            # (``0.0`` floats, ``0`` ints) are NOT treated as missing.
            raw_functional = (
                value["functional"] if "functional" in value
                else value.get("functional_score")
            )
            functional = _safe_float(raw_functional)
            composite = _safe_float(value.get("composite"))
            hygiene = _safe_float(value.get("hygiene_index"))
            if functional is not None:
                functionals.append(functional)
            if composite is not None:
                composites.append(composite)
            if hygiene is not None:
                hygiene_indices.append(hygiene)
            sv = _safe_float(value.get("safety_violations"))
            cv = _safe_float(value.get("critical_violations"))
            if sv is not None:
                safety_violations_total += int(sv)
            if cv is not None:
                critical_violations_total += int(cv)
            if value.get("axis1_passed") is True:
                axis1_passed += 1
            if value.get("axis2_passed") is True:
                axis2_passed += 1
            if value.get("axis3_safe") is True:
                axis3_safe += 1
            if value.get("safety_gate_active") is True:
                safety_gate_active += 1

        samples_count = len(functionals) or len(composites) or len(hygiene_indices) or len(tri_scores)
        aggregates["samples"] = samples_count
        if functionals:
            aggregates["functional_pass_rate"] = round(sum(functionals) / len(functionals), 4)
        if composites:
            aggregates["mean_composite"] = round(sum(composites) / len(composites), 4)
        if hygiene_indices:
            aggregates["hygiene_index"] = round(sum(hygiene_indices) / len(hygiene_indices), 4)
        aggregates["safety_violations_total"] = int(safety_violations_total)
        aggregates["critical_violations_total"] = int(critical_violations_total)
        if samples_count:
            aggregates["axis1_pass_rate"] = round(axis1_passed / samples_count, 4)
            aggregates["axis2_pass_rate"] = round(axis2_passed / samples_count, 4)
            aggregates["axis3_safe_rate"] = round(axis3_safe / samples_count, 4)
            aggregates["safety_gate_pass_rate"] = round(
                (samples_count - safety_gate_active) / samples_count, 4
            )

    # 2. Telemetry medians (from the ``eds_telemetry`` metric block).
    telemetry_payloads = _iter_metric_payloads(eval_log)
    for telemetry in telemetry_payloads:
        for field in ("median_ttft_s", "median_decode_tps", "median_mtp_acceptance"):
            value = _safe_float(telemetry.get(field))
            if value is not None and field not in aggregates:
                aggregates[field] = value

    return aggregates


# ---------------------------------------------------------------------------
# EDS aware markdown + JSON writers
# ---------------------------------------------------------------------------


def _format_eds_section(aggregates: Mapping[str, Any]) -> str:
    """Build the markdown snippet rendered under the EDS log report."""
    if not aggregates:
        return ""

    def _pct(key: str) -> str:
        """Format aggregate as percent or em-dash.

        Args:
            key: Aggregate key to format.

        Returns:
            str: ``"75.0%"`` for numeric values, em-dash otherwise.
        """
        value = aggregates.get(key)
        if value is None:
            return "—"
        try:
            return f"{float(value) * 100:.1f}%"
        except (TypeError, ValueError):
            return "—"

    def _count(key: str) -> str:
        """Format aggregate as integer count.

        Args:
            key: Aggregate key to format.

        Returns:
            str: ``"3"`` for integer values, em-dash otherwise.
        """
        value = aggregates.get(key)
        if value is None:
            return "—"
        try:
            return f"{int(value)}"
        except (TypeError, ValueError):
            return "—"

    def _latency(key: str, unit: str) -> str:
        """Format aggregate as fixed-precision float with unit suffix.

        Args:
            key: Aggregate key to format.
            unit: Display unit string (e.g. ``"s"``.

        Returns:
            str: ``"0.193 s"`` for numeric values, em-dash otherwise.
        """
        value = aggregates.get(key)
        if value is None:
            return "—"
        try:
            return f"{float(value):.3f} {unit}"
        except (TypeError, ValueError):
            return "—"

    def _acc(key: str) -> str:
        """Format aggregate as three-decimal scalar.

        Args:
            key: Aggregate key to format.

        Returns:
            str: ``"0.624"`` for numeric values, em-dash otherwise.
        """
        value = aggregates.get(key)
        if value is None:
            return "—"
        try:
            return f"{float(value):.3f}"
        except (TypeError, ValueError):
            return "—"

    sample_count = _count("samples")
    section = (
        "## 🧬 EDS Tri-Axis Aggregates\n\n"
        "*Samples aggregated*: "
        f"{sample_count}\n\n"
        "| Axis | Metric | Value |\n"
        "| :--- | :--- | :--- |\n"
        "| Functional | Pass Rate | "
        f"{_pct('functional_pass_rate')} |\n"
        "| Hygiene | Composite Index | "
        f"{_acc('hygiene_index')} |\n"
        "| Safety | Violations (Total / Critical) | "
        f"{_count('safety_violations_total')} / "
        f"{_count('critical_violations_total')}\u2003|\n"
        "| Safety Gate | Pass Rate | "
        f"{_pct('safety_gate_pass_rate')} |\n"
        "| Composite | Mean Composite | "
        f"{_acc('mean_composite')} |\n"
        "| Telemetry | Median TTFT | "
        f"{_latency('median_ttft_s', 's')} |\n"
        "| Telemetry | Median Decode TPS | "
        f"{_latency('median_decode_tps', 'tok/s')} |\n"
        "| Telemetry | Median MTP Acceptance | "
        f"{_acc('median_mtp_acceptance')} |\n"
    )
    return section


def write_eds_scorecard(
    log_dir: Path,
    benchmark_name: str,
    aggregates: Mapping[str, Any],
    *,
    model_name: Optional[str] = None,
    endpoint_url: Optional[str] = None,
    raw_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Write an EDS-specific markdown section plus JSON blob.

    The function is additive to ``write_benchmark_report``: the
    primary report is still owned by that function, while this call
    creates ``report.eds.md`` and ``results.eds.json`` alongside. It
    tolerates an empty ``aggregates`` mapping (writes a "no EDS
    data" placeholder), never crashes on non-EDS benchmarks, and
    intentionally returns ``None``-friendly artifact paths for the
    legacy runner to ignore.

    Args:
        log_dir: Per-run artifact directory.
        benchmark_name: Benchmark key identifier.
        aggregates: Dict produced by :func:`extract_eds_metrics`.
        model_name: Optional model name to stamp into the JSON header.
        endpoint_url: Optional endpoint URL to stamp into the JSON.
        raw_path: Optional source log path / digest recorded in JSON.

    Returns:
        Path: Location of the JSON blob written on disk.
    """
    markdown_path = log_dir / "report.eds.md"
    json_path = log_dir / "results.eds.json"

    eds_section = _format_eds_section(aggregates) if aggregates else (
        "_No EDS tri-axis aggregates detected in this run._\n"
    )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = (
        f"# 🧬 EDS Tri-Axis Scorecard: {benchmark_name}\n\n"
        f"* **Benchmark**: `{benchmark_name}`\n"
    )
    if model_name:
        header += f"* **Model**: `{model_name}`\n"
    if endpoint_url:
        header += f"* **Endpoint**: `{endpoint_url}`\n"
    header += f"* **Timestamp**: {timestamp}\n\n"

    markdown_path.write_text(header + eds_section, encoding="utf-8")

    payload = {
        "benchmark": benchmark_name,
        "timestamp": timestamp,
        "model": model_name,
        "endpoint": endpoint_url,
        "raw_log": str(raw_path) if raw_path is not None else None,
        "eds_tag": EDS_DASHBOARD_TAG,
        "aggregates": dict(aggregates),
    }
    with open(json_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)

    return json_path


def update_models_yaml(
    model_name: str,
    endpoint_url: str,
    benchmark_name: str,
    scores: Dict[str, Any],
    duration_s: float,
    telemetry: Optional[Dict[str, Any]] = None,
):
    """
    Dynamically persists model evaluation runs and latest scores into configs/models.yaml.
    """
    MODELS_YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    current_data = {}
    if MODELS_YAML_PATH.exists():
        try:
            with open(MODELS_YAML_PATH, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    current_data = loaded
        except Exception:
            current_data = {}

    models_dict = current_data.setdefault("models", {})
    model_entry = models_dict.setdefault(model_name, {
        "endpoint": endpoint_url,
        "last_updated": datetime.now().isoformat(),
        "benchmarks": {},
        "telemetry": {},
    })

    model_entry["endpoint"] = endpoint_url
    model_entry["last_updated"] = datetime.now().isoformat()
    
    # Store benchmark result
    model_entry.setdefault("benchmarks", {})[benchmark_name] = {
        "scores": scores,
        "duration_seconds": round(duration_s, 2),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if telemetry:
        model_entry["telemetry"].update(telemetry)

    try:
        with open(MODELS_YAML_PATH, "w", encoding="utf-8") as f:
            yaml.dump(current_data, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        print(f"Warning: Failed to update {MODELS_YAML_PATH}: {e}")


def write_benchmark_report(
    log_dir: Path,
    model_name: str,
    endpoint_url: str,
    benchmark_name: str,
    samples_count: int,
    duration_s: float,
    raw_output: str,
    scores: Dict[str, Any],
    eval_log_path: Optional[str] = None,
) -> Path:
    """
    Writes a formatted Markdown report into log_dir / report.md.
    """
    report_file = log_dir / "report.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    score_rows = ""
    for k, v in scores.items():
        val_str = f"{v:.3f}" if isinstance(v, float) else str(v)
        score_rows += f"| `{k}` | **{val_str}** |\n"

    content = f"""# 📊 Benchmark Results: {benchmark_name}

* **Model**: `{model_name}`
* **Endpoint**: `{endpoint_url}`
* **Samples Evaluated**: {samples_count}
* **Execution Time**: {duration_s:.1f} seconds (~{duration_s/60:.1f} min)
* **Log Directory**: `{log_dir}`
* **Timestamp**: {timestamp}

## 🎯 Evaluated Metrics

| Metric Name | Score |
| :--- | :--- |
{score_rows}

## 📝 Raw Inspect Output
```text
{raw_output}
```
"""
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(content)

    # Save JSON summary
    json_file = log_dir / "results.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump({
            "model": model_name,
            "endpoint": endpoint_url,
            "benchmark": benchmark_name,
            "samples": samples_count,
            "duration_s": duration_s,
            "scores": scores,
            "eval_log": eval_log_path,
            "timestamp": timestamp,
        }, f, indent=2)

    try:
        from .hydrator import rebuild_leaderboard_json
        rebuild_leaderboard_json()
    except Exception:
        pass

    return report_file


def sync_to_chai_vault(model_name: str, report_file: Path, benchmark_name: str):
    """
    Syncs the finalized report to ~/chai/references/models/<model-name>/ if the vault exists.
    """
    sanitized_model = model_name.replace("/", "_").replace(":", "_").lower()
    target_vault_dir = CHAI_MODELS_DIR / sanitized_model
    if target_vault_dir.parent.exists():
        target_vault_dir.mkdir(parents=True, exist_ok=True)
        dest = target_vault_dir / f"{benchmark_name.lower()}_results.md"
        shutil.copy2(report_file, dest)
