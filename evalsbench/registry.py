"""
Curated benchmark definitions, tasks, and preset suites.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class BenchmarkTask:
    name: str
    task_id: str
    description: str
    default_limit: int = 25
    default_max_connections: int = 8
    docker_required: bool = False
    args: List[str] = field(default_factory=list)


# Master registry of verified benchmarks
BENCHMARK_REGISTRY: Dict[str, BenchmarkTask] = {
    "ifeval": BenchmarkTask(
        name="IFEval",
        task_id="inspect_evals/ifeval",
        description="Instruction following & negative constraints adherence (strict/loose)",
        default_limit=25,
        default_max_connections=8,
        docker_required=False,
    ),
    "humaneval": BenchmarkTask(
        name="HumanEval",
        task_id="inspect_evals/humaneval",
        description="Python coding completion and functional Pass@1 unit tests",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
    ),
    "ifevalcode": BenchmarkTask(
        name="IFEvalCode",
        task_id="inspect_evals/ifevalcode",
        description="Multi-language polyglot coding under strict structural constraints",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
    ),
    "agentbench": BenchmarkTask(
        name="AgentBench",
        task_id="inspect_evals/agent_bench_os",
        description="Autonomous multi-turn OS terminal administration inside Docker sandbox",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
    ),
    "pawbench": BenchmarkTask(
        name="PawBench",
        task_id="inspect_harbor/agentscope_ai_pawbench",
        description="Multi-agent complex interaction and tool verification in Harbor sandbox",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
    ),
    "gaia": BenchmarkTask(
        name="GAIA",
        task_id="inspect_evals/gaia",
        description="General AI assistant multimodal & multi-step complex reasoning",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
    ),
    "mbpp": BenchmarkTask(
        name="MBPP",
        task_id="inspect_evals/mbpp",
        description="Mostly Basic Python Problems coding benchmark",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
    ),
    "livecodebench": BenchmarkTask(
        name="LiveCodeBench",
        task_id="inspect_evals/livecodebench",
        description="Contamination-free competitive programming problems",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
    ),
    "aider_polyglot": BenchmarkTask(
        name="AiderPolyglot",
        task_id="inspect_evals/aider_polyglot",
        description="Code editing and refactoring across multiple programming languages",
        default_limit=25,
        default_max_connections=8,
        docker_required=True,
    ),
}

# Curated Preset Suites
PRESET_SUITES: Dict[str, List[str]] = {
    "screening": ["ifeval", "humaneval", "ifevalcode", "agentbench"],
    "coding": ["humaneval", "ifevalcode", "mbpp", "livecodebench"],
    "agentic": ["agentbench", "pawbench", "gaia"],
    "instruction": ["ifeval", "ifevalcode"],
    "full": ["ifeval", "humaneval", "ifevalcode", "agentbench", "pawbench", "gaia"],
}
