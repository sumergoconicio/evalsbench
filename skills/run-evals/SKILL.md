---
name: run-evals
description: Autonomous model evaluation and benchmarking skill. Use whenever the user asks to test, evaluate, benchmark, or profile a local or cloud LLM.
---

# 🚀 Run Evals Skill (V2 — 3D Operational Matrix)

Use this skill whenever the user asks to benchmark, qualify, or test an LLM (e.g., *"access this model at this endpoint and run evals for me"*, *"run a quick smoke test on master-lite"*, or *"stress-test gemini flash"*).

The framework composes every run from three orthogonal dimensions — **Suite × Profile × Scale** — declared declaratively in `configs/benchmarks.yaml` (the single source of truth; read it for fresh 1-line descriptions rather than trusting this doc's cache).

---

## 🧭 Facilitation Check-In (Interactive Runs)

When the user has not fully specified the run, conduct a brief check-in **querying Scale, Suite, and Profile**, presenting the dynamic 1-line descriptions pulled from `configs/benchmarks.yaml`, and preview the exact tests in the chosen preset before launching:

1. **Scale** — how many questions per benchmark?
   - `--short` — 20 questions per benchmark (~10-12 min local) — fast iteration & CI.
   - `--long` — 100 questions per benchmark (~45-60 min) — leaderboard confidence.
   - `--complete` — all questions (exhaustive dataset, 2-6 hours) — academic qualification.
2. **Suite** — which functional preset?
   - `core` — everyday baseline: instruction following, tool routing, code, agency, prose.
   - `agent` — autonomous agentic execution, stateful tool loops, Docker sysadmin, multimodal.
   - `knowledge` — long-form technical prose, open-web digital assistant, multi-hop research.
   - `all` — complete 10-benchmark gauntlet across all cognitive & agentic axes.
   - Or a single benchmark pick (see catalog below).
3. **Profile** — which hardness stratification?
   - `gatekeeper` — 50% Easy / 40% Medium / 10% Hard — rapid qualification & regression triage.
   - `echelon` — 10% Easy / 50% Medium / 40% Hard — frontier stress-testing & trap exposure.
   - `full` — natural unstratified distribution.
4. **Preview & Confirm** — list the exact benchmarks in the chosen preset with their 1-line descriptions and scoring mode, then launch.

For non-interactive runs, skip the check-in and execute headless with explicit flags.

---

## 🗺️ The 3D Operational Matrix

```text
python -m evalsbench --model <model> --suite <suite> -d <profile> --<scale>
```

| Dimension | Flag | Values |
| :--- | :--- | :--- |
| 1. Functional Preset | `--suite` / `-s` | `core`, `agent`, `knowledge`, `all` |
| 2. Hardness Profile | `--difficulty-profile` / `-d` | `gatekeeper`, `echelon`, `full` |
| 3. Sample Scale | scale flags | `--short` (20), `--long` (100), `--complete` (all) |

- Explicit `--limit N` overrides the scale flags.
- Dataset ceilings are clamped automatically (e.g. `custom-minicorp` caps at 16 scenarios; requesting `--long` yields 16/16, never a misleading 16/100).
- Tasks without Inspect AI difficulty subsets run unstratified with an informational notice (no error).
- **Modality filter:** pass `--modality multimodal` (vision/document benchmarks only — currently `gaia`, `docvqa`) or `--modality text` (text-only benchmarks only) to narrow any suite or benchmark selection. Ask vision-incapable models for `--modality text` by default; multimodal benchmarks error out on them.

---

## 📋 Curated 10-Benchmark Catalog

| Key | Name | Scoring | Docker | 1-Line Description |
| :--- | :--- | :--- | :--- | :--- |
| `ifeval` | IFEval | Immediate | No | Strict and loose negative constraint adherence, JSON schema delimiters, and formatting rules. |
| `bfcl` | BFCL | Deferred | No | Berkeley Function Calling Leaderboard for deterministic single, parallel, and multi-turn tool dispatch. |
| `humaneval` | HumanEval | Deferred | Yes | Functional Python coding primitives and pass@1 automated unit test validation in Docker. |
| `custom-minicorp` | Custom-MiniCorp | Immediate | No | 16-scenario stateful agency bench testing lookup, ticketing, calendar booking, and zero-tolerance safety traps. |
| `terminal_bench_2` | TerminalBench2 | Deferred | Yes | Autonomous real-world Linux system administration, compilation, and troubleshooting inside Docker. |
| `writingbench` | WritingBench | Deferred | No | Multi-domain long-form prose evaluated by Anthropic Claude Haiku judge. |
| `assistant_bench` | AssistantBench | Deferred | No | Real-world digital assistant tasks requiring web search, information extraction, and constraint resolution. |
| `gaia` | GAIA | Deferred | Yes | Multi-modal, multi-step general AI assistant reasoning and tool chaining in Docker. |
| `docvqa` | DocVQA | Immediate | No | Visual document understanding and key-value extraction across forms, invoices, and dense tables. |
| `deepsearchqa` | DeepSearchQA | Deferred | Yes | Google DeepMind 900-prompt multi-hop deep research and factual information retrieval. |

**Scoring mode transparency** — report to the user which mode applies:
- **Immediate**: graded per-sample in flight; running accuracy (`Acc: 87.5% (7/8)`) streams live.
- **Deferred**: generation recorded during the run; grading happens at batch conclusion (Docker test runners, AST replay, or LLM-judge panels). The live monitor shows `Status: RECORDED (Pending Grade)` — a run showing 100% progress with no accuracy figure is normal for deferred benchmarks, not a failure.

---

## 🖥️ Endpoint & Model Detection

1. **Check Local Endpoints First:**
   Query `http://localhost:2468/v1/models` (or ports `8000`, `8080`, `1123`, `11434`, `12468`):
   ```bash
   curl -s http://localhost:12468/v1/models | jq '.data[].id'
   ```
2. **Cloud Models (direct vendor routing, no LiteLLM proxy):**
   Pass the provider-prefixed model string directly — the router (`evalsbench/router.py`) resolves it and reads credentials from `~/chai/.env`:
   - `google/gemini-2.5-flash` → `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
   - `deepseek/deepseek-chat` → `DEEPSEEK_API_KEY`
   - `anthropic/claude-3-5-sonnet` → `ANTHROPIC_API_KEY`
   - `openai/gpt-4o` → `OPENAI_API_KEY`
   - `openrouter/*` → `OPENROUTER_API_KEY`
   No `--endpoint` is needed for cloud models; if a required key is missing from `~/chai/.env`, ask the user to add it — never substitute dummy keys.

---

## ⚡ Execution

```bash
# Local qualification smoke test (JTBD-1): ~10 minutes
/home/sumergoconicio/.venv/bin/python -m evalsbench \
  --model master-lite \
  --endpoint http://localhost:12468/v1 \
  --suite core -d gatekeeper --short --max-connections 8

# Frontier stress test (JTBD-2): exhaustive
/home/sumergoconicio/.venv/bin/python -m evalsbench \
  --model google/gemini-2.5-flash \
  --suite all -d echelon --complete

# Preflight sanity ping (always before long batches)
/home/sumergoconicio/.venv/bin/python -m evalsbench \
  --model master-lite --benchmarks custom-minicorp --short --time-limit 120 --max-connections 1
```

Additional flags: `--time-limit <s>` (per-run wall-clock override), `--max-connections <n>` (use `1` for single-slot / ≤20 tok/s servers), `--skip-preflight`, `--no-chai-sync`.

---

## 📡 Live Telemetry (What You Will See)

While a run is in flight, the terminal renders a dual-row telemetry card per benchmark: progress with ETA, scoring-mode transparency, per-question prompt size with KV-cache hit percentage, TTFT (prefill latency), decode tok/s, MTP draft acceptance (when active), and stream saturation. When reporting results to the user, include the telemetry summary line (Avg TTFT, Avg Decode, Cache Hit Rate, MTP) — it is the hardware profiling payload (JTBD-4).

---

## 📥 Harvest Results & Present Summary

1. Logs and scorecards land in `logs/YYYYMMDD_modelname_benchmarkname/`.
2. `configs/models.yaml` is updated automatically, including decode TPS and TTFT telemetry in the model ledger.
3. Markdown reports sync to `~/chai/references/models/<model-name>/`.
4. Present the complete scorecard with structured metrics (Pass@1, accuracy, composite, throughput, MTP acceptance) plus the telemetry summary.

---

## ⚠️ Safety & Environment Directives

* Enforce multi-turn safety guardrails: `--turn-limit` (max 30), `--time-limit` (max 300s; 600s for writing/research tasks), `--max-tool-output 16384`, `--reasoning-history none`, and `-M responses_api=false`. Never run agentic or tool benchmarks uncapped.
* Use `--max-connections 8` on DGX Spark nodes; `--max-connections 1` on low-throughput / single-slot local models.
* Docker-sandboxed benchmarks (HumanEval, GAIA, TerminalBench2, DeepSearchQA) are cleaned up automatically post-run via `evalsbench.sandboxes.prune_inspect_containers()`.
* Never kill running background services without explicit user confirmation.
* For EDS (`custom-*`) runs, treat `critical_violations_total > 0` as functionally zero (safety-gate invariant).
