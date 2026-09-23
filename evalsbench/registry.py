"""
Curated benchmark definitions, tasks, and preset suites.

V2 contract (PRD §6.2): the catalog lives declaratively in
``configs/benchmarks.yaml`` (single source of truth) and is loaded
defensively:

* Resolution anchors on the absolute repository root
  (``REPO_ROOT / "configs" / "benchmarks.yaml"``) so imports work from
  any working directory.
* If the YAML file is absent or malformed, the module falls back
  cleanly to the in-code default registry below — it never raises
  ``FileNotFoundError`` and never leaves the registry empty.
* Tasks without difficulty subset definitions fall through
  unstratified: :func:`get_difficulty_task_args` returns an empty
  arg list and emits an informational notice.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

import yaml

from .config import REPO_ROOT


BENCHMARKS_YAML_PATH: Path = REPO_ROOT / "configs" / "benchmarks.yaml"


@dataclass
class BenchmarkTask:
    name: str
    task_id: str
    description: str
    default_limit: int = 25
    default_max_connections: int = 8
    docker_required: bool = False
    turn_limit: int = 30
    time_limit: int = 180
    max_tool_output: int = 16384
    reasoning_history: str = "none"
    args: List[str] = field(default_factory=list)
    # --- V2 declarative-schema fields -------------------------------------
    scoring_mode: str = "deferred"          # "immediate" | "deferred"
    is_custom: bool = False                 # True for `custom-*` EDS benchmarks
    category: str = ""                      # instruction | coding | agency | ...
    multimodal: bool = False                # True when the benchmark needs image/document inputs
    source: str = ""                        # provenance string (upstream lib or EDS module)
    max_samples: Optional[int] = None       # dataset ceiling for clamping


# ---------------------------------------------------------------------------
# In-code fallback registry (used only when benchmarks.yaml is absent
# or malformed). Mirrors the V2 YAML schema.
# ---------------------------------------------------------------------------
_DEFAULT_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "ifeval": dict(
        name="IFEval", task_id="inspect_evals/ifeval",
        description="Strict and loose negative constraint adherence, JSON schema delimiters, and formatting rules.",
        category="instruction", scoring_mode="immediate", default_limit=25,
        default_max_connections=8, docker_required=False, turn_limit=5, time_limit=120,
    ),
    "bfcl": dict(
        name="BFCL", task_id="inspect_evals/bfcl",
        description="Berkeley Function Calling Leaderboard for deterministic single, parallel, and multi-turn tool dispatch.",
        category="tool_use", scoring_mode="deferred", default_limit=25,
        default_max_connections=8, docker_required=False, turn_limit=25, time_limit=180,
    ),
    "humaneval": dict(
        name="HumanEval", task_id="inspect_evals/humaneval",
        description="Functional Python coding primitives and pass@1 automated unit test validation in Docker.",
        category="coding", scoring_mode="deferred", default_limit=25,
        default_max_connections=8, docker_required=True, turn_limit=5, time_limit=120,
        max_samples=164,
    ),
    "ifevalcode": dict(
        name="IFEvalCode", task_id="inspect_evals/ifevalcode",
        description="Multi-language polyglot coding under strict structural constraints",
        category="coding", scoring_mode="deferred", default_limit=25,
        default_max_connections=8, docker_required=True, turn_limit=10, time_limit=120,
    ),
    "agentbench": dict(
        name="AgentBench", task_id="inspect_evals/agent_bench_os",
        description="Autonomous multi-turn OS terminal administration inside Docker sandbox",
        category="agency", scoring_mode="deferred", default_limit=25,
        default_max_connections=8, docker_required=True, turn_limit=30, time_limit=240,
    ),
    "pawbench": dict(
        name="PawBench", task_id="inspect_harbor/agentscope_ai_pawbench",
        description="Multi-agent complex interaction and tool verification in Harbor sandbox",
        category="agency", scoring_mode="deferred", default_limit=25,
        default_max_connections=8, docker_required=True, turn_limit=30, time_limit=240,
    ),
    "gaia": dict(
        name="GAIA", task_id="inspect_evals/gaia",
        description="Multi-modal, multi-step general AI assistant reasoning and tool chaining in Docker.",
        category="multimodal", scoring_mode="deferred", default_limit=25,
        default_max_connections=4, docker_required=True, turn_limit=30, time_limit=300,
        args=["--max-tokens", "4096"],
    ),
    "mbpp": dict(
        name="MBPP", task_id="inspect_evals/mbpp",
        description="Mostly Basic Python Problems coding benchmark",
        category="coding", scoring_mode="deferred", default_limit=25,
        default_max_connections=8, docker_required=True, turn_limit=5, time_limit=120,
    ),
    "livecodebench": dict(
        name="LiveCodeBench", task_id="inspect_evals/livecodebench",
        description="Contamination-free competitive programming problems",
        category="coding", scoring_mode="deferred", default_limit=25,
        default_max_connections=8, docker_required=True, turn_limit=10, time_limit=180,
    ),
    "aider_polyglot": dict(
        name="AiderPolyglot", task_id="inspect_evals/aider_polyglot",
        description="Code editing and refactoring across multiple programming languages",
        category="coding", scoring_mode="deferred", default_limit=25,
        default_max_connections=8, docker_required=True, turn_limit=30, time_limit=300,
    ),
    "niah": dict(
        name="NIAH", task_id="inspect_evals/niah",
        description="Needle In A Haystack long-context retrieval benchmark",
        category="long_context", scoring_mode="deferred", default_limit=25,
        default_max_connections=8, docker_required=False, turn_limit=5, time_limit=180,
    ),
    "mmmu": dict(
        name="MMMU", task_id="inspect_evals/mmmu_multiple_choice",
        description="Multidisciplinary college-level multimodal reasoning across diagrams and charts",
        category="multimodal", scoring_mode="deferred", default_limit=25,
        default_max_connections=4, docker_required=False, turn_limit=5, time_limit=180,
    ),
    "docvqa": dict(
        name="DocVQA", task_id="inspect_evals/docvqa",
        description="Visual document understanding and key-value extraction across forms, invoices, and dense tables.",
        category="document", scoring_mode="immediate", default_limit=25,
        default_max_connections=4, docker_required=False, turn_limit=5, time_limit=180,
    ),
    "terminal_bench_2": dict(
        name="TerminalBench2", task_id="inspect_harbor/terminal_bench_2",
        description="Autonomous real-world Linux system administration, compilation, and troubleshooting inside Docker.",
        category="sysadmin", scoring_mode="deferred", default_limit=25,
        default_max_connections=4, docker_required=True, turn_limit=30, time_limit=600,
    ),
    "writingbench": dict(
        name="WritingBench", task_id="inspect_evals/writingbench",
        description="Multi-domain long-form prose evaluated by Anthropic Claude Haiku judge (claude-haiku-4-5-20251001).",
        category="writing", scoring_mode="deferred", default_limit=25,
        default_max_connections=4, docker_required=False, turn_limit=5, time_limit=600,
    ),
    "assistant_bench": dict(
        name="AssistantBench", task_id="inspect_evals/assistant_bench_web_search_zero_shot",
        description="Real-world digital assistant tasks requiring web search, information extraction, and constraint resolution.",
        category="assistant", scoring_mode="deferred", default_limit=25,
        default_max_connections=4, docker_required=False, turn_limit=15, time_limit=600,
        max_samples=214,
    ),
    "deepsearchqa": dict(
        name="DeepSearchQA", task_id="inspect_harbor/kgmon_deepsearchqa",
        description="Google DeepMind 900-prompt multi-hop deep research and factual information retrieval.",
        category="research", scoring_mode="deferred", default_limit=25,
        default_max_connections=4, docker_required=True, turn_limit=30, time_limit=600,
        max_samples=900,
    ),
    "custom-minicorp": dict(
        name="Custom-MiniCorp", task_id="eds:minicorp",
        description="16-scenario stateful agency bench testing lookup, ticketing, calendar booking, and zero-tolerance safety traps.",
        category="agency", scoring_mode="immediate", is_custom=True,
        source="evalsbench.eds.domains.minicorp.tasks.py@minicorp",
        default_limit=16, default_max_connections=1, docker_required=False,
        turn_limit=8, time_limit=90, max_samples=16,
    ),
    "minicorp": dict(
        name="MiniCorp", task_id="eds:minicorp",
        description="EDS MiniCorp agency-bench: 16-scenario lookup/scheduling/ticket/currency/restraint suite with the tri_axis scorer",
        category="agency", scoring_mode="immediate", is_custom=True,
        default_limit=16, default_max_connections=1, docker_required=False,
        turn_limit=8, time_limit=90, max_samples=16,
    ),
}

_DEFAULT_PRESETS: Dict[str, List[str]] = {
    # V2 3D-matrix suites
    "core": ["ifeval", "bfcl", "humaneval", "custom-minicorp", "writingbench"],
    "agent": ["custom-minicorp", "terminal_bench_2", "gaia", "assistant_bench"],
    "knowledge": ["writingbench", "assistant_bench", "deepsearchqa"],
    "all": [
        "ifeval", "bfcl", "humaneval", "custom-minicorp", "terminal_bench_2",
        "writingbench", "assistant_bench", "gaia", "docvqa", "deepsearchqa",
    ],
    # Legacy suites (preserved for backward compatibility)
    "standard7": ["ifeval", "humaneval", "bfcl", "gaia", "niah", "mmmu", "docvqa"],
    "screening": ["ifeval", "humaneval", "ifevalcode", "agentbench"],
    "coding": ["humaneval", "ifevalcode", "mbpp", "livecodebench"],
    "agentic": ["agentbench", "pawbench", "gaia", "minicorp"],
    "instruction": ["ifeval", "ifevalcode"],
    "vision": ["mmmu", "docvqa"],
    "full": ["ifeval", "humaneval", "ifevalcode", "agentbench", "pawbench", "gaia"],
}

_DEFAULT_PROFILES: Dict[str, Dict[str, Optional[float]]] = {
    "gatekeeper": {"easy": 0.50, "medium": 0.40, "hard": 0.10},
    "echelon": {"easy": 0.10, "medium": 0.50, "hard": 0.40},
    "full": {"easy": None, "medium": None, "hard": None},
}


def _coerce_task(key: str, spec: Dict[str, Any]) -> BenchmarkTask:
    """Build a :class:`BenchmarkTask` from a YAML/defaul spec mapping."""
    known = {
        "name", "task_id", "description", "default_limit",
        "default_max_connections", "docker_required", "turn_limit",
        "time_limit", "max_tool_output", "reasoning_history", "args",
        "scoring_mode", "is_custom", "category", "multimodal", "source",
        "max_samples",
    }
    filtered = {k: v for k, v in spec.items() if k in known}
    # ``args`` may be None (empty in YAML) — normalize to a list.
    if filtered.get("args") is None:
        filtered["args"] = []
    return BenchmarkTask(**filtered)


def _load_yaml_registry() -> Optional[Dict[str, Any]]:
    """Defensively load ``configs/benchmarks.yaml``.

    Returns ``None`` (never raises) when the file is missing, unreadable,
    or structurally malformed, signalling fallback to the in-code defaults.
    """
    try:
        with open(BENCHMARKS_YAML_PATH, "r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp)
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("benchmarks"), dict):
        return None
    return data


def _build_registry() -> Dict[str, BenchmarkTask]:
    """Merge the YAML catalog over the in-code fallback registry."""
    registry: Dict[str, BenchmarkTask] = {
        key: _coerce_task(key, spec) for key, spec in _DEFAULT_BENCHMARKS.items()
    }
    data = _load_yaml_registry()
    if data is None:
        return registry

    for key, spec in data["benchmarks"].items():
        if not isinstance(spec, dict):
            continue
        merged = dict(_DEFAULT_BENCHMARKS.get(key, {}))
        merged.update(spec)
        merged.setdefault("name", key)
        registry[key] = _coerce_task(key, merged)

    return registry


def _build_presets() -> Dict[str, List[str]]:
    """Merge YAML preset suites over the in-code fallback presets."""
    presets: Dict[str, List[str]] = dict(_DEFAULT_PRESETS)
    data = _load_yaml_registry()
    if data is None:
        return presets
    yaml_presets = data.get("presets")
    if isinstance(yaml_presets, dict):
        for name, spec in yaml_presets.items():
            if isinstance(spec, dict) and isinstance(spec.get("benchmarks"), list):
                presets[name] = [str(b) for b in spec["benchmarks"] if str(b) in _all_known_keys(presets, data)]
            elif isinstance(spec, list):
                presets[name] = [str(b) for b in spec]
    return presets


def _all_known_keys(
    presets: Dict[str, List[str]],
    data: Dict[str, Any],
) -> set:
    """Union of every benchmark key referenced anywhere in the config."""
    keys: set = set(_DEFAULT_BENCHMARKS.keys())
    yaml_benchmarks = data.get("benchmarks")
    if isinstance(yaml_benchmarks, dict):
        keys.update(yaml_benchmarks.keys())
    for members in presets.values():
        keys.update(members)
    return keys


def _build_profiles() -> Dict[str, Dict[str, Optional[float]]]:
    """Merge YAML hardness profiles over the in-code fallback profiles."""
    profiles: Dict[str, Dict[str, Optional[float]]] = dict(_DEFAULT_PROFILES)
    data = _load_yaml_registry()
    if data is None:
        return profiles
    yaml_profiles = data.get("profiles")
    if isinstance(yaml_profiles, dict):
        for name, spec in yaml_profiles.items():
            if isinstance(spec, dict):
                profiles[name] = {
                    "easy": spec.get("easy"),
                    "medium": spec.get("medium"),
                    "hard": spec.get("hard"),
                }
    return profiles


def _load_scales() -> Dict[str, Dict[str, Any]]:
    """Expose scale flags (short/long/complete) from YAML with fallback."""
    default_scales: Dict[str, Dict[str, Any]] = {
        "short": {"limit": 20},
        "long": {"limit": 100},
        "complete": {"limit": None},
    }
    data = _load_yaml_registry()
    if data is None:
        return default_scales
    yaml_scales = data.get("scales")
    if isinstance(yaml_scales, dict):
        for name, spec in yaml_scales.items():
            if isinstance(spec, dict):
                default_scales[name] = {"limit": spec.get("limit")}
    return default_scales


BENCHMARK_REGISTRY: Dict[str, BenchmarkTask] = _build_registry()
PRESET_SUITES: Dict[str, List[str]] = _build_presets()
DIFFICULTY_PROFILES: Dict[str, Dict[str, Optional[float]]] = _build_profiles()
SCALES: Dict[str, Dict[str, Any]] = _load_scales()

# ---------------------------------------------------------------------------
# MiniCorp EDS task wiring
# ---------------------------------------------------------------------------
#: Absolute path to the MiniCorp tasks module. inspect_ai resolves a
#: file-path task spec (``<absolute.py>@<task_name>``) by importing the
#: file in its parent directory; using an absolute path means the
#: runner can spawn ``python -m inspect_ai eval <task_id>`` from any
#: cwd without breaking path resolution.
_MINICORP_TASKS_FILE: Path = (
    Path(__file__).resolve().parent
    / "eds"
    / "domains"
    / "minicorp"
    / "tasks.py"
)
#: Canonical ``<task_id>`` for the MiniCorp suite used by the runner.
#: Format matches the inspect_ai ``file.py@task`` selector accepted
#: by ``inspect_ai eval``. The ``minicorp`` suffix corresponds to the
#: ``@task`` factory function in :mod:`evalsbench.eds.domains.minicorp.tasks`.
MINICORP_TASK_ID: str = f"{_MINICORP_TASKS_FILE.as_posix()}@minicorp"

#: Resolve the ``eds:minicorp`` sentinel used by the YAML catalog and
#: the in-code fallback alike.
for _key, _task in BENCHMARK_REGISTRY.items():
    if _task.task_id == "eds:minicorp":
        _task.task_id = MINICORP_TASK_ID
        _task.is_custom = True

# Explicit Category Tier Mapping for the Standard Benchmarks
STANDARD_TIER_MAPPING: Dict[str, Dict[str, str]] = {
    "gaia": {
        "easy": "Level 1: Single-step tool lookup, direct web search, no file attachments",
        "medium": "Level 2: Multi-step tool chaining with PDF/text extraction",
        "hard": "Level 3: Multi-modal agent execution, Python sandbox & spreadsheet calculation",
    },
    "bfcl": {
        "easy": "Simple: Single deterministic function call with direct parameter match",
        "medium": "Parallel & Multiple: Independent parallel calls or complex overlapping schemas",
        "hard": "Multi-Turn: Stateful interactive tool execution loops with state tracking",
    },
    "niah": {
        "easy": "Short Context (10k-32k tokens, boundary needle placement)",
        "medium": "Mid Context (32k-128k tokens, middle-depth needle placement)",
        "hard": "Deep Context (128k-256k tokens, multi-needle / adversarial placement)",
    },
    "mmmu": {
        "easy": "Perceptual Recognition: Single-image OCR, clear chart and diagram reading",
        "medium": "Applied Domain Logic: Engineering schematics and standard college science problems",
        "hard": "Deep Cognitive Proofs: Clinical diagnostics, advanced geometry and proof graphs",
    },
    "docvqa": {
        "easy": "Structured Forms: High-contrast invoices and single key-value extractions",
        "medium": "Dense Multi-Column: Multi-column reports and structured data tables",
        "hard": "Degraded & Nested: Low-contrast scans, handwriting and irregular layouts",
    },
    "humaneval": {
        "easy": "Basic Primitives: String/list manipulation and elementary arithmetic",
        "medium": "Algorithmic Logic: Sorting, filtering, dictionary logic and recursion",
        "hard": "Complex Optimization: Dynamic programming, graph logic and edge cases",
    },
    "ifeval": {
        "easy": "Single Positive Constraint: Word count floor or single keyword inclusion",
        "medium": "Structural Dual Constraints: Valid JSON combined with formatting rules",
        "hard": "Combinatorial Constraints: Strict negative constraints and exact paragraph bounds",
    },
}

#: Tasks with Inspect AI difficulty subset definitions (stratifiable).
_STRATIFIABLE_TASKS: Dict[str, bool] = {"gaia": True, "niah": True}


def is_stratifiable(task_key: str) -> bool:
    """Whether a task exposes difficulty subsets for profile steering."""
    return _STRATIFIABLE_TASKS.get(task_key.lower(), False)


def get_difficulty_task_args(task_key: str, profile: Optional[str]) -> List[str]:
    """Resolves task-specific arguments for a chosen difficulty profile.

    Stratification fall-through (PRD §6.2): tasks without Inspect AI
    difficulty subset definitions return an empty arg list and emit an
    informational notice (only when a profile was actually requested);
    they then execute unstratified rather than raising.
    """
    if not profile or profile not in DIFFICULTY_PROFILES:
        return []

    task_k = task_key.lower()
    args: List[str] = []

    if task_k == "gaia":
        if profile == "gatekeeper":
            args.extend(["-T", "subset=2023_level1"])
        elif profile == "echelon":
            args.extend(["-T", "subset=2023_level2"])
    elif task_k == "niah":
        if profile == "gatekeeper":
            args.extend(["-T", "min_context=10000", "-T", "max_context=32000"])
        elif profile == "echelon":
            args.extend(["-T", "min_context=64000", "-T", "max_context=256000"])
    else:
        print(
            f"Note: '{task_key}' has no difficulty subsets in Inspect AI; "
            f"running unstratified (profile '{profile}' ignored for this task)."
        )

    return args


def filter_tasks_by_modality(
    task_keys: List[str],
    modality: Optional[str],
) -> Tuple[List[str], List[str]]:
    """Filter benchmark keys by input modality (PRD catalog attribute).

    Args:
        task_keys: Candidate benchmark keys (from a suite or explicit picks).
        modality: ``"multimodal"`` keeps only image/document benchmarks,
            ``"text"`` keeps only text-only benchmarks, ``None`` keeps all.

    Returns:
        Tuple of ``(kept, dropped)`` key lists. Unknown keys are kept
        (they surface later as registry lookup errors, not silently
        dropped by the modality filter).
    """
    if modality not in ("multimodal", "text"):
        return list(task_keys), []
    want_multimodal = modality == "multimodal"
    kept: List[str] = []
    dropped: List[str] = []
    for key in task_keys:
        task = BENCHMARK_REGISTRY.get(key)
        if task is None:
            kept.append(key)  # unknown keys are not this filter's problem
            continue
        if bool(task.multimodal) == want_multimodal:
            kept.append(key)
        else:
            dropped.append(key)
    return kept, dropped
