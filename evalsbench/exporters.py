"""
Result exporting: Markdown reports, JSON telemetry, dynamic models.yaml, and ChAI sync.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml

from .config import CONFIGS_DIR, MODELS_YAML_PATH, CHAI_MODELS_DIR


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
