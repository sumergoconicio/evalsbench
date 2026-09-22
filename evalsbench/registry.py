"""
Curated benchmark definitions, tasks, and preset suites.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any


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


# Master registry of verified benchmarks with standardized guardrails
BENCHMARK_REGISTRY: Dict[str, BenchmarkTask] = {
    "ifeval": BenchmarkTask(
        name="IFEval",
        task_id="inspect_evals/ifeval",
        description="Instruction following & negative constraints adherence (strict/loose)",
        default_limit=25,
        default_max_connections=8,
        docker_required=False,
        turn_limit=5,
        time_limit=120,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "bfcl": BenchmarkTask(
        name="BFCL",
        task_id="inspect_evals/bfcl",
        description="Berkeley Function Calling Leaderboard tool execution and routing",
        default_limit=25,
        default_max_connections=8,
        docker_required=False,
        turn_limit=25,
        time_limit=180,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "humaneval": BenchmarkTask(
        name="HumanEval",
        task_id="inspect_evals/humaneval",
        description="Python coding completion and functional Pass@1 unit tests",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
        turn_limit=5,
        time_limit=120,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "ifevalcode": BenchmarkTask(
        name="IFEvalCode",
        task_id="inspect_evals/ifevalcode",
        description="Multi-language polyglot coding under strict structural constraints",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
        turn_limit=10,
        time_limit=120,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "agentbench": BenchmarkTask(
        name="AgentBench",
        task_id="inspect_evals/agent_bench_os",
        description="Autonomous multi-turn OS terminal administration inside Docker sandbox",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
        turn_limit=30,
        time_limit=240,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "pawbench": BenchmarkTask(
        name="PawBench",
        task_id="inspect_harbor/agentscope_ai_pawbench",
        description="Multi-agent complex interaction and tool verification in Harbor sandbox",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
        turn_limit=30,
        time_limit=240,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "gaia": BenchmarkTask(
        name="GAIA",
        task_id="inspect_evals/gaia",
        description="General AI assistant multimodal & multi-step complex reasoning",
        default_limit=25,
        default_max_connections=4,
        docker_required=True,
        turn_limit=30,
        time_limit=300,
        max_tool_output=16384,
        reasoning_history="none",
        args=["--max-tokens", "4096"],
    ),
    "mbpp": BenchmarkTask(
        name="MBPP",
        task_id="inspect_evals/mbpp",
        description="Mostly Basic Python Problems coding benchmark",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
        turn_limit=5,
        time_limit=120,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "livecodebench": BenchmarkTask(
        name="LiveCodeBench",
        task_id="inspect_evals/livecodebench",
        description="Contamination-free competitive programming problems",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
        turn_limit=10,
        time_limit=180,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "aider_polyglot": BenchmarkTask(
        name="AiderPolyglot",
        task_id="inspect_evals/aider_polyglot",
        description="Code editing and refactoring across multiple programming languages",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
        turn_limit=30,
        time_limit=300,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "niah": BenchmarkTask(
        name="NIAH",
        task_id="inspect_evals/niah",
        description="Needle In A Haystack long-context retrieval benchmark",
        default_limit=25,
        default_max_connections=8,
        docker_required=False,
        turn_limit=5,
        time_limit=180,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "mmmu": BenchmarkTask(
        name="MMMU",
        task_id="inspect_evals/mmmu_multiple_choice",
        description="Multidisciplinary college-level multimodal reasoning across diagrams and charts",
        default_limit=25,
        default_max_connections=4,
        docker_required=False,
        turn_limit=5,
        time_limit=180,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "docvqa": BenchmarkTask(
        name="DocVQA",
        task_id="inspect_evals/docvqa",
        description="Visual document understanding across forms, receipts, and scans",
        default_limit=25,
        default_max_connections=4,
        docker_required=False,
        turn_limit=5,
        time_limit=180,
        max_tool_output=16384,
        reasoning_history="none",
    ),
    "minicorp": BenchmarkTask(
        name="MiniCorp",
        # Resolved by the runner via the inspect_ai file-path form
        # ``file.py@task_name`` (computable at editor time so the
        # runner shells ``python -m inspect_ai eval <task_id>`` from
        # any cwd). Absolute path is computed below at module load
        # so the registry value remains portable.
        task_id="PLACEHOLDER_MINICORP_TASK_ID",
        description="EDS MiniCorp agency-bench: 16-scenario lookup/scheduling/ticket/currency/restraint suite with the tri_axis scorer",
        default_limit=16,
        default_max_connections=1,
        docker_required=False,
        turn_limit=8,
        time_limit=90,
        max_tool_output=16384,
        reasoning_history="none",
    ),
}

# Curated Preset Suites
PRESET_SUITES: Dict[str, List[str]] = {
    "standard7": ["ifeval", "humaneval", "bfcl", "gaia", "niah", "mmmu", "docvqa"],
    "screening": ["ifeval", "humaneval", "ifevalcode", "agentbench"],
    "coding": ["humaneval", "ifevalcode", "mbpp", "livecodebench"],
    "agentic": ["agentbench", "pawbench", "gaia", "minicorp"],
    "instruction": ["ifeval", "ifevalcode"],
    "vision": ["mmmu", "docvqa"],
    "full": ["ifeval", "humaneval", "ifevalcode", "agentbench", "pawbench", "gaia"],
}

# ---------------------------------------------------------------------------
# MiniCorp EDS task wiring (Wave 3)
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
BENCHMARK_REGISTRY["minicorp"].task_id = MINICORP_TASK_ID

# Difficulty Profiles & Sampling Ratios
DIFFICULTY_PROFILES: Dict[str, Dict[str, float]] = {
    "gatekeeper": {"easy": 0.50, "medium": 0.40, "hard": 0.10},
    "echelon": {"easy": 0.10, "medium": 0.50, "hard": 0.40},
}

# Explicit Category Tier Mapping for the 7 Standard Benchmarks
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


def get_difficulty_task_args(task_key: str, profile: Optional[str]) -> List[str]:
    """Resolves task-specific arguments for a chosen difficulty profile."""
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

    return args

