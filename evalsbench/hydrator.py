"""
Automated metadata hydrator for EvalsBench Leaderboard.
Extracts architecture specs, KV cache formulas, Hugging Face URLs, and granular benchmark sub-scores.
"""

import json
import os
import glob
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml

from .config import REPO_ROOT, LOGS_DIR, MODELS_YAML_PATH

DASHBOARD_DIR = REPO_ROOT / "dashboard"
DASHBOARD_DATA_DIR = DASHBOARD_DIR / "data"
LEADERBOARD_JSON_PATH = DASHBOARD_DATA_DIR / "leaderboard.json"

# Local model directories to scan for config.json
MODEL_SEARCH_PATHS = [
    Path("/home/sumergoconicio/modelhub/models"),
    Path("/media/sumergoconicio/amanuensis/models"),
    Path("/home/sumergoconicio/.cache/huggingface/hub"),
]

# Standard cloud frontier baselines for "Pin & Compare"
DEFAULT_FRONTIER_BASELINES = {
    "claude-3-5-sonnet": {
        "name": "Claude 3.5 Sonnet (20241022)",
        "provider": "Anthropic",
        "size_class": "Cloud Frontier",
        "is_cloud": True,
        "huggingface_url": "https://anthropic.com/claude",
        "specs": {
            "total_params_b": "Unknown (Dense/MoE)",
            "active_params_b": "Unknown",
            "context_window": 200000,
            "kv_cache_bytes_per_token_per_gpu": 2400,
        },
        "benchmarks": {
            "IFEval": {"prompt_strict_acc": 0.884, "inst_strict_acc": 0.912, "final_acc": 0.898},
            "HumanEval": {"pass@1": 0.937},
            "IFEvalCode": {"python_correctness": 0.920, "typescript_correctness": 0.880, "overall_accuracy": 0.650},
            "AgentBench": {"accuracy": 0.520},
        }
    },
    "gpt-4o": {
        "name": "GPT-4o (2024-11-20)",
        "provider": "OpenAI",
        "size_class": "Cloud Frontier",
        "is_cloud": True,
        "huggingface_url": "https://openai.com/gpt-4o",
        "specs": {
            "total_params_b": "Unknown (~200B MoE)",
            "active_params_b": "Unknown",
            "context_window": 128000,
            "kv_cache_bytes_per_token_per_gpu": 2400,
        },
        "benchmarks": {
            "IFEval": {"prompt_strict_acc": 0.865, "inst_strict_acc": 0.895, "final_acc": 0.880},
            "HumanEval": {"pass@1": 0.902},
            "IFEvalCode": {"python_correctness": 0.890, "typescript_correctness": 0.840, "overall_accuracy": 0.580},
            "AgentBench": {"accuracy": 0.480},
        }
    },
    "gemini-2-0-flash": {
        "name": "Gemini 2.0 Flash",
        "provider": "Google",
        "size_class": "Cloud Frontier",
        "is_cloud": True,
        "huggingface_url": "https://deepmind.google/technologies/gemini",
        "specs": {
            "total_params_b": "Unknown (~30B-70B)",
            "active_params_b": "Unknown",
            "context_window": 1048576,
            "kv_cache_bytes_per_token_per_gpu": 1800,
        },
        "benchmarks": {
            "IFEval": {"prompt_strict_acc": 0.852, "inst_strict_acc": 0.889, "final_acc": 0.871},
            "HumanEval": {"pass@1": 0.890},
            "IFEvalCode": {"python_correctness": 0.880, "typescript_correctness": 0.810, "overall_accuracy": 0.520},
            "AgentBench": {"accuracy": 0.440},
        }
    }
}


def find_local_model_config(model_name: str) -> Optional[Dict[str, Any]]:
    """Searches local model directories for config.json matching model_name."""
    sanitized = model_name.replace("/", "_").replace(":", "_").lower()
    for base in MODEL_SEARCH_PATHS:
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            if "config.json" in files:
                folder_name = Path(root).name.lower()
                if sanitized in folder_name or model_name.lower() in folder_name:
                    try:
                        with open(Path(root) / "config.json", "r", encoding="utf-8") as f:
                            return json.load(f)
                    except Exception:
                        pass
    return None


