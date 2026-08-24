---
name: run_evals
description: Autonomous model evaluation and benchmarking skill. Use whenever the user asks to test, evaluate, benchmark, or profile a local or cloud LLM.
---

# 🚀 Run Evals Skill

Use this skill whenever the user asks to benchmark, qualify, or test an LLM (e.g., *"access this model at this endpoint and run evals for me"*, *"run the fast screening gauntlet"*, or *"evaluate coding on nemotron"*).

---

## 🧭 Workflow for the AI Agent

### Step 1: Detect Endpoint & Model Alias
1. **Check Local Endpoints First:**
   Query `http://localhost:2468/v1/models` (or ports `8000`, `8080`, `11434`):
   ```bash
   curl -s http://localhost:2468/v1/models | jq '.data[].id'
   ```
2. **If Cloud or Custom Endpoint Specified:**
   - For OpenRouter: `https://openrouter.ai/api/v1` (with `OPENROUTER_API_KEY` from `~/chai/.env`)
   - For OpenAI/Custom: Read `OPENAI_API_KEY` from `~/chai/.env`.

---

### Step 2: Present Numbered Menu (If not specified by user)
If the user didn't specify which benchmarks to run, present the standard options:
1. **Fast Screening Gauntlet (Recommended — ~15 min):** IFEval, HumanEval, IFEvalCode, AgentBench (25 samples each)
2. **Coding & Syntax Gauntlet:** HumanEval, IFEvalCode, MBPP, LiveCodeBench
3. **Agentic & OS Gauntlet:** AgentBench (OS), PawBench (Harbor multi-agent), GAIA
4. **Instruction & Constraint Gauntlet:** IFEval Strict/Loose, IFEvalCode
5. **Luke's Agency & Speed Bench:** Tool calling, reasoning loops, and Speculative Decoding MTP tokens/sec
6. **Full Master Gauntlet:** All verified benchmarks sequentially
7. **Single Benchmark Custom Pick:** (e.g. IFEval, HumanEval, or AgentBench only)

---

### Step 3: Execute Evaluation via EvalsBench
Run the evaluation using the virtual environment python:

```bash
/home/sumergoconicio/.venv/bin/python -m evalsbench \
  --model <model-name> \
  --endpoint <endpoint-url> \
  --suite <screening|coding|agentic|instruction|agency|full> \
  --limit 25 \
  --max-connections 8
```

*Note: You can pass `--benchmarks ifeval,humaneval` for custom picks.*

---

### Step 4: Harvest Results & Present Summary
1. The framework stores all logs and generated markdown scorecards in:
   `/home/sumergoconicio/Documents/Code/EvalsBench/logs/YYYYMMDD_modelname_benchmarkname/`
2. It automatically updates `/home/sumergoconicio/Documents/Code/EvalsBench/configs/models.yaml`.
3. It syncs the markdown reports to `/home/sumergoconicio/chai/references/models/<model-name>/`.
4. Read the generated `master_summary.md` and present the complete scorecard to the user with structured metrics (Pass@1, strict accuracy, generation throughput, and speculative acceptance rates).

---

## ⚠️ Safety & Environment Directives
* Always use `--max-connections 8` on DGX Spark nodes.
* Sandboxes (`AgentBench`, `PawBench`, `HumanEval`) run inside Docker containers. The framework automatically cleans up containers post-run.
* Never kill running background services without explicit user confirmation.
