# 🏛️ EvalsBench: Agent Operating Manual & Repository Directive

Welcome to **EvalsBench**, the unified LLM evaluation, benchmarking, and profiling framework.

This repository serves as the single source of truth for qualifying, stress-testing, and benchmarking local and cloud models across standardized cognitive, multimodal, and agentic domains.

---

## 🎯 Purpose & Core Capabilities

When an agent or developer asks to *"test this model at this endpoint"*, this repository provides the complete pipeline to:
1. **Auto-Probe Endpoints:** Detect active local inference endpoints (`http://localhost:2468/v1`, ports `1123`, `8000`, `11434`, `12468`) and identify served model aliases.
2. **Execute Standardized Benchmark Suites:** Run curated academic and real-world application benchmarks (`IFEval`, `HumanEval`, `BFCL`, `GAIA`, `NIAH`, `MMMU`, `DocVQA`, `IFEvalCode`, `MBPP`, `LiveCodeBench`, `AgentBench`, `PawBench`, `Luke's Agency Bench`).
3. **Capture Hardware Telemetry:** Measure Speculative Decoding MTP draft acceptance rates ($k=3, 5$), mean acceptance length, and active tokens/sec generation throughput.
4. **Enforce Docker Sandbox Hygiene:** Automatically manage container lifecycles and cleanly remove sandboxes post-test.
5. **Persist Results Across 3 Tiers:**
   - Write raw `.eval` logs and markdown scorecards directly to `logs/YYYYMMDD_modelname_benchmarkname/`.
   - Maintain an append-only historical run ledger in `configs/models.yaml`.
   - Sync formatted scorecards into `~/chai/references/models/<model-name>/` for second-brain reference.
   - Aggregate leaderboard statistics into `dashboard/data.json` for the HTML dashboard (`dashboard/index.html`).

---

## 📁 Repository Layout & Subsystem Responsibilities

```
/home/sumergoconicio/Documents/Code/EvalsBench/
├── AGENTS.md                             # This file: Agent guidelines & repository architecture contract
├── README.md                             # Public overview, quick-start, and developer guide
├── requirements.txt                      # Core dependencies (inspect-ai, inspect-evals, pyyaml, etc.)
├── run_evals.py                          # CLI wrapper
├── skills/
│   └── run_evals/
│       └── SKILL.md                      # Antigravity/ChAI skill for autonomous evaluation execution
├── configs/
│   └── models.yaml                       # Dynamically updated registry of tested models and scores
├── dashboard/                            # Visual leaderboard interface
│   ├── index.html                        # Dashboard HTML frontend
│   ├── app.js                            # Dynamic table rendering and search filter
│   └── data.json                         # Aggregated benchmark scores backing the UI
├── evalsbench/                           # Core Python package
│   ├── __init__.py
│   ├── cli.py                            # Interactive guided wizard & headless argument parsing (also dispatches `validate-spec` / `new-eval` EDS subcommands)
│   ├── config.py                         # Port probing, endpoint resolution, log directory structure
│   ├── doctor.py                         # Auto-healing dependency doctor (installs missing benchmark deps)
│   ├── registry.py                       # Curated benchmark catalog, task parameters, and preset suites
│   ├── runner.py                         # Async Inspect AI runner with 1-sample preflight validation gate (EDS-aware: bounded subprocess, /metrics ingest, `report.eds.md` + `results.eds.json` fan-out)
│   ├── sandboxes.py                      # Docker container management & auto-cleanup handlers
│   ├── shims.py                          # Token-count fallbacks & OpenAI provider shims
│   ├── exporters.py                      # Markdown, JSON, dynamic models.yaml, ChAI vault sync, and the EDS tri-axis scorecard writer
│   ├── hydrator.py                       # Aggregates log metrics into dashboard/data.json
│   ├── progress.py                       # Live streaming terminal progress indicators
│   ├── eds/                              # Evaluation Development System (Layer 1-5: typed models, world, tools, parser, linter, scaffold, solver, scorers, telemetry)
│   │   ├── models.py                     # EpisodeSpec, WorldFixture, Scorecard (safety-gate invariant)
│   │   ├── world.py                      # Copy-on-write WorldState + append-only tool trace
│   │   ├── tools.py                      # @mock_tool decorator + bind_tools (per-sample closure)
│   │   ├── parser.py                     # Markdown-first EDS DSL parser + canonical section roster
│   │   ├── linter.py                     # spec-level semantic lint (tool inventory, oracles, cross-field)
│   │   ├── scaffold.py                   # `new-eval` domain starter
│   │   ├── solver.py                     # eds_agent_solver (per-sample isolation, telemetry=True default)
│   │   ├── telemetry.py                  # TTFT / decode_tps / MTP offline-first collector
│   │   ├── scorers/                      # tri_axis + eds_telemetry @metric
│   │   └── domains/minicorp/             # 16-scenario fixture + 8 mock tools
│   └── adapters/
│       ├── __init__.py
│       ├── inspect_adapter.py            # In-process Inspect AI execution adapter
│       └── lukes_agency_adapter.py       # Luke's Agency Bench adapter (tool dispatch, MTP TPS)
├── docs/                                 # Living user guides (currently `eds_guide.md`)
└── logs/                                 # Standard result directory: YYYYMMDD_modelname_benchmarkname/
```

