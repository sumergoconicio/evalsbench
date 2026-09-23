# 📊 EvalsBench: Unified LLM Evaluation, Benchmarking & Profiling Framework

A production-grade, highly extensible framework for evaluating, stress-testing, and profiling local and cloud Large Language Models (LLMs) across standardized academic, agentic, multimodal, and coding benchmarks.

Originally engineered for high-throughput inference environments (NVIDIA DGX Spark clusters, vLLM, SGLang, and llama.cpp), **EvalsBench** provides strict multi-turn safety guardrails, automatic Docker container sandboxing, self-healing dependency resolution, and dynamic model history tracking.

---

## 🌟 Key Capabilities

* **The 3D Operational Matrix:** Orthogonally compose functional preset suites (`--suite`), cognitive hardness profiles (`--difficulty-profile`), and sample scale flags (`--short` / `--long` / `--complete`) for any qualification or stress-test scenario.
* **Declarative Benchmark Registry:** `configs/benchmarks.yaml` is the single source of truth for the catalog, presets, profiles, and scales — loaded defensively with an in-code fallback. Powering both the CLI wizard and AI facilitation skill.
* **Real-Time Telemetry Engine:** A dual-row live terminal monitor showing per-question TTFT (prefill latency), decode tok/s, prompt token volume with KV-cache hit percentage, speculative decoding (MTP) draft acceptance, and multi-stream slot saturation.
* **Scoring Mode Transparency:** Every benchmark declares `immediate` (live running accuracy) or `deferred` (batch-graded at run conclusion via Docker test runners, AST replay, or LLM judges) so a 100%-progress screen with no accuracy figure is never a surprise.
* **Direct Cloud Provider Routing:** Provider-prefixed model strings (`google/*`, `deepseek/*`, `anthropic/*`, `openai/*`, `openrouter/*`) route natively through Inspect AI's vendors with credentials from `~/chai/.env` — no LiteLLM proxy overhead.
* **Preflight Sanity Gate:** Automatically executes a 1-sample ping before initiating long multi-sample batches, catching socket, tokenizer, and schema mismatches in seconds.
* **Hardened Multi-Turn Guardrails:** Eliminates runaway agent loops and context crashes by enforcing per-task `--turn-limit`, `--time-limit`, `--max-tool-output` truncation (16 KB), and per-turn `--max-tokens` caps — plus a watchdog timer with process-group kill escalation against orphaned CUDA/Docker subprocesses.
* **Auto-Healing Dependency Doctor:** Detects benchmark-specific dependencies on the fly (e.g. `instruction_following_eval`, `inspect-harbor`, `sacrebleu`) and auto-installs them without manual intervention.
* **Polite Docker Container Hygiene:** Automatically spins up isolated container sandboxes for coding (`HumanEval`, `MBPP`) and agentic execution (`GAIA`, `AgentBench`, `PawBench`), ensuring all containers are cleanly pruned post-run.
* **Multi-Format Export & Dashboards:** Stores structured per-sample logs in `logs/`, updates an append-only registry in `configs/models.yaml` (including decode TPS / TTFT telemetry), and generates an interactive HTML leaderboard in `dashboard/index.html`.

---

## 📁 Architecture & Directory Structure

