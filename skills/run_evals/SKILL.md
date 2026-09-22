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
   Query `http://localhost:2468/v1/models` (or ports `8000`, `8080`, `1123`, `11434`, `12468`):
   ```bash
   curl -s http://localhost:12468/v1/models | jq '.data[].id'
   ```
2. **If Cloud or Custom Endpoint Specified:**
   - For OpenRouter: `https://openrouter.ai/api/v1` (with `OPENROUTER_API_KEY` from `~/chai/.env`)
   - For OpenAI/Custom: Read `OPENAI_API_KEY` from `~/chai/.env`.

---

### Step 2: Present Numbered Menu (If not specified by user)
If the user didn't specify which benchmarks to run, present the standard options:
1. **The Standard 7 Gauntlet (Recommended — Canonical Battery):** IFEval, HumanEval, BFCL, GAIA, NIAH, MMMU, DocVQA
2. **Fast Screening Gauntlet (~15 min):** IFEval, HumanEval, IFEvalCode, AgentBench (25 samples each)
3. **Coding & Syntax Gauntlet:** HumanEval, IFEvalCode, MBPP, LiveCodeBench
4. **Agentic & OS Gauntlet:** AgentBench (OS), PawBench (Harbor multi-agent), GAIA, MiniCorp (EDS, 16 scenarios, `--max-connections 1`)
5. **Instruction & Constraint Gauntlet:** IFEval Strict/Loose, IFEvalCode
6. **Vision & Multimodal Gauntlet:** MMMU, DocVQA
7. **Luke's Agency & Speed Bench:** Tool calling, reasoning loops, and Speculative Decoding MTP tokens/sec (use `--benchmarks minicorp` for the canonical EDS port)
8. **Full Master Gauntlet:** All verified benchmarks sequentially
9. **Single Benchmark Custom Pick:** (e.g. IFEval, HumanEval, NIAH, MMMU, or DocVQA)

> EDS-specific tasks (currently `minicorp`) are selected via the standard `--benchmarks` flag or as a member of the `agentic` suite. Selectable via `--benchmarks minicorp --limit 16 --max-connections 1`. See `docs/eds_guide.md` for the full authoring & safety-gate contract.

---

### Step 3: Execute Evaluation via EvalsBench
Run the evaluation using the virtual environment python:

```bash
/home/sumergoconicio/.venv/bin/python -m evalsbench \
  --model <model-name> \
  --endpoint <endpoint-url> \
  --suite <standard7|screening|coding|agentic|instruction|vision|full> \
  --difficulty-profile <gatekeeper|echelon> \
  --limit 25 \
  --max-connections 8
```

*Note: The valid `--suite` values (verified by argparse) are exactly: `standard7`, `screening`, `coding`, `agentic`, `instruction`, `vision`, `full`. There is **no** `--suite agency`; for the EDS MiniCorp scenarios use `--benchmarks minicorp --limit 16 --max-connections 1` or `--suite agentic`. Choose `--difficulty-profile gatekeeper` (50% easy, 40% medium, 10% hard) for triage/qualification, or `--difficulty-profile echelon` (10% easy, 50% medium, 40% hard) for frontier stress-testing. You can also pass `--benchmarks ifeval,humaneval,bfcl,gaia,niah,mmmu,docvqa` for custom picks.*

---

### Step 4: Harvest Results & Present Summary
1. The framework stores all logs and generated markdown scorecards in:
   `/home/sumergoconicio/Documents/Code/EvalsBench/logs/YYYYMMDD_modelname_benchmarkname/`
2. It automatically updates `/home/sumergoconicio/Documents/Code/EvalsBench/configs/models.yaml`.
3. It syncs the markdown reports to `/home/sumergoconicio/chai/references/models/<model-name>/`.
4. Read the generated `master_summary.md` and present the complete scorecard to the user with structured metrics (Pass@1, strict accuracy, generation throughput, and speculative acceptance rates).

---

## ⚠️ Safety & Environment Directives
* Always use `--max-connections 8` on DGX Spark nodes (or `--max-connections 1` on low-throughput / single-slot local models).
* Enforce multi-turn safety guardrails: `--turn-limit 30`, `--time-limit 180`, `--max-tool-output 16384`, `--reasoning-history none`, and `-M responses_api=false`. Never run agentic or tool benchmarks uncapped.
* Sandboxes (`AgentBench`, `PawBench`, `HumanEval`, `GAIA`) run inside Docker containers. The framework automatically cleans up containers post-run.
* Never kill running background services without explicit user confirmation.
