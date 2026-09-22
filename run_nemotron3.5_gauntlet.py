import os
import sys
import time
import subprocess
import json

ENV_VARS = os.environ.copy()
ENV_VARS["OPENAI_BASE_URL"] = "http://localhost:2468/v1"
ENV_VARS["OPENAI_API_KEY"] = "dummy"

OUTPUT_DIR = "/home/sumergoconicio/chai/references/models/nemotron3.5-lightning"
os.makedirs(OUTPUT_DIR, exist_ok=True)

INSPECT_BIN = "/home/sumergoconicio/.venv/bin/inspect"

BENCHMARKS = [
    {"name": "IFEval", "task": "inspect_evals/ifeval", "args": []},
    {"name": "HumanEval", "task": "inspect_evals/humaneval", "args": []},
    {"name": "IFEvalCode", "task": "inspect_evals/ifevalcode", "args": []},
    {"name": "AgentBench", "task": "inspect_evals/agent_bench_os", "args": []},
    {"name": "PawBench", "task": "inspect_harbor/agentscope_ai_pawbench", "args": []},
    {"name": "GAIA", "task": "inspect_evals/gaia", "args": []}
]

def clean_docker():
    subprocess.run("docker ps -a --filter status=exited -q | xargs -r docker rm -f >/dev/null 2>&1", shell=True)
    subprocess.run("docker image prune -f >/dev/null 2>&1", shell=True)

def generate_markdown_report(name, output, dur, log_file):
    report_path = os.path.join(OUTPUT_DIR, f"{name.lower()}_results.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"# 📊 Benchmark Results: {name}\n\n")
        f.write(f"* **Model**: `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (alias `nemotron3.5-lightning`)\n")
        f.write(f"* **Endpoint**: `http://localhost:2468/v1`\n")
        f.write(f"* **Samples Evaluated**: 25 (Option A)\n")
        f.write(f"* **Parallel Slots**: 8 Concurrent Connections\n")
        f.write(f"* **Execution Time**: {dur:.1f} seconds\n")
        f.write(f"* **Log Directory**: `{log_file}`\n")
        f.write(f"* **Timestamp**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## Output Summary\n```text\n{output}\n```\n")
    print(f"📝 Saved report to {report_path}")

def run_bench(b, limit=25):
    task_log_dir = os.path.join(OUTPUT_DIR, b["name"].lower())
    os.makedirs(task_log_dir, exist_ok=True)
    
    cmd = [
        INSPECT_BIN, "eval", b["task"],
        "--model", "openai/nemotron3.5-lightning",
        "--limit", str(limit),
        "--sample-shuffle", "42",
        "--max-connections", "8",
        "--log-dir", task_log_dir
    ] + b["args"]
    
    print("\n" + "="*65)
    print(f"🚀 Starting Benchmark: {b['name']} ({limit} samples, 8 concurrent slots)")
    print(f"Command: {' '.join(cmd)}")
    print("="*65)
    
    start_t = time.time()
    res = subprocess.run(cmd, env=ENV_VARS, capture_output=True, text=True)
    dur = time.time() - start_t
    
    clean_docker()
    
    output_text = res.stdout if res.stdout else res.stderr
    print(output_text)
    
    if res.returncode == 0:
        print(f"✅ {b['name']} Completed in {dur:.1f}s")
        generate_markdown_report(b["name"], output_text, dur, task_log_dir)
        return True, output_text, dur
    else:
        err = res.stdout + "\n" + res.stderr
        print(f"❌ {b['name']} Failed (Exit Code {res.returncode})")
        generate_markdown_report(b["name"], err, dur, task_log_dir)
        return False, err, dur

if __name__ == "__main__":
    target_bench = sys.argv[1] if len(sys.argv) > 1 else None
    
    benches_to_run = BENCHMARKS
    if target_bench:
        benches_to_run = [b for b in BENCHMARKS if b["name"].lower() == target_bench.lower()]
        if not benches_to_run:
            print(f"Unknown benchmark: {target_bench}")
            sys.exit(1)
            
    print(f"🎯 Launching Nemotron 3.5 Lightning Gauntlet Suite ({len(benches_to_run)} benchmarks)")
    results = {}
    for b in benches_to_run:
        success, output, dur = run_bench(b, limit=25)
        results[b["name"]] = {"success": success, "duration": dur}
    
    master_summary_path = os.path.join(OUTPUT_DIR, "master_gauntlet_summary.md")
    with open(master_summary_path, 'w', encoding='utf-8') as f:
        f.write("# 🏆 Nemotron 3.5 Lightning Master Evaluation Gauntlet Summary\n\n")
        f.write(f"* **Model**: `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (TP=2, FP8 KV Cache, MTP k=3)\n")
        f.write(f"* **Concurrency**: 8 Parallel Slots (`--max-connections 8`)\n")
        f.write(f"* **Samples per Benchmark**: 25 (Option A Randomized)\n")
        f.write(f"* **Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("| Benchmark | Status | Duration |\n")
        f.write("|---|---|---|\n")
        for name, r in results.items():
            status = "PASSED" if r["success"] else "FAILED"
            f.write(f"| **{name}** | {status} | {r['duration']:.1f}s |\n")
            
    print("\n" + "="*65)
    print("📊 MASTER GAUNTLET EXECUTION COMPLETED")
    print(f"Master summary saved to: {master_summary_path}")
    print("="*65)
