"""
Environment, endpoint discovery, and path configuration.
"""

import os
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime
import urllib.request
import json

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = REPO_ROOT / "logs"
CONFIGS_DIR = REPO_ROOT / "configs"
MODELS_YAML_PATH = CONFIGS_DIR / "models.yaml"
CHAI_MODELS_DIR = Path("/home/sumergoconicio/chai/references/models")
CHAI_ENV_PATH = Path("/home/sumergoconicio/chai/.env")

# Common local ports to auto-probe for active OpenAI-compatible servers
LOCAL_PROBE_PORTS = [2468, 8000, 8080, 11434, 5000, 12345]


def load_chai_env() -> dict[str, str]:
    """Load environment variables from ~/chai/.env if available."""
    env_vars = {}
    if CHAI_ENV_PATH.exists():
        try:
            with open(CHAI_ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip().strip("'\"")
        except Exception:
            pass
    return env_vars


def auto_probe_local_endpoint() -> Optional[Tuple[str, str]]:
    """
    Probes local ports for an active /v1/models endpoint.
    Returns (endpoint_url, model_name) if found, else None.
    """
    for port in LOCAL_PROBE_PORTS:
        url = f"http://localhost:{port}/v1"
        try:
            req = urllib.request.Request(f"{url}/models", headers={"User-Agent": "EvalsBench"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    models = [m.get("id") for m in data.get("data", []) if m.get("id")]
                    if models:
                        # Prefer primary model name over generic aliases like 'workhorse'
                        primary = [m for m in models if m not in ("workhorse", "frontier", "lite")]
                        selected_model = primary[0] if primary else models[0]
                        return url, selected_model
        except Exception:
            continue
    return None


def get_log_dir_for_benchmark(model_name: str, benchmark_name: str) -> Path:
    """
    Returns the strict directory path formatted as:
    repo-root/logs/YYYYMMDD_modelname_benchmarkname/
    """
    date_str = datetime.now().strftime("%Y%m%d")
    sanitized_model = model_name.replace("/", "_").replace(":", "_").lower()
    sanitized_bench = benchmark_name.replace("/", "_").replace(":", "_").lower()
    folder_name = f"{date_str}_{sanitized_model}_{sanitized_bench}"
    target_dir = LOGS_DIR / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir
