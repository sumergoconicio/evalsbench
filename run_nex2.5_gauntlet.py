import os
import sys
import time
import subprocess
import json
import glob
from pathlib import Path
from inspect_ai.log import read_eval_log
import yaml

ENV_VARS = os.environ.copy()
ENV_VARS["OPENAI_BASE_URL"] = "http://127.0.0.1:12468/v1"
ENV_VARS["OPENAI_API_KEY"] = "dummy"

OUTPUT_DIR = Path("/home/sumergoconicio/chai/references/models/nex-n2.5-mini")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

INSPECT_BIN = "/home/sumergoconicio/.venv/bin/inspect"
EVALSBENCH_CONFIGS_DIR = Path("/home/sumergoconicio/Documents/Code/EvalsBench/configs")
MODELS_YAML_PATH = EVALSBENCH_CONFIGS_DIR / "models.yaml"

BENCHMARKS = [
    {
        "key": "ifeval",
        "name": "IFEval",
        "task": "inspect_evals/ifeval",
        "model": "openai/frontier-agent",
        "profile": "frontier-agent",
        "limit": 100,
        "max_connections": 8,
        "args": ["-M", "responses_api=false"],
    },
    {
        "key": "humaneval",
        "name": "HumanEval",
        "task": "inspect_evals/humaneval",
        "model": "openai/frontier-agent",
        "profile": "frontier-agent",
        "limit": 100,
        "max_connections": 8,
        "args": ["-M", "responses_api=false"],
    },
    {
        "key": "bfcl_agent",
        "name": "BFCL (Agent Profile)",
        "task": "inspect_evals/bfcl",
        "model": "openai/frontier-agent",
        "profile": "frontier-agent",
        "limit": 100,
        "max_connections": 8,
        "args": ["-M", "responses_api=false"],
    },
    {
        "key": "bfcl_tool",
        "name": "BFCL (Tool Profile)",
        "task": "inspect_evals/bfcl",
        "model": "openai/frontier-tool",
        "profile": "frontier-tool",
        "limit": 100,
        "max_connections": 8,
        "args": ["-M", "responses_api=false"],
    },
    {
        "key": "gaia",
        "name": "GAIA",
        "task": "inspect_evals/gaia",
        "model": "openai/frontier-agent",
        "profile": "frontier-agent",
        "limit": 25,
        "max_connections": 4,
        "args": ["-M", "responses_api=false"],
    },
]

def clean_docker_sandboxes():
    try:
        subprocess.run(
            "docker ps -a --filter status=exited -q | xargs -r docker rm -f >/dev/null 2>&1",
            shell=True,
            timeout=30,
        )
    except Exception as e:
        print(f"Warning cleaning docker sandboxes: {e}")

