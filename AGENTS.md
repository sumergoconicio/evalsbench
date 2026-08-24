# 🏛️ EvalsBench: Agent Operating Manual & Repository Directive

Welcome to **EvalsBench**, the unified LLM evaluation, benchmarking, and profiling framework.

This repository serves as the single source of truth for qualifying, stress-testing, and benchmarking local and cloud models across standardized cognitive domains.

---

## 🎯 Purpose & Core Capabilities

When an agent or developer asks to *"test this model at this endpoint"*, this repository provides the complete pipeline to:
1. **Auto-Probe Endpoints:** Detect active local inference endpoints (`http://localhost:2468/v1`, port `8000`, `11434`, etc.) and identify served model aliases.
2. **Execute Standardized Benchmark Suites:** Run curated academic and real-world application benchmarks (`IFEval`, `HumanEval`, `IFEvalCode`, `AgentBench`, `PawBench`, `GAIA`, `Luke's Agency Bench`).
3. **Capture Hardware Telemetry:** Measure Speculative Decoding MTP draft acceptance rates ($k=3, 5$), mean acceptance length, and active tokens/sec generation throughput.
4. **Enforce Docker Sandbox Hygiene:** Automatically manage container lifecycles and clean up sandboxes post-test.
5. **Persist Results:**
   - Write raw logs and markdown reports directly to `logs/YYYYMMDD_modelname_benchmarkname/`
   - Dynamically maintain model run histories in `configs/models.yaml`
   - Automatically sync formatted summary scorecards into `~/chai/references/models/<model-name>/` for persistent second-brain reference.

---

## 📁 Repository Layout

```
/home/sumergoconicio/Documents/Code/EvalsBench/
├── AGENTS.md                             # This file: Agent guidelines & repository contract
├── README.md                             # User quick-start guide
├── requirements.txt                      # Dependencies (inspect-ai, inspect-evals, inspect-harbor, etc.)
├── skills/
│   └── run_evals/
│       └── SKILL.md                      # Antigravity skill for autonomous evaluation execution
├── configs/
│   └── models.yaml                       # Dynamically updated registry of tested models and scores
├── evalsbench/                           # Core Python package
│   ├── __init__.py
│   ├── cli.py                            # Interactive & headless CLI entrypoint
│   ├── config.py                         # Environment discovery, ports, log directory resolution
│   ├── registry.py                       # Curated benchmark catalog & preset definitions
│   ├── runner.py                         # Async Inspect AI runner with preflight validation
│   ├── sandboxes.py                      # Docker container management & auto-cleanup
│   ├── shims.py                          # Token-count and OpenAI compatibility fallbacks
│   ├── exporters.py                      # Markdown, JSON, dynamic models.yaml, and ChAI sync
│   └── adapters/
│       ├── __init__.py
│       ├── inspect_adapter.py            # In-process Inspect AI execution adapter
│       └── lukes_agency_adapter.py       # Luke's Agency Bench adapter
└── logs/                                 # Standard result directory: YYYYMMDD_modelname_benchmarkname/
```

---

## 🚀 How to Run Evaluations

### 1. Programmatic / Skill Invocation (Recommended for Agents)
```bash
/home/sumergoconicio/.venv/bin/python -m evalsbench \
  --model nemotron3.5-lightning \
  --endpoint http://localhost:2468/v1 \
  --suite screening \
  --limit 25 \
  --max-connections 8
```

### 2. Available Preset Suites
* `screening` (Option A): IFEval, HumanEval, IFEvalCode, AgentBench (25 samples each, ~15 min total)
* `coding`: HumanEval, IFEvalCode, MBPP, LiveCodeBench
* `agentic`: AgentBench (OS), PawBench (Harbor multi-agent), GAIA
* `instruction`: IFEval (Strict/Loose), IFEvalCode
* `agency`: Luke's Agency Bench (tool calling, reasoning loops, MTP TPS)
* `full`: All verified benchmarks sequentially

---

## 🏛️ Operating Rules for AI Agents

1. **Log Path Strictness:** Always write logs and results to `logs/YYYYMMDD_modelname_benchmarkname/` relative to repository root.
2. **Preflight Gate:** Before running long 25+ sample batches, always execute a 1-sample preflight check to ensure tokenizer and parser compatibility.
3. **No Code Blocks in Chat Responses:** Unless explicitly requested to analyze code, explain results and progress in plain English and structured Markdown.
4. **Preserve Dynamic Models Registry:** After each benchmark run, verify that `configs/models.yaml` is updated with the latest scores.
5. **Docker Cleanup:** Always ensure Docker sandboxes are cleanly removed after evaluations conclude.