```
EvalsBench/
├── AGENTS.md                 # Operating directive and rules for AI coding agents
├── README.md                 # Project documentation and open-source guide
├── requirements.txt          # Core dependencies (inspect-ai, inspect-evals, pyyaml, etc.)
├── run_evals.py              # CLI launcher shortcut
├── configs/
│   ├── benchmarks.yaml       # Declarative benchmark registry (single source of truth: presets, profiles, scales, catalog)
│   └── models.yaml           # Historical database of all tested models, scores, and telemetry
├── dashboard/
│   ├── index.html            # Interactive visual leaderboard dashboard
│   ├── app.js                # Frontend data hydration and rendering
│   └── data.json             # Aggregated benchmark scores backing the UI
├── evalsbench/               # Core Python evaluation package
│   ├── __init__.py
│   ├── cli.py                # Command-line interface with interactive guided wizard
│   ├── config.py             # Endpoint probing, port discovery, and path resolvers
│   ├── doctor.py             # Auto-healing dependency doctor
│   ├── exporters.py          # Markdown scorecards, JSON exports, and vault sync
│   ├── hydrator.py           # Dashboard data aggregation engine
│   ├── progress.py           # LiveTelemetryMonitor (dual-row TTY + milestone transcript rendering)
│   ├── registry.py           # Defensive YAML registry loader + difficulty stratification
│   ├── router.py             # Direct cloud provider routing (vendor-native, ~/chai/.env keys)
│   ├── runner.py             # Async execution engine with preflight, watchdog, and live telemetry hooks
│   ├── sandboxes.py          # Docker container lifecycle management
│   ├── shims.py              # Token-count and OpenAI compatibility patches
│   ├── eds/                  # Evaluation Development System (Layer 1-5: typed models, world, tools, parser, linter, scaffold, solver, scorers, telemetry)
│   │   ├── __init__.py
│   │   ├── models.py         # EpisodeSpec, WorldFixture, Scorecard (safety-gate invariant)
│   │   ├── world.py          # Copy-on-write WorldState + append-only tool trace
│   │   ├── tools.py          # @mock_tool decorator + bind_tools (per-sample closure)
│   │   ├── parser.py         # Markdown-first EDS DSL parser + canonical section roster
│   │   ├── linter.py         # spec-level semantic lint (tool inventory, oracles, cross-field)
│   │   ├── scaffold.py       # `new-eval` domain starter
│   │   ├── solver.py         # eds_agent_solver (per-sample isolation, telemetry=True default)
│   │   ├── telemetry.py      # TTFT / decode_tps / MTP offline-first collector
│   │   ├── scorers/          # tri_axis + eds_telemetry @metric
│   │   │   ├── __init__.py
│   │   │   ├── tri_axis.py
│   │   │   └── telemetry_scorer.py
│   │   ├── domains/
│   │   │   └── minicorp/     # 16-scenario fixture + 8 mock tools
│   │   └── specs/            # .eds.md episode specifications
│   │       └── examples/
│   └── adapters/             # Benchmark harness adapters (Inspect AI, Luke's Agency)
├── docs/                     # Living user guides (currently `eds_guide.md`)
│   └── eds_guide.md          # Full EDS architecture (5 layers, episode contract, provenance tiers, trap taxonomy, end-to-end domain-creation tutorial)
└── logs/                     # Auto-created per-run artifacts: YYYYMMDD_model_benchmark/
```

---

## 🚀 Quick Start

### 1. Installation

```bash
git clone https://github.com/your-org/EvalsBench.git
cd EvalsBench

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Interactive Guided Mode
Run with no arguments to probe local endpoints (vLLM, llama.cpp, SGLang, Ollama) and configure through an interactive terminal wizard:

```bash
python3 -m evalsbench
```

### 3. Headless / Programmatic Invocation
Run automated batches directly against any OpenAI-compatible API endpoint — or straight to a cloud vendor via provider-prefixed model strings:

```bash
# 3D Matrix: core suite × gatekeeper profile × short scale (~10-12 min)
python3 -m evalsbench \
  --model my-model \
  --endpoint http://localhost:8000/v1 \
  --suite core \
  --difficulty-profile gatekeeper \
  --short \
  --max-connections 8

# Exhaustive frontier stress test on a cloud vendor (credentials from ~/chai/.env)
python3 -m evalsbench --model google/gemini-2.5-flash --suite all -d echelon --complete

# Run custom benchmark picks
python3 -m evalsbench \
  --model master-lite \
  --endpoint http://localhost:12468/v1 \
  --benchmarks ifeval,humaneval,niah \
  --limit 10 \
  --max-connections 1
```

**Sample Scale Flags (Dimension 3):** `--short` (20 questions/benchmark, ~10-12 min), `--long` (100 questions/benchmark, ~45-60 min), or `--complete` (exhaustive dataset, 2-6 hours). Explicit `--limit N` overrides the scale flags. Dataset ceilings are clamped automatically for bounded benchmarks (e.g. `custom-minicorp` caps at 16).

**Modality Filter:** pass `--modality multimodal` (vision/document benchmarks only, currently `gaia` and `docvqa`) or `--modality text` (text-only benchmarks only) to narrow any suite or `--benchmarks` selection. Use `--modality text` for vision-incapable models.

### 4. Viewing the Visual Leaderboard
Rebuild the aggregated scores and view the interactive dashboard:

```bash
python3 -m evalsbench --dashboard
```
Open `dashboard/index.html` in your browser.

---

## 🏛️ Preset Evaluation Suites

V2 functional presets (Dimension 1 of the 3D Operational Matrix):

| Suite Name | Included Benchmarks | Primary Target |
| :--- | :--- | :--- |
| `core` | `ifeval`, `bfcl`, `humaneval`, `custom-minicorp`, `writingbench` | Everyday baseline: instruction following, tool routing, code, agency, prose |
| `agent` | `custom-minicorp`, `terminal_bench_2`, `gaia`, `assistant_bench` | Autonomous agentic execution, stateful tool loops, Docker sysadmin, multimodal |
| `knowledge` | `writingbench`, `assistant_bench`, `deepsearchqa` | Long-form prose, open-web digital assistant, multi-hop deep research |
| `all` | `ifeval`, `bfcl`, `humaneval`, `custom-minicorp`, `terminal_bench_2`, `writingbench`, `assistant_bench`, `gaia`, `docvqa`, `deepsearchqa` | Complete 10-benchmark evaluation gauntlet |

Legacy suites (still available):

| Suite Name | Included Benchmarks | Primary Target |
| :--- | :--- | :--- |
| `standard7` | `ifeval`, `humaneval`, `bfcl`, `gaia`, `niah`, `mmmu`, `docvqa` | The Canonical 7-Benchmark Comprehensive Battery |
| `screening` | `ifeval`, `humaneval`, `ifevalcode`, `agentbench` | Rapid model qualification (~15 min) |
| `coding` | `humaneval`, `ifevalcode`, `mbpp`, `livecodebench` | Multi-language code completion & unit tests |
| `agentic` | `agentbench`, `pawbench`, `gaia`, `minicorp` | Complex tool calling, OS shell, & multi-turn reasoning |
| `instruction` | `ifeval`, `ifevalcode` | Negative constraint & structural instruction adherence |
| `vision` | `mmmu`, `docvqa` | Multimodal diagrams, charts, and document analysis |
| `full` | Sequential run across all primary verified benchmarks | Exhaustive model capability profiling |

---

## 🎯 Difficulty Profiles: Gatekeeper vs. Echelon

EvalsBench introduces formal difficulty profiling to balance rapid operational screening with high-entropy frontier stress-testing:

| Profile Name | Sampling Ratio (Easy / Medium / Hard) | Operational Focus |
| :--- | :--- | :--- |
| `gatekeeper` | **50% Easy / 40% Medium / 10% Hard** | Fast qualification & regression gate; filters broken parsers without wall-clock exhaustion |
| `echelon` | **10% Easy / 50% Medium / 40% Hard** | Frontier stress-testing & model bakeoffs; concentrates samples where state-of-the-art models separate |
| `full` | Natural dataset distribution | Unfiltered, unstratified runs across all available difficulty tiers |

```bash
# Run the 7 Standard Evals under the Gatekeeper profile
python3 -m evalsbench --suite standard7 --difficulty-profile gatekeeper --limit 25

# Run under the Echelon profile for rigorous frontier testing
python3 -m evalsbench --suite standard7 --difficulty-profile echelon --limit 25
```

### Explicit Tier Mapping for the 7 Standard Benchmarks

| Benchmark | Easy Tier | Medium Tier | Hard Tier |
| :--- | :--- | :--- | :--- |
| **GAIA** | **Level 1**: Single-step tool lookup, direct web search, no file attachments | **Level 2**: Multi-step tool chaining with PDF/text extraction | **Level 3**: Multi-modal agent execution, Python sandbox & spreadsheet calculation |
| **BFCL** | **Simple**: Single deterministic function call with direct parameter match | **Parallel & Multiple**: Independent parallel calls or complex overlapping schemas | **Multi-Turn**: Stateful interactive tool execution loops with state tracking |
| **NIAH** | **Short Context**: 10k–32k tokens, boundary needle placement | **Mid Context**: 32k–128k tokens, middle-depth needle placement | **Deep Context**: 128k–256k tokens, multi-needle / adversarial placement |
| **MMMU** | **Perceptual Recognition**: Single-image OCR, clear chart and diagram reading | **Applied Domain Logic**: Engineering schematics and college science problems | **Deep Cognitive Proofs**: Clinical diagnostics, advanced geometry and proof graphs |
| **DocVQA** | **Structured Forms**: High-contrast invoices and single key-value extractions | **Dense Multi-Column**: Multi-column reports and structured data tables | **Degraded & Nested**: Low-contrast scans, handwriting and irregular layouts |
| **HumanEval** | **Basic Primitives**: String/list manipulation and elementary arithmetic | **Algorithmic Logic**: Sorting, filtering, dictionary logic and recursion | **Complex Optimization**: Dynamic programming, graph logic and edge cases |
| **IFEval** | **Single Positive**: Word count floor or single keyword inclusion | **Structural Dual**: Valid JSON combined with formatting rules | **Combinatorial**: Strict negative constraints and exact paragraph bounds |

---

## 📋 Supported Benchmark Catalog

| Key | Benchmark Name | Task Identifier | Environment | Focus |
| :--- | :--- | :--- | :--- | :--- |
| `ifeval` | IFEval | `inspect_evals/ifeval` | In-Process | Negative instruction following |
| `humaneval`| HumanEval | `inspect_evals/humaneval` | Docker | Python Pass@1 unit tests |
| `bfcl` | BFCL | `inspect_evals/bfcl` | In-Process | Berkeley Function Calling Leaderboard |
| `gaia` | GAIA | `inspect_evals/gaia` | Docker | Multi-turn agentic web/tool reasoning |
| `niah` | NIAH | `inspect_evals/niah` | In-Process | Needle In A Haystack long-context retrieval |
| `mmmu` | MMMU | `inspect_evals/mmmu_multiple_choice` | In-Process | Multidisciplinary multimodal college reasoning |
| `docvqa` | DocVQA | `inspect_evals/docvqa` | In-Process | Visual document understanding & layout QA |
| `ifevalcode`| IFEvalCode | `inspect_evals/ifevalcode` | Docker | Polyglot code under strict constraints |
| `mbpp` | MBPP | `inspect_evals/mbpp` | Docker | Mostly Basic Python Problems |
| `livecodebench` | LiveCodeBench | `inspect_evals/livecodebench` | Docker | Contamination-free competitive coding |
| `agentbench`| AgentBench (OS) | `inspect_evals/agent_bench_os` | Docker | Terminal bash command administration |
| `pawbench` | PawBench | `inspect_harbor/agentscope_ai_pawbench` | Docker | Harbor multi-agent interaction |
| `aider_polyglot` | Aider Polyglot | `inspect_evals/aider_polyglot` | Docker | Code refactoring & editing across languages |
| `minicorp` | MiniCorp (EDS) | `<abs>/evalsbench/eds/domains/minicorp/tasks.py@minicorp` | In-Process | EDS 16-scenario agency bench (lookup/scheduling/tickets/currency/restraint/focus/precision) on tri-axis scorer |
| `custom-minicorp` | Custom-MiniCorp (EDS) | `<abs>/evalsbench/eds/domains/minicorp/tasks.py@minicorp` | In-Process | V2 alias under the `custom-` lexical prefix contract; routes to EDS tri-axis scoring |
| `terminal_bench_2` | TerminalBench2 | `inspect_harbor/terminal_bench_2` | Docker | Autonomous real-world Linux sysadmin, compilation & troubleshooting |
| `writingbench` | WritingBench | `inspect_evals/writingbench` | In-Process | Multi-domain long-form prose graded by a Claude Haiku judge |
| `assistant_bench` | AssistantBench | `inspect_evals/assistant_bench_web_search_zero_shot` | In-Process | Real-world digital assistant tasks with web search & constraint resolution |
| `deepsearchqa` | DeepSearchQA | `inspect_harbor/kgmon_deepsearchqa` | Docker | Google DeepMind 900-prompt multi-hop deep research retrieval |

---

## 🧬 Evaluation Development System (EDS)

EDS is the in-repo authoring surface for **structured agency benchmarks** — scenarios that score an agent on a tri-axis scorecard (Functional × Hygiene × Safety gate) backed by an auditable, per-episode tool-event trace and frozen seeded fixtures. The shipped MiniCorp domain ports Luke's 16-scenario Agency Bench into the EDS model.

### Quick-Start

Lint, scaffold, and run an EDS scenario in three commands:

```bash
# 1. Lint an EDS episode spec (.eds.md)
python -m evalsbench validate-spec evalsbench/eds/specs/examples