---

## 🚀 How to Run Evaluations

### 1. Headless / Programmatic Invocation (Recommended for Agents)
```bash
/home/sumergoconicio/.venv/bin/python -m evalsbench \
  --model master-lite \
  --endpoint http://localhost:12468/v1 \
  --suite screening \
  --limit 25 \
  --max-connections 8
```

### 2. Available Preset Suites
* `standard7`: The 7 Canonical Benchmarks (`ifeval`, `humaneval`, `bfcl`, `gaia`, `niah`, `mmmu`, `docvqa`)
* `screening`: IFEval, HumanEval, IFEvalCode, AgentBench (25 samples each, ~15 min total)
* `coding`: HumanEval, IFEvalCode, MBPP, LiveCodeBench
* `agentic`: AgentBench (OS), PawBench (Harbor multi-agent), GAIA, MiniCorp (EDS)
* `instruction`: IFEval (Strict/Loose), IFEvalCode
* `vision`: MMMU (multidisciplinary multimodal reasoning), DocVQA (visual document extraction)
* `full`: All verified benchmarks sequentially

### 3. Difficulty Profile Steering
Pass `--difficulty-profile` (`-d`) to filter benchmark subsets by target cognitive hardness:
* `gatekeeper`: **50% Easy / 40% Medium / 10% Hard** (rapid qualification & regression testing)
* `echelon`: **10% Easy / 50% Medium / 40% Hard** (frontier stress-testing & model discrimination)

Standard 7 Tier Breakdown:
* **GAIA**: Easy = Level 1 (single-step, no files), Medium = Level 2 (multi-step, PDF/text), Hard = Level 3 (multi-modal, sandbox Python/sheets)
* **BFCL**: Easy = Simple, Medium = Parallel/Multiple, Hard = Multi-Turn (stateful loops)
* **NIAH**: Easy = 10k–32k context, Medium = 32k–128k context, Hard = 128k–256k context
* **MMMU**: Easy = Perceptual Recognition, Medium = Applied Domain Logic, Hard = Deep Cognitive Proofs
* **DocVQA**: Easy = Structured Forms, Medium = Multi-Column Tables, Hard = Degraded/Handwritten Scans
* **HumanEval**: Easy = Basic Primitives, Medium = Algorithmic Logic, Hard = Dynamic Programming/Optimization
* **IFEval**: Easy = Single Positive Constraint, Medium = Structural Dual Constraints, Hard = Combinatorial Negative Constraints

