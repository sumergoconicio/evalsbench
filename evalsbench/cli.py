"""
Interactive and argument-driven command line interface for EvalsBench.
"""

import argparse
import sys
from typing import List

from .config import auto_probe_local_endpoint
from .registry import BENCHMARK_REGISTRY, PRESET_SUITES
from .runner import EvalsRunner


def parse_args():
    parser = argparse.ArgumentParser(
        description="EvalsBench: Unified Model Evaluation & Profiling Framework",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", "-m", type=str, default=None, help="Model alias or name (e.g. nemotron3.5-lightning)")
    parser.add_argument("--endpoint", "-e", type=str, default=None, help="OpenAI-compatible base URL (e.g. http://localhost:2468/v1)")
    parser.add_argument("--api-key", "-k", type=str, default=None, help="API key (defaults to dummy for local or reads ~/chai/.env)")
    parser.add_argument("--suite", "-s", type=str, choices=list(PRESET_SUITES.keys()), default=None, help="Preconfigured benchmark suite")
    parser.add_argument("--benchmarks", "-b", type=str, default=None, help="Comma-separated list of individual benchmarks to run")
    parser.add_argument("--limit", "-l", type=int, default=25, help="Number of samples to evaluate per benchmark")
    parser.add_argument("--max-connections", "-c", type=int, default=8, help="Concurrent parallel connection slots")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip 1-sample preflight validation gate")
    parser.add_argument("--no-chai-sync", action="store_true", help="Disable auto-syncing scorecards to ~/chai/references/models/")
    return parser.parse_args()


def interactive_menu(detected_model: str, detected_endpoint: str) -> tuple[str, str, List[str]]:
    print("\n" + "=" * 65)
    print("🎯 EvalsBench: Model Evaluation Suite Selection")
    print("=" * 65)
    print(f"📡 Detected Endpoint: {detected_endpoint}")
    print(f"🤖 Detected Model:    {detected_model}")
    print("-" * 65)
    print("Select evaluation suite:")
    print("  [1] Fast Screening Gauntlet (IFEval, HumanEval, IFEvalCode, AgentBench - ~15 min)")
    print("  [2] Coding & Syntax Gauntlet (HumanEval, IFEvalCode, MBPP, LiveCodeBench)")
    print("  [3] Agentic & OS Gauntlet (AgentBench, PawBench, GAIA)")
    print("  [4] Instruction & Constraint Gauntlet (IFEval Strict, IFEvalCode)")
    print("  [5] Full Master Gauntlet (All Verified Benchmarks Sequentially)")
    print("  [6] Single Benchmark Pick")
    print("  [q] Quit")
    
    choice = input("\nEnter choice [1-6, default=1]: ").strip().lower()
    if choice == "q":
        sys.exit(0)
    
    suite_map = {
        "": "screening",
        "1": "screening",
        "2": "coding",
        "3": "agentic",
        "4": "instruction",
        "5": "full",
    }
    
    if choice in suite_map:
        suite_key = suite_map[choice]
        return detected_model, detected_endpoint, PRESET_SUITES[suite_key]
    elif choice == "6":
        print("\nAvailable individual benchmarks:")
        keys = list(BENCHMARK_REGISTRY.keys())
        for idx, k in enumerate(keys, 1):
            print(f"  [{idx}] {BENCHMARK_REGISTRY[k].name} ({k})")
        pick = input("\nEnter benchmark name or number: ").strip().lower()
        if pick.isdigit() and 1 <= int(pick) <= len(keys):
            return detected_model, detected_endpoint, [keys[int(pick) - 1]]
        elif pick in BENCHMARK_REGISTRY:
            return detected_model, detected_endpoint, [pick]
        else:
            print("Invalid selection. Defaulting to screening.")
            return detected_model, detected_endpoint, PRESET_SUITES["screening"]
    else:
        return detected_model, detected_endpoint, PRESET_SUITES["screening"]


def main():
    args = parse_args()

    endpoint = args.endpoint
    model = args.model

    # Auto-probe if missing
    if not endpoint or not model:
        probed = auto_probe_local_endpoint()
        if probed:
            probed_endpoint, probed_model = probed
            endpoint = endpoint or probed_endpoint
            model = model or probed_model
        else:
            endpoint = endpoint or "http://localhost:2468/v1"
            model = model or "nemotron3.5-lightning"

    # Determine tasks to run
    tasks_to_run: List[str] = []
    if args.benchmarks:
        tasks_to_run = [b.strip().lower() for b in args.benchmarks.split(",") if b.strip()]
    elif args.suite:
        tasks_to_run = PRESET_SUITES.get(args.suite, PRESET_SUITES["screening"])
    else:
        # Launch interactive menu if run without suite or benchmark arguments
        if sys.stdin.isatty():
            model, endpoint, tasks_to_run = interactive_menu(model, endpoint)
        else:
            tasks_to_run = PRESET_SUITES["screening"]

    runner = EvalsRunner(
        model_name=model,
        endpoint_url=endpoint,
        api_key=args.api_key,
        max_connections=args.max_connections,
        chai_sync=not args.no_chai_sync,
    )

    print(f"\n🎯 Running EvalsBench Suite for [{model}] across {len(tasks_to_run)} benchmarks:")
    for t in tasks_to_run:
        print(f"  • {BENCHMARK_REGISTRY.get(t, t).name if t in BENCHMARK_REGISTRY else t}")

    results_summary = {}
    for task_key in tasks_to_run:
        success, scores, duration = runner.run_benchmark(
            task_key=task_key,
            limit=args.limit,
            skip_preflight=args.skip_preflight,
        )
        results_summary[task_key] = {"success": success, "scores": scores, "duration": duration}

    print("\n" + "=" * 65)
    print("📊 ALL BENCHMARKS COMPLETED")
    print("=" * 65)
    for k, v in results_summary.items():
        status = "✅ PASSED" if v["success"] else "❌ FAILED"
        print(f"{k.upper():<15} {status} ({v['duration']:.1f}s)")
        for sk, sv in v["scores"].items():
            print(f"   └─ {sk}: {sv}")


if __name__ == "__main__":
    main()
