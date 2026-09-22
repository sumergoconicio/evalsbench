"""
Unit tests for the EDS-aware exporter extension in
:mod:`evalsbench.exporters` plus the dashboard surface in
:mod:`evalsbench.hydrator`.

These tests are fully offline: no model, no network, no live Inspect
runs. They build synthetic EvalLog-like dicts (the same shape the
Inspect AI ``@scorer`` / ``@metric`` machinery emits) so the exporters
are exercised against representative run output.

Coverage:

1. Aggregate correctness across a heterogeneous sample list:
   functional pass rate, hygiene index, safety totals, and per-axis
   pass rates must match hand-computed expected values.
2. Graceful degradation when telemetry metrics are absent, missing,
   or hold ``None`` — the exporter must omit the field rather than
   fabricate a value.
3. Non-EDS logs (e.g. a vanilla GAIA scorecard) must pass through
   unchanged: no EDS payload is invented and no exception is raised.
4. The ``write_eds_scorecard`` writer must produce a Markdown report
   plus a JSON blob whose shape matches what the dashboard's data
   pipeline expects (canonical ``eds_tag`` marker at ``"eds_tri_axis"``).
5. The hydrator's ``_harvest_eds_scorecards`` helper must merge
   ``results.eds.json`` aggregates into the leaderboard harvest
   under the canonical benchmark name without overwriting historic
   scores for other benchmarks.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pytest

from evalsbench.exporters import (
    EDS_AGGREGATE_KEYS,
    EDS_DASHBOARD_TAG,
    EDS_TELEMETRY_MEDIAN_KEYS,
    EDS_TELEMETRY_METRIC,
    EDS_TELEMETRY_ONLY_SCORER,
    EDS_TRI_AXIS_SCORER,
    extract_eds_metrics,
)
from evalsbench.exporters import write_eds_scorecard
from evalsbench.hydrator import _harvest_eds_scorecards


# ---------------------------------------------------------------------------
# Helpers — synthetic EvalLog construction (offline, no Inspect boot).
# ---------------------------------------------------------------------------


def _build_sample(
    sample_id: str,
    *,
    functional: float,
    composite: float,
    hygiene_index: float,
    safety_violations: int,
    critical_violations: int,
    axis1_passed: bool,
    axis2_passed: bool,
    axis3_safe: bool,
    safety_gate_active: bool,
) -> Dict[str, Any]:
    """Build a per-sample score entry mirroring the tri_axis output shape."""
    return {
        "id": sample_id,
        "scores": {
            EDS_TRI_AXIS_SCORER: {
                "value": {
                    "functional": functional,
                    "composite": composite,
                    "hygiene_index": hygiene_index,
                    "safety_violations": safety_violations,
                    "critical_violations": critical_violations,
                    "axis1_passed": axis1_passed,
                    "axis2_passed": axis2_passed,
                    "axis3_safe": axis3_safe,
                    "safety_gate_active": safety_gate_active,
                    "scenario_id": None,
                    "oracle_type": None,
                },
                "answer": "ok",
                "explanation": "synthetic",
            }
        },
    }


def _build_telemetry_metric(
    *,
    median_ttft_s: Optional[float],
    median_decode_tps: Optional[float],
    median_mtp_acceptance: Optional[float],
) -> Dict[str, Any]:
    """Build the ``eds_telemetry`` aggregate that inspect emits."""
    return {
        "median_ttft_s": median_ttft_s,
        "median_decode_tps": median_decode_tps,
        "median_mtp_acceptance": median_mtp_acceptance,
        "sample_count": 16,
        "coverage": {
            "median_ttft_s": 1.0,
            "median_decode_tps": 1.0,
            "median_mtp_acceptance": 1.0,
        },
    }


def _build_eds_log(
    *,
    sample_specs: List[Mapping[str, Any]],
    telemetry: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Wrap sample specs into a synthetic Inspect ``EvalLog`` dict."""
    samples = [_build_sample(**spec) for spec in sample_specs]
    log: Dict[str, Any] = {
        "eval": {"task": "minicorp", "model": "synthetic"},
        "samples": samples,
    }
    if telemetry is not None:
        log["results"] = {
            "scores": [
                {
                    "name": EDS_TRI_AXIS_SCORER,
                    "metrics": {
                        EDS_TELEMETRY_METRIC: dict(telemetry),
                    },
                }
            ]
        }
    return log


def _build_non_eds_log() -> Dict[str, Any]:
    """Build a vanilla GAIA-style EvalLog lacking every tri-axis key."""
    return {
        "eval": {"task": "gaia", "model": "synthetic"},
        "samples": [
            {
                "id": "gaia-1",
                "scores": {
                    "gaia_scorer": {
                        "value": 0.4,
                        "answer": "42",
                        "explanation": "guess",
                    }
                },
            }
        ],
        "results": {
            "scores": [
                {
                    "name": "gaia_scorer",
                    "metrics": {
                        "accuracy": 0.4,
                        "stderr": 0.05,
                    },
                }
            ]
        },
    }


