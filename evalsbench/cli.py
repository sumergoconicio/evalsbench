"""
Interactive guided check-in and argument-driven command line interface for EvalsBench.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

from .config import auto_probe_local_endpoint, load_chai_env
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
    parser.add_argument("--limit", "-l", type=int, default=None, help="Number of samples to evaluate per benchmark")
    parser.add_argument("--max-connections", "-c", type=int, default=None, help="Concurrent parallel connection slots")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip 1-sample preflight validation gate")
    parser.add_argument("--no-chai-sync", action="store_true", help="Disable auto-syncing scorecards to ~/chai/references/models/")
    parser.add_argument("--dashboard", action="store_true", help="Rebuild leaderboard data and display dashboard file path")
    return parser.parse_args()


def guided_checkin(
    default_model: str,
    default_endpoint: str,
) -> Tuple[str, str, str, List[str], int, int, bool]:
    """
    Polite, step-by-step guided check-in asking the user:
    1. Endpoint & Model
    2. API Key
    3. Benchmark Selection
    4. Sample Count (Questions)
    5. Parallel Slots
    6. Preflight Sanity Check
    """
    print("\n" + "=" * 65)
    print("🎯 EvalsBench: Model Evaluation Setup & Check-in")
    print("=" * 65)

    # 1. Endpoint & Model
    print(f"\n[1/6] 📡 Target Endpoint & Model")
    print(f"      Detected Local Endpoint: {default_endpoint}")
    print(f"      Detected Model Name:     {default_model}")
    ep_in = input(f"      Use this endpoint? [Enter=Yes, or type new URL]: ").strip()
    endpoint = ep_in if ep_in else default_endpoint

    if ep_in:
        model_in = input(f"      Enter model name/alias: ").strip()
        model = model_in if model_in else default_model
    else:
        model = default_model

    # 2. API Key
    print(f"\n[2/6] 🔐 API Credentials")
    chai_env = load_chai_env()
    default_key = "dummy"
    if "openrouter.ai" in endpoint:
        default_key = chai_env.get("OPENROUTER_API_KEY", "dummy")
    elif "openai.com" in endpoint:
        default_key = chai_env.get("OPENAI_API_KEY", "dummy")

    key_masked = f"{default_key[:6]}...{default_key[-4:]}" if len(default_key) > 12 else default_key
    key_in = input(f"      API Key [{key_masked}]: ").strip()
    api_key = key_in if key_in else default_key

    # 3. Benchmark Suite Selection
    print(f"\n[3/6] 📋 Benchmark Selection")
    print("      [1] Fast Screening Gauntlet (IFEval, HumanEval, IFEvalCode, AgentBench - ~15 min)")
    print("      [2] Coding & Syntax Gauntlet (HumanEval, IFEvalCode, MBPP, LiveCodeBench)")
    print("      [3] Agentic & OS Gauntlet (AgentBench, PawBench, GAIA)")
    print("      [4] Instruction & Constraint Gauntlet (IFEval Strict, IFEvalCode)")
    print("      [5] Full Master Gauntlet (All Verified Benchmarks Sequentially)")
    print("      [6] Single Benchmark Pick")
    print("      [q] Quit")
    
    suite_choice = input("      Select suite [1-6, default=1]: ").strip().lower()
    if suite_choice == "q":
        sys.exit(0)

    suite_map = {
        "": "screening",
        "1": "screening",
        "2": "coding",
        "3": "agentic",
        "4": "instruction",
        "5": "full",
    }

    if suite_choice in suite_map:
        tasks = PRESET_SUITES[suite_map[suite_choice]]
    elif suite_choice == "6":
        print("\n      Available individual benchmarks:")
        keys = list(BENCHMARK_REGISTRY.keys())
        for idx, k in enumerate(keys, 1):
            print(f"        [{idx}] {BENCHMARK_REGISTRY[k].name} ({k})")
        pick = input("      Enter benchmark name or number: ").strip().lower()
        if pick.isdigit() and 1 <= int(pick) <= len(keys):
            tasks = [keys[int(pick) - 1]]
        elif pick in BENCHMARK_REGISTRY:
            tasks = [pick]
        else:
            tasks = PRESET_SUITES["screening"]
    else:
        tasks = PRESET_SUITES["screening"]

    # 4. Sample Count (Questions)
    print(f"\n[4/6] 🔢 Sample Count (Questions per benchmark)")
    limit_in = input("      Enter sample limit [default=25, or 5/50/100]: ").strip()
    limit = int(limit_in) if limit_in.isdigit() else 25

    # 5. Parallel Slots
    print(f"\n[5/6] ⚡ Concurrent Parallel Slots")
    slots_in = input("      Enter concurrent slots [default=8]: ").strip()
    slots = int(slots_in) if slots_in.isdigit() else 8

    # 6. Preflight Sanity Gate
    print(f"\n[6/6] 🔍 Preflight Sanity Check (1-sample ping before batch)")
    pre_in = input("      Run 1-sample preflight check? [Y/n, default=Y]: ").strip().lower()
    skip_preflight = (pre_in == "n")

    print("\n" + "=" * 65)
    print("🚀 Confirmation Summary:")
    print(f"   • Model:        {model} @ {endpoint}")
    print(f"   • Benchmarks:   {', '.join(tasks)}")
    print(f"   • Samples:      {limit} per benchmark")
    print(f"   • Slots:        {slots} concurrent")
    print(f"   • Preflight:    {'Enabled' if not skip_preflight else 'Skipped'}")
    print("=" * 65 + "\n")

    return model, endpoint, api_key, tasks, limit, slots, skip_preflight


def main():
    args = parse_args()

    endpoint = args.endpoint
    model = args.model
    api_key = args.api_key
    limit = args.limit or 25
    slots = args.max_connections or 8
    if args.dashboard:
        from .hydrator import rebuild_leaderboard_json
        path = rebuild_leaderboard_json()
        dash_html = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"
        print(f"\n📊 [Leaderboard Ready]")
        print(f"Data file:      {path}")
        print(f"Dashboard View: file://{dash_html}")
        return

    skip_preflight = args.skip_preflight

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

    # If run without suite or benchmark arguments and in interactive terminal
    if not args.benchmarks and not args.suite and sys.stdin.isatty():
        model, endpoint, api_key, tasks_to_run, limit, slots, skip_preflight = guided_checkin(model, endpoint)
    else:
        if args.benchmarks:
            tasks_to_run = [b.strip().lower() for b in args.benchmarks.split(",") if b.strip()]
        elif args.suite:
            tasks_to_run = PRESET_SUITES.get(args.suite, PRESET_SUITES["screening"])
        else:
            tasks_to_run = PRESET_SUITES["screening"]

    runner = EvalsRunner(
        model_name=model,
        endpoint_url=endpoint,
        api_key=api_key,
        max_connections=slots,
        chai_sync=not args.no_chai_sync,
    )

    print(f"\n🎯 Launching EvalsBench Suite for [{model}] across {len(tasks_to_run)} benchmarks:")
    for t in tasks_to_run:
        print(f"  • {BENCHMARK_REGISTRY.get(t, t).name if t in BENCHMARK_REGISTRY else t}")

    results_summary = {}
    for task_key in tasks_to_run:
        success, scores, duration = runner.run_benchmark(
            task_key=task_key,
            limit=limit,
            skip_preflight=skip_preflight,
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
