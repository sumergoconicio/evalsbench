"""
Auto-healing dependency doctor for EvalsBench.
Automatically detects and installs missing packages for specific evaluation suites.
"""

import importlib.util
import subprocess
import sys
from typing import Dict, List, Optional

# Mapping of benchmark keys / imports to required pip packages
BENCHMARK_DEPENDENCIES: Dict[str, List[str]] = {
    "ifeval": ["instruction_following_eval@git+https://github.com/josejg/instruction_following_eval.git"],
    "ifevalcode": ["instruction_following_eval@git+https://github.com/josejg/instruction_following_eval.git", "sacrebleu", "datasketch"],
    "pawbench": ["inspect-harbor>=0.7.4", "harbor>=0.22.0"],
    "ade_bench": ["inspect-harbor>=0.7.4", "harbor>=0.22.0"],
    "humaneval": ["inspect-evals>=0.18.0"],
    "agentbench": ["inspect-evals>=0.18.0"],
    "gaia": ["inspect-evals>=0.18.0"],
    "mbpp": ["inspect-evals>=0.18.0"],
    "livecodebench": ["inspect-evals>=0.18.0"],
    "aider_polyglot": ["inspect-evals>=0.18.0"],
    "niah": ["inspect-evals>=0.18.0"],
    "mmmu": ["inspect-evals>=0.18.0"],
    "docvqa": ["inspect-evals>=0.18.0"],
}

MODULE_CHECK_MAP: Dict[str, str] = {
    "instruction_following_eval": "instruction_following_eval",
    "inspect-harbor": "inspect_harbor",
    "harbor": "harbor",
    "inspect-evals": "inspect_evals",
    "sacrebleu": "sacrebleu",
    "datasketch": "datasketch",
    "pyyaml": "yaml",
    "openai": "openai",
}


def is_module_installed(module_name: str) -> bool:
    """Checks if a python module is available in the current environment."""
    return importlib.util.find_spec(module_name) is not None


def ensure_dependencies_for_task(task_key: str) -> bool:
    """
    Checks and auto-installs missing dependencies required for a specific benchmark.
    Returns True if all dependencies are satisfied.
    """
    deps = BENCHMARK_DEPENDENCIES.get(task_key.lower(), [])
    if not deps:
        return True

    missing_pkgs = []
    for pkg in deps:
        base_name = pkg.split("@")[0].split(">=")[0].split("==")[0].strip()
        mod_name = MODULE_CHECK_MAP.get(base_name, base_name.replace("-", "_"))
        if not is_module_installed(mod_name):
            missing_pkgs.append(pkg)

    if not missing_pkgs:
        return True

    print(f"🩺 [Auto-Doctor] Detected {len(missing_pkgs)} missing dependencies for '{task_key}': {missing_pkgs}")
    print("⏳ Auto-installing missing packages into environment...")

    try:
        cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + missing_pkgs
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("✅ [Auto-Doctor] Missing dependencies installed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ [Auto-Doctor] Failed to auto-install dependencies: {e.stderr}")
        return False
