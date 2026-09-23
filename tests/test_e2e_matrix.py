"""
End-to-end verification of the EvalsBench V2 3D Operational Matrix
(PRD: 3D Matrix, Declarative Engine & Real-Time Telemetry).

Offline-safe by design: every test exercises the declarative registry,
the provider router, the telemetry monitor, the CLI scale flags, and
the custom- exporters routing WITHOUT network access, Docker, or a
live inference endpoint. A live preflight ping (Task 4.2's real
verification command) must be run manually against an active endpoint.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Wave 0 — Declarative schema & provider router
# ---------------------------------------------------------------------------

def test_benchmarks_yaml_schema():
    """Task 0.1: benchmarks.yaml carries the full V2 schema."""
    import yaml

    data = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "configs" / "benchmarks.yaml")
        .read_text(encoding="utf-8")
    )
    assert "core" in data["presets"]
    assert "agent" in data["presets"]
    assert "knowledge" in data["presets"]
    assert "all" in data["presets"]
    assert len(data["benchmarks"]) == 10
    for key, spec in data["benchmarks"].items():
        assert spec["scoring_mode"] in ("immediate", "deferred"), key
        assert spec.get("description"), key
    assert data["scales"]["short"]["limit"] == 20
    assert data["scales"]["long"]["limit"] == 100
    assert data["scales"]["complete"]["limit"] is None
    assert data["profiles"]["gatekeeper"] == {
        "easy": 0.50, "medium": 0.40, "hard": 0.10,
        "description": data["profiles"]["gatekeeper"]["description"],
    }


def test_router_cloud_resolution():
    """Task 0.2: provider prefixes resolve to cloud routing + env keys."""
    from evalsbench.router import resolve_model_and_env

    model, provider, is_cloud, env = resolve_model_and_env("google/gemini-2.5-flash")
    assert is_cloud is True
    assert provider == "google"
    assert "GEMINI_API_KEY" in env
    assert model == "google/gemini-2.5-flash"

    for model_str, key in [
        ("deepseek/deepseek-chat", "DEEPSEEK_API_KEY"),
        ("anthropic/claude-3-5-sonnet", "ANTHROPIC_API_KEY"),
        ("openrouter/meta-llama/llama-3", "OPENROUTER_API_KEY"),
    ]:
        _, _, cloud, env_overrides = resolve_model_and_env(model_str)
        assert cloud is True
        assert key in env_overrides


def test_router_local_fallthrough():
    """Local aliases fall through to the OpenAI-compatible path untouched."""
    from evalsbench.router import resolve_model_and_env

    model, provider, is_cloud, env = resolve_model_and_env("master-lite", "http://localhost:12468/v1")
    assert is_cloud is False
    assert provider == "local"
    assert env == {}
    assert model == "master-lite"


# ---------------------------------------------------------------------------
# Wave 1 — Registry & engine
# ---------------------------------------------------------------------------

def test_registry_yaml_load_with_custom_keys():
    """Task 1.1: registry loads YAML; custom-minicorp registered."""
    from evalsbench.registry import BENCHMARK_REGISTRY, PRESET_SUITES

    assert "custom-minicorp" in BENCHMARK_REGISTRY
    assert "core" in PRESET_SUITES
    assert PRESET_SUITES["core"] == ["ifeval", "bfcl", "humaneval", "custom-minicorp", "writingbench"]
    task = BENCHMARK_REGISTRY["custom-minicorp"]
    assert task.is_custom is True
    assert task.scoring_mode == "immediate"
    assert task.max_samples == 16
    # eds:minicorp sentinel resolved to the absolute file-path task id
    assert task.task_id.endswith("tasks.py@minicorp")
    assert task.task_id.startswith("/")


def test_registry_defensive_fallback(tmp_path, monkeypatch):
    """Missing/malformed YAML degrades to the in-code default registry."""
    import evalsbench.registry as registry_mod

    monkeypatch.setattr(registry_mod, "BENCHMARKS_YAML_PATH", tmp_path / "missing.yaml")
    fallback = registry_mod._build_registry()
    assert "custom-minicorp" in fallback
    assert "ifeval" in fallback


def test_difficulty_stratification_fall_through(capsys):
    """Task 1.1: unstratified tasks return [] with an informational notice."""
    from evalsbench.registry import get_difficulty_task_args

    args = get_difficulty_task_args("custom-minicorp", "echelon")
    assert args == []
    assert "no difficulty subsets" in capsys.readouterr().out
    # Stratifiable tasks still resolve.
    assert get_difficulty_task_args("niah", "gatekeeper") != []


def test_runner_routing_contracts():
    """Task 1.2: runner selects model spec + env per routing decision."""
    from evalsbench.runner import EvalsRunner

    local = EvalsRunner("master-lite", "http://localhost:12468/v1")
    assert hasattr(local, "run_benchmark")
    assert local.is_cloud is False
    assert local._model_spec() == "openai/master-lite"

    cloud = EvalsRunner("deepseek/deepseek-chat", "https://api.deepseek.com/v1")
    assert cloud.is_cloud is True
    assert cloud._model_spec() == "deepseek/deepseek-chat"
    assert "DEEPSEEK_API_KEY" in cloud.cloud_env


# ---------------------------------------------------------------------------
# Wave 2 — Live telemetry engine
# ---------------------------------------------------------------------------

def test_live_telemetry_monitor_contract():
    """Task 2.1: monitor records per-sample telemetry and renders."""
    from evalsbench.progress import LiveTelemetryMonitor

    monitor = LiveTelemetryMonitor("test", 20, scoring_mode="immediate")
    monitor.record_sample_telemetry(1, 100, 20, 50, 200.0, 16.5, None, "PASS")
    monitor.close()  # smoke: must not raise

    summary = monitor.summary()
    assert summary["avg_ttft_ms"] == 200.0
    assert summary["avg_decode_tps"] == 16.5
    assert summary["cache_hit_rate"] == pytest.approx(0.20, abs=1e-3)
    assert summary["mtp_acceptance_rate"] is None  # MTP disabled


def test_live_telemetry_monitor_mtp_and_deferred():
    """Task 2.1: MTP stats compute acceptance rate; deferred mode has no verdict."""
    from evalsbench.progress import LiveTelemetryMonitor

    monitor = LiveTelemetryMonitor("t", 20, scoring_mode="deferred")
    monitor.record_sample_telemetry(2, 1387, 364, 412, 472.0, 16.4, (320, 393), None)
    summary = monitor.summary()
    assert summary["mtp_acceptance_rate"] == pytest.approx(320 / 393, abs=1e-3)
    # Deferred: no verdict recorded, no running accuracy.
    assert monitor.last_accuracy is None
    monitor.close()


def test_live_telemetry_slot_saturation():
    """Task 2.2: slot poller feed updates saturation state."""
    from evalsbench.progress import LiveTelemetryMonitor

    monitor = LiveTelemetryMonitor("t", 20, max_connections=4)
    monitor.set_slot_status(3, 4)
    monitor.set_aggregate_tps(48.2)
    row = monitor._saturation_row()
    assert "3/4" in row
    assert "48.2 tok/s" in row


# ---------------------------------------------------------------------------
# Wave 3 — CLI & exporters
# ---------------------------------------------------------------------------

def test_cli_scale_flags(monkeypatch):
    """Task 3.1: --short/--long/--complete resolve to scale limits."""
    from evalsbench.cli import parse_args

    def _argv(*tokens):
        monkeypatch.setattr(sys, "argv", ["evalsbench", *tokens])
        return parse_args()

    args = _argv("--model", "m", "--suite", "core", "--short")
    assert args.short is True and args.long is False and args.complete is False
    args = _argv("--model", "m", "--suite", "core", "--complete")
    assert args.complete is True
    args = _argv("--model", "m", "--suite", "core", "--long")
    assert args.long is True
    args = _argv("--model", "m", "--suite", "core", "--time-limit", "120")
    assert args.time_limit == 120


def test_exporters_custom_namespace_routing():
    """Task 3.2: custom- prefix routes to EDS scoring deterministically."""
    from evalsbench.exporters import is_eds_benchmark, EDS_BENCHMARK_KEYS

    assert is_eds_benchmark("custom-minicorp")
    assert is_eds_benchmark("custom-whatever-domain")
    assert is_eds_benchmark("minicorp")
    assert not is_eds_benchmark("ifeval")
    assert not is_eds_benchmark("")
    # Canonical keys untouched.
    assert "minicorp" in EDS_BENCHMARK_KEYS


def test_update_models_yaml_persists_telemetry(tmp_path, monkeypatch):
    """Task 3.2: telemetry fields land in the models.yaml ledger entry."""
    import yaml
    import evalsbench.exporters as exporters_mod

    target = tmp_path / "models.yaml"
    monkeypatch.setattr(exporters_mod, "MODELS_YAML_PATH", target)
    exporters_mod.update_models_yaml(
        model_name="master-lite",
        endpoint_url="http://localhost:12468/v1",
        benchmark_name="Custom-MiniCorp",
        scores={"functional_pass_rate": 0.875},
        duration_s=102.4,
        telemetry={"avg_ttft_ms": 468.0, "avg_decode_tps": 16.5, "cache_hit_rate": 0.284},
    )
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    entry = data["models"]["master-lite"]
    assert entry["telemetry"]["avg_ttft_ms"] == 468.0
    assert entry["telemetry"]["avg_decode_tps"] == 16.5
    assert entry["benchmarks"]["Custom-MiniCorp"]["scores"]["functional_pass_rate"] == 0.875


# ---------------------------------------------------------------------------
# Wave 4 — Facilitation skill & E2E wiring
# ---------------------------------------------------------------------------

def test_skill_md_documents_3d_matrix():
    """Task 4.1: the facilitation skill carries the 3D matrix contract."""
    skill = (
        Path(__file__).resolve().parent.parent
        / "skills" / "run-evals" / "SKILL.md"
    ).read_text(encoding="utf-8")
    for token in ("--short", "--long", "--complete", "gatekeeper", "echelon",
                  "core", "agent", "knowledge", "custom-minicorp", "Scoring"):
        assert token in skill, f"SKILL.md missing {token}"


def test_modality_filter():
    """--modality filter: gaia/docvqa are multimodal; the rest text-only."""
    from evalsbench.registry import filter_tasks_by_modality, BENCHMARK_REGISTRY

    suite = ["gaia", "docvqa", "ifeval", "bfcl", "custom-minicorp"]
    kept_mm, dropped_mm = filter_tasks_by_modality(suite, "multimodal")
    assert kept_mm == ["gaia", "docvqa"]
    assert dropped_mm == ["ifeval", "bfcl", "custom-minicorp"]

    kept_txt, dropped_txt = filter_tasks_by_modality(suite, "text")
    assert kept_txt == ["ifeval", "bfcl", "custom-minicorp"]
    assert dropped_txt == ["gaia", "docvqa"]

    kept_all, dropped_all = filter_tasks_by_modality(suite, None)
    assert kept_all == suite and dropped_all == []

    # Registry consistency: every multimodal task is flagged in YAML.
    assert BENCHMARK_REGISTRY["gaia"].multimodal is True
    assert BENCHMARK_REGISTRY["docvqa"].multimodal is True
    assert BENCHMARK_REGISTRY["custom-minicorp"].multimodal is False
    assert BENCHMARK_REGISTRY["terminal_bench_2"].multimodal is False


def test_slot_poller_strips_v1_prefix():
    """Audit fix: /slots is mounted at host root, not under /v1."""
    from evalsbench.progress import LiveTelemetryMonitor
    from evalsbench.runner import _SlotPoller

    monitor = LiveTelemetryMonitor("t", 20)
    poller = _SlotPoller("http://localhost:1123/v1", monitor)
    assert poller._slots_url == "http://localhost:1123/slots"

    poller = _SlotPoller("http://localhost:8000", monitor)
    assert poller._slots_url == "http://localhost:8000/slots"

    # Trailing-slash variants normalize identically.
    poller = _SlotPoller("http://localhost:12468/v1/", monitor)
    assert poller._slots_url == "http://localhost:12468/slots"


def test_full_matrix_wire_up():
    """Integration: every 3D axis resolves end-to-end from the YAML."""
    from evalsbench.registry import BENCHMARK_REGISTRY, PRESET_SUITES, SCALES, DIFFICULTY_PROFILES

    # Every preset member exists in the registry.
    for preset, members in PRESET_SUITES.items():
        for key in members:
            assert key in BENCHMARK_REGISTRY, f"{preset} references unknown benchmark {key}"
    # Scales and profiles carry the 3 axes.
    assert set(("short", "long", "complete")) <= set(SCALES.keys())
    assert {"gatekeeper", "echelon", "full"} <= set(DIFFICULTY_PROFILES.keys())
    # The all-suite spans the full 10-benchmark battery.
    assert len(PRESET_SUITES["all"]) == 10