### 3. Custom Benchmark Selection
Pass a comma-separated list of benchmark keys:
```bash
/home/sumergoconicio/.venv/bin/python -m evalsbench \
  --model master-lite \
  --endpoint http://localhost:12468/v1 \
  --benchmarks ifeval,humaneval,niah,mmmu,docvqa \
  --limit 10 \
  --max-connections 1
```

### 4. EDS Episode Spec Subcommands
The CLI exposes two EDS-specific subcommands for linting `.eds.md` episode specifications and scaffolding new domain packages directly:
```bash
python -m evalsbench validate-spec evalsbench/eds/specs/
python -m evalsbench new-eval --domain climate-risk
```

---

## 🛠️ How to Add a New Benchmark (Contributor & Agent Workflow)

To add a new benchmark to the framework, follow these 3 steps:

1. **Step 1: Register in `evalsbench/registry.py`**
   Add a `BenchmarkTask` instance to `BENCHMARK_REGISTRY`:
   ```python
   "mybench": BenchmarkTask(
       name="MyBench",
       task_id="inspect_evals/mybench",         # Task path recognized by inspect_ai
       description="Benchmark objective",
       default_limit=25,
       default_max_connections=8,              # Use 1 or 4 for heavy/multimodal models
       docker_required=False,                   # Set True if sandbox execution is needed
       turn_limit=10,                           # Mandatory turn limit
       time_limit=180,                          # Timeout in seconds
       max_tool_output=16384,                   # 16 KB max per tool call
       reasoning_history="none",                # "none" or "all"
       args=[],                                 # Extra arguments (e.g. ["--max-tokens", "4096"])
   )
   ```
   If applicable, add `mybench` to one or more lists in `PRESET_SUITES`.

2. **Step 2: Add Dependencies to `evalsbench/doctor.py`**
   If the benchmark requires specialized packages:
   ```python
   BENCHMARK_DEPENDENCIES["mybench"] = ["package-name>=1.0.0"]
   ```

3. **Step 3: Run Preflight Sanity Check**
   Execute a 1-sample verification ping:
   ```bash
   python -m evalsbench --benchmarks mybench --limit 1 --max-connections 1
   ```

---

## 🏛️ Operating Rules for AI Agents

1. **Log Path Strictness:** Always write logs and results to `logs/YYYYMMDD_modelname_benchmarkname/` relative to repository root.
2. **Preflight Gate:** Before running long 25+ sample batches, always execute a 1-sample preflight check to ensure tokenizer and parser compatibility.
3. **No Code Blocks in Chat Responses:** Unless explicitly requested to analyze code, explain results and progress in plain English and structured Markdown.
4. **Preserve Dynamic Models Registry:** After each benchmark run, verify that `configs/models.yaml` is updated with the latest scores.
5. **Docker Cleanup:** Always ensure Docker sandboxes are cleanly removed after evaluations conclude via `evalsbench.sandboxes.prune_inspect_containers()`.
6. **Mandatory Multi-Turn Safety Guardrails:** All evaluation runs must enforce `--turn-limit` (max 30), `--time-limit` (max 300s), `--max-tool-output 16384` (16 KB max per tool call), `--reasoning-history none`, and `-M responses_api=false`. Never run agentic benchmarks (BFCL, GAIA, AgentBench) uncapped without these safeguards.
7. **Concurrency Throttling on Slow Models:** If an inference server operates at ≤20 tok/s or single-slot batching, strictly enforce `--max-connections 1` to prevent socket starvation and timeouts.
8. **EDS Safety-Gate Invariant (mandatory):** Treat any EDS run with `critical_violations_total > 0` as **functionally zero**, regardless of `composite` or `mean_composite`. The `Scorecard` Pydantic model in `evalsbench/eds/models.py` enforces this invariant: a critical `PolicyRule` violation clamps `functional_score` (and consequently `composite`) to `0.0` *before* the value is surfaced to metric aggregators. Operators must read the dashboard's `EDS Tri-Axis Summary` sidebar widget and treat the safety-gate pass rate as the authoritative success signal for EDS MiniCorp runs.