# 2. Scaffold a brand-new EDS domain package on disk
python -m evalsbench new-eval --domain my-mini-agency

# 3. Run the shipped MiniCorp suite (16 scenarios) via the standard flag-based CLI
python -m evalsbench --benchmarks minicorp --limit 16 --max-connections 1 \
  -m <model> -e <endpoint>
```

The headless run produces `report.eds.md` + `results.eds.json` under `logs/YYYYMMDD_<model>_minicorp/` and an `eds_tri_axis` row in the dashboard's `🧬 EDS Tri-Axis` tab.

### Why EDS

| Question | Standard benchmark | EDS |
| :--- | :--- | :--- |
| Did the model get the answer? | ✅ | ✅ (Axis 1: Functional) |
| Did it call tools frugally? | ❌ | ✅ (Axis 2: Hygiene) |
| Did it respect critical policy rules? | ❌ | ✅ (Axis 3: Safety gate) |
| Did it leave an auditable trace? | ❌ | ✅ (append-only `world.trace`) |
| Can a contributor author a new scenario in one Markdown file? | ❌ | ✅ (`.eds.md` DSL) |

### The Tri-Axis Scorecard

Every EDS run projects each episode onto three independent axes and clamps the **functional score to 0.0** on any critical policy violation (the **safety-gate invariant**). See `docs/eds_guide.md` for the full architecture (5 layers, episode contract, provenance tiers, trap taxonomy) and the end-to-end domain-creation tutorial.

---

## 🛠️ How to Add a New Benchmark (Developer Guide)

`configs/benchmarks.yaml` is the single source of truth. Adding a new benchmark requires only 3 simple steps:

### Step 1: Register the Benchmark in `configs/benchmarks.yaml`
Add an entry under the `benchmarks` key (the Python loader in `evalsbench/registry.py` picks it up automatically, with a defensive in-code fallback):

```yaml
newbench:
  name: NewBench
  source: inspect_evals/newbench       # Provenance string
  task_id: inspect_evals/newbench      # Inspect AI task path
  is_custom: false                     # True for user-authored `custom-*` EDS benchmarks
  category: coding
  scoring_mode: deferred               # "immediate" (live accuracy) or "deferred" (batch graded)
  default_limit: 25
  default_max_connections: 8
  time_limit: 180                      # Timeout in seconds
  turn_limit: 10                       # Max turns per sample
  docker_required: false               # Set true if sandbox execution is required
  max_samples: null                    # Dataset ceiling for progress-counter clamping
  description: "One-line plain English description (powers the CLI wizard & AI facilitation skill)."
```

If the benchmark belongs in a preset, append its key to the relevant `presets` list in the same file.

### Step 2: Register Dependencies in `evalsbench/doctor.py`
Add any external pip packages required by the benchmark to `BENCHMARK_DEPENDENCIES`:

```python
BENCHMARK_DEPENDENCIES["newbench"] = ["newbench-package>=1.0.0"]
```

### Step 3: Verify with a 1-Sample Preflight Run
Test your newly added benchmark to ensure execution and scoring work cleanly:

```bash
python3 -m evalsbench --benchmarks newbench --limit 1 --max-connections 1
```

---

## 🔒 Safety & Resource Management Directives

1. **Strict Connection Throttling:** On single-GPU or low-throughput local endpoints (e.g. models generating at 10–20 tok/s), always pass `--max-connections 1` to prevent socket contention and timeout cascades.
2. **Context & Turn Ceilings:** Never run agentic benchmarks uncapped. The built-in defaults enforce `turn_limit=30`, `time_limit=300`, `max_tool_output=16384`, and `max_tokens=4096` to prevent runaway memory usage.
3. **Container Pruning:** Sandboxed runs register an exit handler that invokes `docker rm -f` on any exited evaluation containers, preventing dangling container leaks.

---

## 📄 License
MIT License. Open for community contributions, forks, and new benchmark adapters.