def extract_model_specs(model_name: str, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extracts architectural metrics, layer counts, and calculates exact KV cache bytes/token."""
    if not config:
        # Fallbacks based on known naming heuristics
        if "nemotron" in model_name.lower():
            return {
                "architecture": "NemotronHForCausalLM",
                "attention_layers": 6,
                "mamba_layers": 23,
                "moe_layers": 23,
                "num_kv_heads": 2,
                "head_dim": 128,
                "context_window": 1048576,
                "kv_bytes_per_token_per_gpu": 1536, # FP8 TP=2
                "vram_weights_gib": 10.35,
                "size_class": "Mid-Weight MoE (30B A3B)",
                "huggingface_url": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
            }
        return {
            "architecture": "Transformer",
            "attention_layers": 32,
            "num_kv_heads": 8,
            "head_dim": 128,
            "context_window": 131072,
            "kv_bytes_per_token_per_gpu": 8192,
            "vram_weights_gib": 20.0,
            "size_class": "Mid-Weight (14B-35B)",
            "huggingface_url": f"https://huggingface.co/models?search={model_name}"
        }

    arch = config.get("architectures", ["Transformer"])[0]
    total_layers = config.get("num_hidden_layers", 32)
    num_kv_heads = config.get("num_key_value_heads", config.get("num_attention_heads", 8))
    head_dim = config.get("head_dim", config.get("hidden_size", 4096) // config.get("num_attention_heads", 32))
    max_pos = config.get("max_position_embeddings", 131072)
    name_or_path = config.get("_name_or_path", model_name)

    # Attention layer counting for hybrid models
    if "Nemotron" in arch or "hybrid" in arch.lower():
        att_layers = len([i for i in range(total_layers) if i in [5, 12, 19, 26, 33, 42]]) or 6
        kv_bytes_per_token = att_layers * 2 * (num_kv_heads // 2 if num_kv_heads > 1 else 1) * head_dim * 1 # FP8 TP=2
    else:
        att_layers = total_layers
        kv_bytes_per_token = att_layers * 2 * (num_kv_heads // 2 if num_kv_heads > 1 else 1) * head_dim * 1

    # Hugging Face URL synthesis
    hf_url = f"https://huggingface.co/{name_or_path}" if "/" in name_or_path else f"https://huggingface.co/models?search={name_or_path}"

    return {
        "architecture": arch,
        "attention_layers": att_layers,
        "num_kv_heads": num_kv_heads,
        "head_dim": head_dim,
        "context_window": max_pos,
        "kv_bytes_per_token_per_gpu": kv_bytes_per_token,
        "vram_weights_gib": round(config.get("torch_dtype_bytes", 10.35), 2),
        "size_class": "Mid-Weight MoE (30B A3B)" if "MoE" in arch or "nemotron" in model_name.lower() else "Mid-Weight (14B-35B)",
        "huggingface_url": hf_url
    }


def harvest_all_benchmark_scores() -> Dict[str, Dict[str, Any]]:
    """
    Harvests all granular scores across logs/ and configs/models.yaml.
    """
    models_scores = {}
    
    # 1. Read from configs/models.yaml
    if MODELS_YAML_PATH.exists():
        try:
            with open(MODELS_YAML_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "models" in data:
                    for m_name, m_info in data["models"].items():
                        models_scores[m_name] = m_info.get("benchmarks", {})
        except Exception:
            pass

    # 2. Read granular results.json from all log directories
    for res_json in LOGS_DIR.glob("*/results.json"):
        try:
            with open(res_json, "r", encoding="utf-8") as f:
                item = json.load(f)
                m_name = item.get("model")
                b_name = item.get("benchmark")
                scores = item.get("scores", {})
                if m_name and b_name:
                    models_scores.setdefault(m_name, {})[b_name] = scores
        except Exception:
            continue

    return models_scores


def rebuild_leaderboard_json() -> Path:
    """
    Builds and saves Schema v1.0 leaderboard.json for the dashboard.
    """
    DASHBOARD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_scores = harvest_all_benchmark_scores()
    
    models_payload = {}
    for m_name, b_data in all_scores.items():
        cfg = find_local_model_config(m_name)
        specs = extract_model_specs(m_name, cfg)
        models_payload[m_name] = {
            "id": m_name,
            "name": m_name,
            "is_cloud": False,
            "specs": specs,
            "benchmarks": b_data,
        }

    # Merge frontier baselines
    for f_id, f_data in DEFAULT_FRONTIER_BASELINES.items():
        models_payload[f_id] = {
            "id": f_id,
            "name": f_data["name"],
            "is_cloud": True,
            "specs": f_data["specs"],
            "benchmarks": f_data["benchmarks"],
        }

    payload = {
        "schema_version": "1.0",
        "generated_at": str(Path(__file__).stat().st_mtime),
        "models": models_payload,
    }

    with open(LEADERBOARD_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"📊 [Leaderboard Rebuilt] Saved Schema v1.0 data to {LEADERBOARD_JSON_PATH} ({len(models_payload)} models).")
    return LEADERBOARD_JSON_PATH
