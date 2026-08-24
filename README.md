# 📊 EvalsBench: Unified Model Evaluation Framework

A standardized, production-grade evaluation and benchmarking framework for local and cloud LLMs on DGX Spark nodes.

---

## ⚡ Quick Start

### 1. Interactive Selection
Run with no arguments to auto-detect the local running model and select from the numbered menu:
```bash
python3 run_evals.py
```

### 2. Autonomous Agent Execution (Skill Invocation)
```bash
python3 -m evalsbench \
  --model nemotron3.5-lightning \
  --endpoint http://localhost:2468/v1 \
  --suite screening \
  --limit 25 \
  --max-connections 8
```

### 3. Custom Benchmark Runs
```bash
python3 -m evalsbench --benchmarks ifeval,humaneval --limit 10
```

---

## 📁 Output Structure

* **Strict Per-Run Logs:** `logs/YYYYMMDD_modelname_benchmarkname/`
  * `report.md`: Formatted Markdown scorecard
  * `results.json`: Machine-readable score summary
  * `*.eval`: Binary Inspect AI trace log
* **Dynamic Model Registry:** `configs/models.yaml` (auto-updated with latest scores and throughput)
* **Second-Brain Synced Vault:** `~/chai/references/models/<model-name>/`

---

## 🏛️ Preset Benchmark Suites

| Suite Name | Included Benchmarks | Primary Focus |
| :--- | :--- | :--- |
| `screening` | IFEval, HumanEval, IFEvalCode, AgentBench | Fast model qualification (~15 min) |
| `coding` | HumanEval, IFEvalCode, MBPP, LiveCodeBench | Functional code generation & syntax |
| `agentic` | AgentBench (OS), PawBench (Harbor), GAIA | Multi-turn tools, terminals, and agents |
| `instruction` | IFEval Strict/Loose, IFEvalCode | Strict negative constraint adherence |
| `full` | All verified benchmarks sequentially | Complete model capability qualification |