def update_models_yaml(benchmark_key: str, profile: str, scores: dict, duration_s: float):
    try:
        current_data = {}
        if MODELS_YAML_PATH.exists():
            with open(MODELS_YAML_PATH, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    current_data = loaded
        models_dict = current_data.setdefault("models", {})
        model_entry = models_dict.setdefault("Nex-N2.5-mini-NVFP4", {
            "endpoint": "http://127.0.0.1:12468/v1",
            "served_profiles": ["frontier-agent", "frontier-tool"],
            "benchmarks": {},
        })
        model_entry.setdefault("benchmarks", {})[benchmark_key] = {
            "profile": profile,
            "scores": scores,
            "duration_seconds": round(duration_s, 2),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(MODELS_YAML_PATH, "w", encoding="utf-8") as f:
            yaml.dump(current_data, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        print(f"Warning: Failed to update {MODELS_YAML_PATH}: {e}")

def parse_and_report(bench: dict, raw_output: str, duration_s: float, task_log_dir: Path) -> dict:
    eval_files = sorted(task_log_dir.glob("*.eval"), key=lambda p: p.stat().st_mtime, reverse=True)
    eval_log_path = eval_files[0] if eval_files else None
    
    metrics = {}
    tokens_info = {}
    failures = []
    
    if eval_log_path:
        try:
            log_data = read_eval_log(str(eval_log_path))
            if log_data.results and log_data.results.scores:
                for s in log_data.results.scores:
                    for m_name, m_val in s.metrics.items():
                        metrics[f"{s.name}_{m_name}"] = round(m_val.value, 4) if isinstance(m_val.value, float) else m_val.value
            
            # Extract token stats
            if log_data.stats and log_data.stats.model_usage:
                for m_id, u in log_data.stats.model_usage.items():
                    tokens_info["input_tokens"] = u.input_tokens
                    tokens_info["output_tokens"] = u.output_tokens
                    tokens_info["total_tokens"] = u.total_tokens

            # Extract failed samples
            if log_data.samples:
                for sample in log_data.samples:
                    sample_score = 0
                    if sample.scores:
                        for sc_name, sc_obj in sample.scores.items():
                            val = sc_obj.value if hasattr(sc_obj, 'value') else 0
                            if isinstance(val, (int, float)):
                                sample_score = max(sample_score, val)
                            elif str(val).lower() in ["c", "correct", "true", "1"]:
                                sample_score = 1
                    if sample_score == 0:
                        failures.append({
                            "id": getattr(sample, "id", "unknown"),
                            "input": str(getattr(sample, "input", ""))[:300],
                            "target": str(getattr(sample, "target", ""))[:200],
                            "error": str(getattr(sample, "error", "")) if getattr(sample, "error", None) else None,
                        })
        except Exception as e:
            print(f"Warning reading eval log {eval_log_path}: {e}")

    # Generate Markdown Report
    report_file = OUTPUT_DIR / f"{bench['key']}_results.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# 📊 Benchmark Results: {bench['name']}\n\n")
        f.write(f"* **Model**: `Nex-N2.5-mini-NVFP4`\n")
        f.write(f"* **ModelProxy Profile**: `{bench['profile']}`\n")
        f.write(f"* **Task ID**: `{bench['task']}`\n")
        f.write(f"* **Samples Evaluated**: {bench['limit']}\n")
        f.write(f"* **Parallel Slots**: {bench['max_connections']}\n")
        f.write(f"* **Duration**: {duration_s:.1f}s (~{duration_s/60:.1f} min)\n")
        f.write(f"* **Timestamp**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## 🎯 Scores & Metrics\n\n")
        if metrics:
            f.write("| Metric | Score |\n|---|---|\n")
            for k, v in metrics.items():
                f.write(f"| `{k}` | **{v}** |\n")
        else:
            f.write("*(Metrics extracted from raw log)*\n")
        
        if tokens_info:
            f.write(f"\n**Token Usage**: Input: {tokens_info.get('input_tokens', 0):,} | Output: {tokens_info.get('output_tokens', 0):,} | Total: {tokens_info.get('total_tokens', 0):,}\n")
        
        if failures:
            f.write(f"\n## ⚠️ Failure Breakdown ({len(failures)} failed samples)\n\n")
            f.write(f"| Sample ID | Target | Error / Failure Note |\n|---|---|---|\n")
            for fail in failures[:15]:
                err_text = fail['error'] if fail['error'] else "Assertion or constraint mismatch"
                f.write(f"| `{fail['id']}` | `{fail['target']}` | {err_text} |\n")
            if len(failures) > 15:
                f.write(f"\n*(Truncated: {len(failures) - 15} additional failures omitted)*\n")
                
        f.write(f"\n## 📝 Raw Inspect Console Output\n\n```text\n{raw_output}\n```\n")
        
    print(f"📝 Saved {bench['key']} report to {report_file}")
    update_models_yaml(bench["key"], bench["profile"], metrics, duration_s)
    return {"metrics": metrics, "tokens": tokens_info, "failures_count": len(failures), "duration": duration_s}

def run_bench(bench: dict) -> dict:
    task_log_dir = OUTPUT_DIR / bench["key"]
    task_log_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        INSPECT_BIN, "eval", bench["task"],
        "--model", bench["model"],
        "--limit", str(bench["limit"]),
        "--sample-shuffle", "42",
        "--max-connections", str(bench["max_connections"]),
        "--turn-limit", str(bench.get("turn_limit", 30)),
        "--time-limit", str(bench.get("time_limit", 180)),
        "--max-tool-output", str(bench.get("max_tool_output", 16384)),
        "--reasoning-history", bench.get("reasoning_history", "none"),
        "--log-dir", str(task_log_dir),
    ] + bench["args"]
    
    print("\n" + "=" * 70)
    print(f"🚀 Running {bench['name']} ({bench['limit']} samples, {bench['max_connections']} slots, profile: {bench['profile']})")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 70)
    
    start_t = time.time()
    res = subprocess.run(cmd, env=ENV_VARS, capture_output=True, text=True)
    dur = time.time() - start_t
    
    clean_docker_sandboxes()
    output_text = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
    print(output_text[-1200:] if len(output_text) > 1200 else output_text)
    
    if res.returncode == 0:
        print(f"✅ {bench['name']} completed in {dur:.1f}s.")
    else:
        print(f"❌ {bench['name']} exited with code {res.returncode}.")
        
    return parse_and_report(bench, output_text, dur, task_log_dir)