# ---------------------------------------------------------------------------
# Fixtures — synthetic EDS sample bank for aggregate correctness tests.
# ---------------------------------------------------------------------------


# Eight samples hand-assembled to cover pass / fail / safety branches.
_EDS_SAMPLE_BANK = [
    {
        "sample_id": "eds-1",
        "functional": 1.0, "composite": 0.9, "hygiene_index": 0.85,
        "safety_violations": 0, "critical_violations": 0,
        "axis1_passed": True, "axis2_passed": True, "axis3_safe": True,
        "safety_gate_active": False,
    },
    {
        "sample_id": "eds-2",
        "functional": 0.0, "composite": 0.0, "hygiene_index": 1.0,
        "safety_violations": 2, "critical_violations": 1,
        "axis1_passed": False, "axis2_passed": True, "axis3_safe": False,
        "safety_gate_active": True,
    },
    {
        "sample_id": "eds-3",
        "functional": 1.0, "composite": 0.7, "hygiene_index": 0.4,
        "safety_violations": 1, "critical_violations": 0,
        "axis1_passed": True, "axis2_passed": False, "axis3_safe": True,
        "safety_gate_active": False,
    },
    {
        "sample_id": "eds-4",
        "functional": 0.5, "composite": 0.45, "hygiene_index": 0.7,
        "safety_violations": 0, "critical_violations": 0,
        "axis1_passed": True, "axis2_passed": True, "axis3_safe": True,
        "safety_gate_active": False,
    },
    {
        "sample_id": "eds-5",
        "functional": 0.5, "composite": 0.5, "hygiene_index": 0.6,
        "safety_violations": 0, "critical_violations": 0,
        "axis1_passed": True, "axis2_passed": True, "axis3_safe": True,
        "safety_gate_active": False,
    },
    {
        "sample_id": "eds-6",
        "functional": 0.25, "composite": 0.25, "hygiene_index": 0.0,
        "safety_violations": 3, "critical_violations": 0,
        "axis1_passed": False, "axis2_passed": False, "axis3_safe": True,
        "safety_gate_active": False,
    },
    {
        "sample_id": "eds-7",
        "functional": 1.0, "composite": 0.6, "hygiene_index": 0.55,
        "safety_violations": 0, "critical_violations": 0,
        "axis1_passed": True, "axis2_passed": True, "axis3_safe": True,
        "safety_gate_active": False,
    },
    {
        "sample_id": "eds-8",
        "functional": 0.0, "composite": 0.0, "hygiene_index": 0.2,
        "safety_violations": 5, "critical_violations": 2,
        "axis1_passed": False, "axis2_passed": False, "axis3_safe": False,
        "safety_gate_active": True,
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extract_eds_metrics_returns_empty_dict_for_none():
    """``None`` sources must produce an empty dict, not raise."""
    assert extract_eds_metrics(None) == {}


def test_extract_eds_metrics_returns_empty_dict_for_non_eds_log():
    """Non-EDS logs pass through cleanly: no key invention, no crash."""
    aggregates = extract_eds_metrics(_build_non_eds_log())
    assert aggregates == {}


def test_extract_eds_metrics_handles_dict_passthrough():
    """A redispatched dict (no path, no model object) is processed directly."""
    log = _build_eds_log(sample_specs=[_EDS_SAMPLE_BANK[0]])
    aggregates = extract_eds_metrics(log)
    assert aggregates["functional_pass_rate"] == 1.0
    assert aggregates["hygiene_index"] == 0.85
    assert aggregates["samples"] == 1


def test_extract_eds_metrics_aggregate_correctness():
    """Functional / hygiene / safety totals match hand-computed expectations.

    With eight samples we expect:
      * functional pass rate: mean of (1,0,1,0.5,0.5,0.25,1,0) = 0.5313
      * mean composite:      mean of (0.9,0,0.7,0.45,0.5,0.25,0.6,0) = 0.425
      * hygiene index:       mean of (0.85,1.0,0.4,0.7,0.6,0,0.55,0.2) = 0.5375
      * safety violations total: 0+2+1+0+0+3+0+5 = 11
      * critical violations total: 0+1+0+0+0+0+0+2 = 3
      * safety_gate_pass_rate (fraction NOT gated): 6 / 8 = 0.75
      * axis1_pass_rate: 5 / 8 (samples 1,3,4,5,7)
      * axis2_pass_rate: 5 / 8 (samples 1,2,4,5,7 — those with hygiene >= 0.5)
      * axis3_safe_rate: 6 / 8 (samples 1,3,4,5,6,7)
    """
    log = _build_eds_log(sample_specs=_EDS_SAMPLE_BANK)
    aggregates = extract_eds_metrics(log)

    assert aggregates["samples"] == 8
    assert aggregates["functional_pass_rate"] == pytest.approx(0.5313, abs=1e-3)
    assert aggregates["mean_composite"] == pytest.approx(0.425, abs=1e-3)
    assert aggregates["hygiene_index"] == pytest.approx(0.5375, abs=1e-3)
    assert aggregates["safety_violations_total"] == 11
    assert aggregates["critical_violations_total"] == 3
    assert aggregates["safety_gate_pass_rate"] == pytest.approx(0.75, abs=1e-3)
    assert aggregates["axis1_pass_rate"] == pytest.approx(5 / 8, abs=1e-3)
    assert aggregates["axis2_pass_rate"] == pytest.approx(5 / 8, abs=1e-3)
    assert aggregates["axis3_safe_rate"] == pytest.approx(6 / 8, abs=1e-3)


def test_extract_eds_metrics_telemetry_fields_present():
    """Telemetry medians are extracted when supplied under ``eds_telemetry``."""
    log = _build_eds_log(
        sample_specs=_EDS_SAMPLE_BANK,
        telemetry=_build_telemetry_metric(
            median_ttft_s=0.18,
            median_decode_tps=42.4,
            median_mtp_acceptance=0.72,
        ),
    )
    aggregates = extract_eds_metrics(log)
    assert aggregates["median_ttft_s"] == pytest.approx(0.18, abs=1e-3)
    assert aggregates["median_decode_tps"] == pytest.approx(42.4, abs=1e-3)
    assert aggregates["median_mtp_acceptance"] == pytest.approx(0.72, abs=1e-3)


def test_extract_eds_metrics_graceful_degradation_when_telemetry_missing():
    """Telemetry absence must not crash AND must omit the field entirely.

    Dashboards distinguish "radius unknown" from "0.0" by checking for
    field presence, so we keep ``None`` OUT of the payload entirely.
    """
    log = _build_eds_log(sample_specs=_EDS_SAMPLE_BANK)  # no telemetry block
    aggregates = extract_eds_metrics(log)
    for key in ("median_ttft_s", "median_decode_tps", "median_mtp_acceptance"):
        assert key not in aggregates


def test_extract_eds_metrics_graceful_degradation_when_telemetry_none():
    """All-``None`` telemetry values degrade to omitted fields, not zeroes."""
    log = _build_eds_log(
        sample_specs=_EDS_SAMPLE_BANK,
        telemetry=_build_telemetry_metric(
            median_ttft_s=None,
            median_decode_tps=None,
            median_mtp_acceptance=None,
        ),
    )
    aggregates = extract_eds_metrics(log)
    for key in ("median_ttft_s", "median_decode_tps", "median_mtp_acceptance"):
        assert key not in aggregates
    # Tri-axis aggregates are still extracted independently.
    assert aggregates["samples"] == 8


def test_extract_eds_metrics_partial_score_payload_is_skipped():
    """Per-sample scores with non-dict ``value`` are skipped, not crashed."""
    log = _build_eds_log(sample_specs=_EDS_SAMPLE_BANK)
    # Inject a junk sample — exporter should drop it instead of raising.
    log["samples"].append({
        "id": "junk-1",
        "scores": {
            EDS_TRI_AXIS_SCORER: {"value": "not-a-dict", "answer": "", "explanation": ""},
        }
    })
    aggregates = extract_eds_metrics(log)
    # Eight valid samples were preserved; junk sample was dropped.
    assert aggregates["samples"] == 8


def test_extract_eds_metrics_unknown_source_returns_empty():
    """An unresolvable source (``str`` of a missing file) does not crash."""
    assert extract_eds_metrics("/nonexistent/path/foo.eval") == {}


def test_extract_eds_metrics_loads_eval_log_from_disk(tmp_path: Path):
    """A real ``.eval`` archive (raw JSON) loads and is processed correctly.

    Inspect's production archive uses Zstd compression — outside this
    synthetic test. We persist a plain JSON snapshot to confirm the
    JSON path decodes the same shape we'd see in production.
    """
    payload = _build_eds_log(sample_specs=_EDS_SAMPLE_BANK)
    log_path = tmp_path / "synthetic-eval-log.json"
    log_path.write_text(json.dumps(payload), encoding="utf-8")
    aggregates = extract_eds_metrics(log_path)
    assert aggregates["samples"] == 8
    assert aggregates["functional_pass_rate"] == pytest.approx(0.5313, abs=1e-3)


def test_extract_eds_metrics_handles_inspect_model_dump_shape():
    """Inspect AI's ``EvalLog.model_dump()`` shape is supported.

    Inspect emits ``samples[*].scores[*].value`` as a typed mapping
    that the exporter must accept. The structure is identical to the
    inline dict; this test only re-asserts the invariant on a copy
    stored under ``samples`` rather than ``scores``.
    """
    log = _build_eds_log(sample_specs=_EDS_SAMPLE_BANK)
    # Inspect sometimes nests the scorer value under ``results``:
    log_alternate = {
        "results": {
            "scores": [
                {
                    "name": EDS_TRI_AXIS_SCORER,
                    "metrics": {
                        EDS_TELEMETRY_METRIC: _build_telemetry_metric(
                            median_ttft_s=0.21,
                            median_decode_tps=44.0,
                            median_mtp_acceptance=0.65,
                        ),
                    },
                }
            ]
        },
        "samples": [
            {
                "id": "eds-1-alt",
                "results": {
                    "scores": {
                        EDS_TRI_AXIS_SCORER: {
                            "value": {
                                "functional": 0.8,
                                "composite": 0.6,
                                "hygiene_index": 0.75,
                                "safety_violations": 0,
                                "critical_violations": 0,
                                "axis1_passed": True,
                                "axis2_passed": True,
                                "axis3_safe": True,
                                "safety_gate_active": False,
                            }
                        }
                    }
                },
            }
        ],
    }
    aggregates = extract_eds_metrics(log_alternate)
    assert aggregates["samples"] == 1
    assert aggregates["functional_pass_rate"] == pytest.approx(0.8, abs=1e-3)
    assert aggregates["median_ttft_s"] == pytest.approx(0.21, abs=1e-3)


def test_write_eds_scorecard_writes_markdown_and_json(tmp_path: Path):
    """End-to-end writer check: markdown + JSON blob with the dashboard tag."""
    aggregates = {
        "samples": 16,
        "functional_pass_rate": 0.75,
        "mean_composite": 0.70,
        "hygiene_index": 0.62,
        "safety_violations_total": 4,
        "critical_violations_total": 1,
        "safety_gate_pass_rate": 0.94,
        "axis1_pass_rate": 0.81,
        "axis2_pass_rate": 0.75,
        "axis3_safe_rate": 0.94,
        "median_ttft_s": 0.21,
        "median_decode_tps": 42.0,
        "median_mtp_acceptance": 0.66,
    }
    json_path = write_eds_scorecard(
        tmp_path,
        benchmark_name="minicorp",
        aggregates=aggregates,
        model_name="synthetic-lite",
        endpoint_url="http://localhost:12468/v1",
    )
    md_path = tmp_path / "report.eds.md"
    assert json_path.exists()
    assert md_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["eds_tag"] == EDS_DASHBOARD_TAG
    assert payload["benchmark"] == "minicorp"
    assert payload["model"] == "synthetic-lite"
    assert payload["endpoint"] == "http://localhost:12468/v1"
    assert payload["aggregates"] == aggregates

    markdown = md_path.read_text(encoding="utf-8")
    assert "EDS Tri-Axis Scorecard: minicorp" in markdown
    assert "Functional" in markdown and "75.0%" in markdown
    assert "Median TTFT" in markdown and "0.210 s" in markdown


def test_write_eds_scorecard_handles_empty_aggregates(tmp_path: Path):
    """An empty-aggregates call still writes files (with a graceful placeholder)."""
    json_path = write_eds_scorecard(
        tmp_path,
        benchmark_name="minicorp",
        aggregates={},
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["eds_tag"] == EDS_DASHBOARD_TAG
    assert payload["aggregates"] == {}
    md_text = (tmp_path / "report.eds.md").read_text(encoding="utf-8")
    assert "No EDS tri-axis aggregates detected" in md_text


def test_write_eds_scorecard_dashboard_data_blob_shape(tmp_path: Path):
    """The exported JSON is shaped correctly for the dashboard data pipeline.

    The dashboard reads ``results.eds.json`` aggregate keys verbatim so
    the harvest step is a 1:1 mapping. We assert the canonical field
    set is present (matching :data:`EDS_AGGREGATE_KEYS`).
    """
    aggregates = {
        "samples": 16,
        "functional_pass_rate": 0.75,
        "mean_composite": 0.70,
        "hygiene_index": 0.62,
        "safety_violations_total": 4,
        "critical_violations_total": 1,
        "safety_gate_pass_rate": 0.94,
        "axis1_pass_rate": 0.81,
        "axis2_pass_rate": 0.75,
        "axis3_safe_rate": 0.94,
        "median_ttft_s": 0.21,
        "median_decode_tps": 42.0,
        "median_mtp_acceptance": 0.66,
    }
    json_path = write_eds_scorecard(
        tmp_path,
        benchmark_name="minicorp",
        aggregates=aggregates,
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload_aggregates = payload["aggregates"]
    for canonical_key in EDS_AGGREGATE_KEYS:
        assert canonical_key in payload_aggregates
    # Top-level shape preserved: benchmark, timestamp, model, endpoint,
    # raw_log, eds_tag, aggregates.
    expected_top_keys = {
        "benchmark", "timestamp", "model", "endpoint", "raw_log",
        "eds_tag", "aggregates",
    }
    assert expected_top_keys.issubset(set(payload.keys()))


def test_harvest_eds_scorecards_merges_results_eds_json(tmp_path, monkeypatch):
    """EDS harvest merges results.eds.json into the leaderboard harvest.

    We patch :data:`evalsbench.hydrator.LOGS_DIR` to a fresh tmp
    directory so the test never touches the user's benchmark log
    corpus, then drop two files (one EDS, one unrelated) and verify
    the EDS entry surfaces under the canonical benchmark key with
    the ``eds_tag`` marker preserved.
    """
    from evalsbench import hydrator

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    sample_run = log_dir / "20260101_model-mini_minicorp"
    sample_run.mkdir()
    eds_json = sample_run / "results.eds.json"
    aggregates = {
        "samples": 8,
        "functional_pass_rate": 0.625,
        "hygiene_index": 0.55,
        "safety_violations_total": 1,
        "critical_violations_total": 0,
        "median_ttft_s": 0.20,
        "median_decode_tps": 36.0,
        "median_mtp_acceptance": 0.6,
    }
    eds_json.write_text(json.dumps({
        "benchmark": "minicorp",
        "model": "model-mini",
        "endpoint": "http://nowhere/v1",
        "raw_log": None,
        "eds_tag": "eds_tri_axis",
        "timestamp": "2026-01-01 00:00:00",
        "aggregates": aggregates,
    }), encoding="utf-8")

    # Drop an unrelated results.eds.json without the canonical tag —
    # it must be ignored, never cross-contaminate.
    other_run = log_dir / "20260101_legacy_run_minicorp"
    other_run.mkdir()
    (other_run / "results.eds.json").write_text(json.dumps({
        "benchmark": "minicorp",
        "model": "legacy",
        "eds_tag": "garbage",
        "aggregates": {"functional_pass_rate": 0.1},
    }), encoding="utf-8")

    monkeypatch.setattr(hydrator, "LOGS_DIR", log_dir)
    harvested = _harvest_eds_scorecards()

    assert "model-mini" in harvested
    assert "legacy" not in harvested
    payload = harvested["model-mini"]["minicorp"]
    # Aggregates are preserved verbatim (no field loss).
    assert payload["functional_pass_rate"] == pytest.approx(0.625, abs=1e-3)
    assert payload["hygiene_index"] == pytest.approx(0.55, abs=1e-3)
    assert payload["eds_tag"] == "eds_tri_axis"


def test_harvest_eds_scorecards_handles_missing_directory(tmp_path, monkeypatch):
    """Empty / missing logs directory yields an empty harvest (no raise)."""
    from evalsbench import hydrator
    monkeypatch.setattr(hydrator, "LOGS_DIR", tmp_path / "absent-logs")
    assert _harvest_eds_scorecards() == {}


def test_hydrator_full_pipeline_includes_eds_entry(tmp_path, monkeypatch):
    """End-to-end: harvest_all + EDS aggregates merge under canonical key."""
    from evalsbench import hydrator

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    run_dir = log_dir / "20260101_demo_minicorp"
    run_dir.mkdir()
    (run_dir / "results.eds.json").write_text(json.dumps({
        "benchmark": "minicorp",
        "model": "demo-local",
        "endpoint": None,
        "raw_log": None,
        "eds_tag": "eds_tri_axis",
        "timestamp": "2026-01-01 00:00:00",
        "aggregates": {
            "functional_pass_rate": 0.5,
            "hygiene_index": 0.4,
            "safety_violations_total": 0,
            "critical_violations_total": 0,
            "samples": 4,
        },
    }), encoding="utf-8")

    monkeypatch.setattr(hydrator, "LOGS_DIR", log_dir)
    # Avoid touching configs/models.yaml and CHAI vault in the test.
    monkeypatch.setattr(hydrator, "MODELS_YAML_PATH", log_dir / "no-models-yaml.yaml")
    monkeypatch.setattr(hydrator, "CHAI_MODELS_DIR", tmp_path / "no-chai-vault")

    harvest = hydrator.harvest_all_benchmark_scores()
    assert "demo-local" in harvest
    mini = harvest["demo-local"]["minicorp"]
    assert mini["functional_pass_rate"] == pytest.approx(0.5, abs=1e-3)
    assert mini["eds_tag"] == "eds_tri_axis"


def test_non_eds_log_does_not_pollute_hydrator(tmp_path, monkeypatch):
    """A vanilla results.json without results.eds.json keeps the harvest EDS-free."""
    from evalsbench import hydrator

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    run_dir = log_dir / "20260101_demo_ifeval"
    run_dir.mkdir()
    (run_dir / "results.json").write_text(json.dumps({
        "model": "demo-local",
        "benchmark": "ifeval",
        "scores": {"prompt_strict_acc": 0.8},
    }), encoding="utf-8")

    monkeypatch.setattr(hydrator, "LOGS_DIR", log_dir)
    monkeypatch.setattr(hydrator, "MODELS_YAML_PATH", log_dir / "no-models-yaml.yaml")
    monkeypatch.setattr(hydrator, "CHAI_MODELS_DIR", tmp_path / "no-chai-vault")
    harvest = hydrator.harvest_all_benchmark_scores()
    assert harvest["demo-local"]["ifeval"]["prompt_strict_acc"] == pytest.approx(0.8)
    # No EDS tag assigned unless there's an EDS path.
    assert "minicorp" not in harvest["demo-local"]


# ---------------------------------------------------------------------------
# Re-verification — FIX B-1: individually-named median_* metrics
# ---------------------------------------------------------------------------
#
# These tests pin the Real Inspect AI ``.eval`` shape (flattened
# ``@metric`` outputs under ``results.scores[*].metrics[<field_name>]``)
# to guarantee that the canonical median_* aggregates reach
# ``configs/models.yaml`` and the dashboard, no matter which Inspect
# version writes the archive.


def _build_real_shape_eds_log(
    *,
    sample_specs: List[Mapping[str, Any]],
    median_ttft_s: Optional[float],
    median_decode_tps: Optional[float],
    median_mtp_acceptance: Optional[float],
    sample_count_telemetry: int = 8,
) -> Dict[str, Any]:
    """Build an EvalLog mirroring the REAL Inspect AI archive shape.

    Mirrors what `python -m inspect_ai eval` writes today:

    * ``tri_axis`` scorer carries the ``@metric`` outputs flattened
      into ``metrics[<field_name>]`` typed entries, each with a
      ``value`` field, ``name``, ``group="eds_telemetry"``, and
      control-plane members (``params``, ``metadata``).
    * ``__eds_telemetry_only__`` sentinel scorer is the canonical
      home for the run-level telemetry (it is appended by
      :mod:`evalsbench.eds.solver`).
    """
    samples = [_build_sample(**spec) for spec in sample_specs]

    def _entry(field: str, value: Optional[float], group: str = "eds_telemetry") -> Dict[str, Any]:
        return {
            "name": field,
            "group": group,
            "value": value if value is not None else 0.0,
            "params": {},
            "metadata": {},
        }

    tri_axis_flat = {
        "sample_count": _entry("sample_count", 0.0),
        "coverage_median_ttft_s": _entry("coverage_median_ttft_s", 0.0),
        "coverage_median_decode_tps": _entry("coverage_median_decode_tps", 0.0),
        "coverage_median_mtp_acceptance": _entry("coverage_median_mtp_acceptance", 0.0),
    }

    telemetry_flat: Dict[str, Any] = {
        "sample_count": _entry("sample_count", float(sample_count_telemetry)),
        "coverage_median_ttft_s": _entry("coverage_median_ttft_s", 1.0),
    }
    if median_ttft_s is not None:
        telemetry_flat["median_ttft_s"] = _entry("median_ttft_s", median_ttft_s)
    if median_decode_tps is not None:
        telemetry_flat["median_decode_tps"] = _entry("median_decode_tps", median_decode_tps)
        telemetry_flat["coverage_median_decode_tps"] = _entry("coverage_median_decode_tps", 1.0)
    if median_mtp_acceptance is not None:
        telemetry_flat["median_mtp_acceptance"] = _entry("median_mtp_acceptance", median_mtp_acceptance)
        telemetry_flat["coverage_median_mtp_acceptance"] = _entry("coverage_median_mtp_acceptance", 1.0)

    log: Dict[str, Any] = {
        "eval": {"task": "minicorp", "model": "synthetic"},
        "samples": samples,
        "results": {
            "scores": [
                {"name": EDS_TRI_AXIS_SCORER, "group": None, "metrics": tri_axis_flat},
                {"name": EDS_TELEMETRY_ONLY_SCORER, "group": None, "metrics": telemetry_flat},
            ]
        },
    }
    return log


def test_extract_eds_metrics_harvests_individual_named_median_metrics():
    """REAL .eval shape: individually-named median_* entries drive aggregates."""
    log = _build_real_shape_eds_log(
        sample_specs=_EDS_SAMPLE_BANK,
        median_ttft_s=0.21,
        median_decode_tps=38.5,
        median_mtp_acceptance=0.66,
        sample_count_telemetry=8,
    )
    aggregates = extract_eds_metrics(log)

    assert aggregates["samples"] == 8
    assert aggregates["functional_pass_rate"] == pytest.approx(0.5313, abs=1e-3)
    assert aggregates["hygiene_index"] == pytest.approx(0.5375, abs=1e-3)

    assert aggregates["median_ttft_s"] == pytest.approx(0.21, abs=1e-3)
    assert aggregates["median_decode_tps"] == pytest.approx(38.5, abs=1e-3)
    assert aggregates["median_mtp_acceptance"] == pytest.approx(0.66, abs=1e-3)


def test_extract_eds_metrics_last_wins_for_real_shape():
    """tri_axis zero-valued metrics must NOT shadow the sentinel row."""
    log = _build_real_shape_eds_log(
        sample_specs=_EDS_SAMPLE_BANK,
        median_ttft_s=0.42,
        median_decode_tps=88.0,
        median_mtp_acceptance=0.91,
    )
    aggregates = extract_eds_metrics(log)
    assert aggregates["median_ttft_s"] == pytest.approx(0.42, abs=1e-3)
    assert aggregates["median_decode_tps"] == pytest.approx(88.0, abs=1e-3)
    assert aggregates["median_mtp_acceptance"] == pytest.approx(0.91, abs=1e-3)


def test_extract_eds_metrics_handles_scalar_metric_entry_shape():
    """Older Inspect versions store flattened metrics as raw scalars."""
    log = _build_eds_log(sample_specs=_EDS_SAMPLE_BANK[:2])
    log["results"] = {
        "scores": [
            {
                "name": EDS_TRI_AXIS_SCORER,
                "metrics": {
                    "median_ttft_s": 0.10,
                    "median_decode_tps": 21.0,
                    "median_mtp_acceptance": 0.55,
                },
            }
        ]
    }
    aggregates = extract_eds_metrics(log)
    assert aggregates["median_ttft_s"] == pytest.approx(0.10, abs=1e-3)
    assert aggregates["median_decode_tps"] == pytest.approx(21.0, abs=1e-3)
    assert aggregates["median_mtp_acceptance"] == pytest.approx(0.55, abs=1e-3)


def test_extract_eds_metrics_telemetry_only_scorer_does_not_pollute_functional():
    """Sentinel scorer MUST NOT contribute to functional aggregates."""
    log = _build_real_shape_eds_log(
        sample_specs=_EDS_SAMPLE_BANK,
        median_ttft_s=0.5,
        median_decode_tps=99.0,
        median_mtp_acceptance=0.5,
    )
    poison_samples: List[Dict[str, Any]] = []
    for spec in _EDS_SAMPLE_BANK:
        poison_samples.append({
            "id": spec["sample_id"],
            "scores": {
                EDS_TELEMETRY_ONLY_SCORER: {
                    "value": {"functional": 0.0, "composite": -1.0},
                    "answer": "",
                    "explanation": "poison",
                }
            },
        })
    log["samples"].extend(poison_samples)

    aggregates = extract_eds_metrics(log)
    assert aggregates["samples"] == 8
    assert aggregates["functional_pass_rate"] == pytest.approx(0.5313, abs=1e-3)
    assert aggregates["median_ttft_s"] == pytest.approx(0.5, abs=1e-3)
    assert aggregates["median_decode_tps"] == pytest.approx(99.0, abs=1e-3)


# ---------------------------------------------------------------------------
# Re-verification — FIX B-2: Zstd-compatible ``.eval`` reader
# ---------------------------------------------------------------------------


def test_load_eval_log_prefers_inspect_ai_read_eval_log(tmp_path: Path, monkeypatch):
    """Path-based reader delegates to ``inspect_ai.log.read_eval_log`` first."""
    import inspect_ai.log as _inspect_log

    expected_payload = {
        "samples": [],
        "results": {
            "scores": [
                {
                    "name": EDS_TELEMETRY_ONLY_SCORER,
                    "metrics": {
                        "median_ttft_s": {"value": 0.18, "name": "median_ttft_s", "group": "eds_telemetry"},
                        "median_decode_tps": {"value": 42.0, "name": "median_decode_tps", "group": "eds_telemetry"},
                        "median_mtp_acceptance": {"value": 0.7, "name": "median_mtp_acceptance", "group": "eds_telemetry"},
                    },
                }
            ]
        },
    }

    captured: Dict[str, List[str]] = {"calls": []}

    class _FakeEvalLog:
        """Minimal stand-in for inspect_ai's :class:`EvalLog`."""

        def model_dump(self, mode: Optional[str] = None) -> Dict[str, Any]:
            return expected_payload

    def _fake_read_eval_log(path_arg: Any) -> _FakeEvalLog:
        captured["calls"].append(str(path_arg))
        return _FakeEvalLog()

    monkeypatch.setattr(_inspect_log, "read_eval_log", _fake_read_eval_log)

    log_path = tmp_path / "sentinel.eval"
    log_path.write_bytes(b"placeholder-bytes")
    aggregates = extract_eds_metrics(log_path)

    assert captured["calls"] == [str(log_path)], (
        f"read_eval_log was not consulted. calls={captured['calls']}"
    )
    assert aggregates["median_ttft_s"] == pytest.approx(0.18, abs=1e-3)
    assert aggregates["median_decode_tps"] == pytest.approx(42.0, abs=1e-3)
    assert aggregates["median_mtp_acceptance"] == pytest.approx(0.7, abs=1e-3)


def test_load_eval_log_falls_back_to_stdlib_zipfile(tmp_path: Path, monkeypatch):
    """If ``inspect_ai.log.read_eval_log`` raises, stdlib zipfile kicks in."""
    import inspect_ai.log as _inspect_log

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated Zstd decode failure")

    monkeypatch.setattr(_inspect_log, "read_eval_log", _raise)

    log_path = tmp_path / "legacy-eval.eval"
    samples_payload = _build_eds_log(
        sample_specs=_EDS_SAMPLE_BANK,
        telemetry=_build_telemetry_metric(
            median_ttft_s=0.18,
            median_decode_tps=42.0,
            median_mtp_acceptance=0.7,
        ),
    )
    header = {
        "eval": {"task": "minicorp", "model": "legacy"},
        "results": samples_payload.get("results") or {},
    }
    with zipfile.ZipFile(log_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("header.json", json.dumps(header))
        for sample in samples_payload["samples"]:
            zf.writestr(
                f"samples/{sample['id']}.json",
                json.dumps(sample),
            )
        zf.writestr("summaries.json", json.dumps({}))

    aggregates = extract_eds_metrics(log_path)
    assert aggregates["samples"] == 8
    assert aggregates["functional_pass_rate"] == pytest.approx(0.5313, abs=1e-3)
    assert aggregates["median_ttft_s"] == pytest.approx(0.18, abs=1e-3)
    assert aggregates["median_decode_tps"] == pytest.approx(42.0, abs=1e-3)


def test_extract_eds_metrics_decodes_real_inspect_zstd_archive(tmp_path: Path):
    """REAL Inspect ``.eval`` archive (Zstd-compressed) decodes end-to-end."""
    import os
    import shutil

    candidates = [
        "/tmp/eds_reverify_c",
        "/tmp/eds_parity_log",
        "/tmp/eds_verify_log",
        "/tmp/eds_verify_log3",
    ]
    src_dir = next((d for d in candidates if os.path.isdir(d)), None)
    if src_dir is None:
        pytest.skip("no real Inspect .eval archive available to copy")

    real_archives = sorted(
        (os.path.join(src_dir, f) for f in os.listdir(src_dir) if f.endswith(".eval")),
    )
    if not real_archives:
        pytest.skip(f"no .eval archive under {src_dir}")
    src_path = Path(real_archives[-1])

    dest_path = tmp_path / src_path.name
    shutil.copy2(src_path, dest_path)

    with zipfile.ZipFile(dest_path) as zf:
        header_info = zf.getinfo("header.json")
    assert header_info.compress_type == 93, (
        f"expected compress_type=93 (Zstd), got {header_info.compress_type}"
    )

    aggregates = extract_eds_metrics(dest_path)
    assert aggregates.get("median_decode_tps") is not None
    assert aggregates["median_decode_tps"] > 0


def test_coerce_metric_scalar_via_value_rejects_control_plane_keys():
    """Coercer must skip ``params`` / ``metadata`` control-plane fields."""
    from evalsbench.exporters import _coerce_metric_scalar_via_value

    entry = {
        "name": "median_ttft_s",
        "group": "eds_telemetry",
        "value": None,
        "params": {"window": 100},
        "metadata": {"source": "fast"},
    }
    assert _coerce_metric_scalar_via_value(None) is None
    assert _coerce_metric_scalar_via_value(True) is None
    assert _coerce_metric_scalar_via_value(0.42) == pytest.approx(0.42, abs=1e-3)
    assert _coerce_metric_scalar_via_value({"value": 1.23, "name": "x"}) == pytest.approx(1.23, abs=1e-3)
    assert _coerce_metric_scalar_via_value({"value": None, "decoded": 7.5}) == pytest.approx(7.5, abs=1e-3)
    assert _coerce_metric_scalar_via_value(entry) is None


def test_canonical_aggregate_keys_include_telemetry_median_fields():
    """``EDS_AGGREGATE_KEYS`` includes all three canonical median fields."""
    for field in EDS_TELEMETRY_MEDIAN_KEYS:
        assert field in EDS_AGGREGATE_KEYS, (
            f"canonical median field {field!r} missing from EDS_AGGREGATE_KEYS"
        )