def generate_master_summary(all_results: dict):
    summary_file = OUTPUT_DIR / "master_eval_summary.md"
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write("# 🏆 Nex-N2.5-mini NVFP4: Master Evaluation Gauntlet Summary\n\n")
        f.write(f"* **Model Checkpoint**: `ProCreations/Nex-N2.5-mini-NVFP4`\n")
        f.write(f"* **Serving Infrastructure**: Dual-node DGX Spark cluster (Ray TP=2, Port 1234)\n")
        f.write(f"* **Proxy Router**: ModelProxy `:12468` (`frontier-agent` & `frontier-tool` profiles)\n")
        f.write(f"* **Execution Framework**: Inspect AI (`inspect_ai` 0.3.260)\n")
        f.write(f"* **Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## 1. Executive Performance Matrix\n\n")
        f.write("| Benchmark | Profile | Samples | Primary Metric | Score | Duration | Failures |\n")
        f.write("|---|---|---:|---|---:|---:|---:|\n")
        
        for key, res in all_results.items():
            b_info = next((b for b in BENCHMARKS if b["key"] == key), None)
            name = b_info["name"] if b_info else key
            profile = b_info["profile"] if b_info else "unknown"
            limit = b_info["limit"] if b_info else "-"
            
            # Find primary metric
            metrics = res.get("metrics", {})
            dur = res.get("duration", 0)
            fails = res.get("failures_count", 0)
            
            primary_name = "Score"
            primary_val = "-"
            for m_k, m_v in metrics.items():
                if "accuracy" in m_k or "pass_at_1" in m_k:
                    primary_name = m_k
                    primary_val = f"{m_v:.3f}" if isinstance(m_v, float) else str(m_v)
                    break
            if primary_val == "-" and metrics:
                first_k = list(metrics.keys())[0]
                primary_name = first_k
                primary_val = str(metrics[first_k])
                
            f.write(f"| **{name}** | `{profile}` | {limit} | `{primary_name}` | **{primary_val}** | {dur:.1f}s | {fails} |\n")
            
        f.write("\n---\n\n## 2. Head-to-Head: BFCL Agent vs. BFCL Tool Profile\n\n")
        f.write("Comparing ModelProxy routing performance for function calling across agentic multi-turn vs direct tool dispatch:\n\n")
        agent_bfcl = all_results.get("bfcl_agent", {}).get("metrics", {})
        tool_bfcl = all_results.get("bfcl_tool", {}).get("metrics", {})
        
        f.write("| Metric | `frontier-agent` | `frontier-tool` | Delta |\n|---|---:|---:|---:|\n")
        all_bfcl_keys = sorted(set(list(agent_bfcl.keys()) + list(tool_bfcl.keys())))
        for k in all_bfcl_keys:
            ag_val = agent_bfcl.get(k, 0)
            tl_val = tool_bfcl.get(k, 0)
            delta = tl_val - ag_val if isinstance(ag_val, (int, float)) and isinstance(tl_val, (int, float)) else "N/A"
            delta_str = f"{delta:+.3f}" if isinstance(delta, float) else str(delta)
            f.write(f"| `{k}` | {ag_val} | {tl_val} | **{delta_str}** |\n")

        f.write("\n---\n\n## 3. Benchmark Detailed Scorecards\n\n")
        for key, res in all_results.items():
            b_info = next((b for b in BENCHMARKS if b["key"] == key), None)
            f.write(f"### {b_info['name'] if b_info else key}\n\n")
            f.write(f"- Detailed report: [`{key}_results.md`](file:///home/sumergoconicio/chai/references/models/nex-n2.5-mini/{key}_results.md)\n")
            f.write(f"- Duration: {res.get('duration', 0):.1f}s\n")
            f.write(f"- Metrics:\n")
            for mk, mv in res.get("metrics", {}).items():
                f.write(f"  - `{mk}`: **{mv}**\n")
            f.write("\n")
            
    print(f"🏆 Master summary generated at {summary_file}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    to_run = BENCHMARKS
    if target:
        to_run = [b for b in BENCHMARKS if b["key"] == target.lower()]
        if not to_run:
            print(f"Unknown target: {target}. Available: {[b['key'] for b in BENCHMARKS]}")
            sys.exit(1)
            
    print(f"🎯 Starting Evaluation Gauntlet: {len(to_run)} benchmark runs")
    all_results = {}
    for bench in to_run:
        res = run_bench(bench)
        all_results[bench["key"]] = res
        
    if not target or len(to_run) > 1:
        generate_master_summary(all_results)
    print("\n🎉 Evaluation Gauntlet Complete!")
