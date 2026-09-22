# 📋 Feature Audit Accumulator: Evaluation Development System (EDS)

* **Branch:** `eds/evaluation-development-system`
* **Repository:** `EvalsBench`
* **Lead Orchestrator:** `@droid:master-audit`
* **Audit Swarm Workers:** `worker_systemsaudit`, `worker_functionalaudit`, `worker_dogfood`, `worker_ponytail`

---

## 📋 Audit Round 1 — 2026-09-22 21:37

### 🚦 Executive Verdict: BLOCKER

The branch introduces an impressive, well-architected foundation for declarative evaluation development:
- **Pydantic v2 domain models** in `evalsbench/eds/models.py`.
- **Copy-on-write `WorldState`** with snapshot diffing and immutable event tracing in `evalsbench/eds/world.py`.
- **Deterministic tool dispatch** with precondition and policy enforcement in `evalsbench/eds/tools.py`.
- **Tri-axis scoring** (`tri_axis`) balancing functional predicates, frugality penalties, and safety clamps.
- **100% unit test pass rate** (273/273 tests passing in 6.97s).
- **Clean specification validation** for the canonical `minicorp_booking.eds.md`.

However, the branch cannot be cleared for merge due to **5 critical BLOCKER issues** in system integration, concurrency, and telemetry pipelines:
1. **Subprocess lifecycle leak and hang vulnerability** in `evalsbench/runner.py`.
2. **Concurrency data race on shared mutable state** during parallel tool execution in `evalsbench/eds/tools.py`.
3. **Telemetry pipeline architectural disconnection** (dead code in `evalsbench/eds/solver.py` and `telemetry.py`).
4. **Disconnected EDS export pipeline** in `evalsbench/runner.py` (scorecards never written, breaking dashboard hydration).
5. **Terminal table parser corrupting model registry** with Unicode box delimiters and error strings in `configs/models.yaml`.

---

### 1. 🛡️ Systems Audit Findings

#### [BLOCKER] Subprocess Lifecycle Leak & Unbounded Execution
* **Location:** `evalsbench/runner.py` (lines 227–238)
* **Violation:** `subprocess.Popen` is spawned without context management, process cleanup handlers, or timeouts on `proc.wait()`. If an exception occurs, or if a user triggers an interrupt, or if `inspect_ai` deadlocks during sandbox setup, the child process runs detached indefinitely, consuming GPU/CPU compute.
* **Proposed Fix:** Wrap `subprocess.Popen` in a `try/finally` block that guarantees `proc.terminate()` followed by `proc.kill()` on timeout or cancellation, and enforce `proc.wait(timeout=task.time_limit + 60)`.

#### [BLOCKER] Concurrency Data Race on Shared Mutable State
* **Location:** `evalsbench/eds/tools.py` (line 391) & `evalsbench/eds/world.py`
* **Violation:** Inspect AI executes parallel tool calls concurrently via `asyncio.gather`. Neither `WorldState.set_entity` nor `WorldState.record_event` employs synchronization primitives (locks or mutexes). Simultaneous calls in a single agent turn cause dictionary state corruption and race conditions in event ordering.
* **Proposed Fix:** Add an `asyncio.Lock` or `threading.Lock` within `WorldState` protecting all mutating operations (`set_entity`, `record_event`), or serialize tool executions inside the tool wrapper closure.

#### [BLOCKER] Telemetry Pipeline Disconnection (Dead Code)
* **Location:** `evalsbench/eds/solver.py` (line 237), `telemetry.py`, `tri_axis.py`
* **Violation:** `TelemetryCollector` is never instantiated or imported in `solver.py`, and `get_model().generate` is never wrapped with `measure_generate()`. Furthermore, `tri_axis.py` does not propagate telemetry metrics to `score.value`, and `minicorp/tasks.py` does not register `telemetry_scorer`. Hardware telemetry (TTFT, decode TPS, MTP acceptance) is completely decoupled from live evaluation runs.
* **Proposed Fix:** In `evalsbench/eds/solver.py`, instantiate `TelemetryCollector` and wrap the model generation call. Ensure `telemetry_scorer` is registered alongside `tri_axis` in domain tasks.

#### [BLOCKER] Disconnected EDS Export Pipeline & Broken Dashboard Hydration
* **Location:** `evalsbench/runner.py` (line 255) & `evalsbench/exporters.py`
* **Violation:** `write_eds_scorecard` is defined but never called in `runner.py` or `write_benchmark_report`. During evaluation runs of EDS benchmarks (`minicorp`), `results.eds.json` and `report.eds.md` are never generated on disk. Consequently, `hydrator.py`'s `_harvest_eds_scorecards` finds zero files, and the dashboard is never populated with tri-axis metrics.
* **Proposed Fix:** Update `EvalsRunner.run_benchmark` to detect EDS tasks (via `EDS_BENCHMARK_KEYS`) and invoke `write_eds_scorecard` to write `results.eds.json` into the run log directory.

#### [BLOCKER] Terminal Table Parser Corrupts Model Registry (`configs/models.yaml`)
* **Location:** `evalsbench/runner.py` (lines 290–305)
* **Violation:** `_parse_scores_from_output` uses naive string splitting on Inspect AI terminal stdout lines. Box-drawing characters (`│`) and error traces are parsed as valid metric keys, polluting `configs/models.yaml` with corrupted entries such as `'│': 1783.0` and `'NotFoundError:': 404.0`.
* **Proposed Fix:** Replace terminal stdout scraping with direct inspection of the generated `.eval` / `results.json` log artifact, or strictly filter parsed keys against an alphanumeric whitelist.

#### [CONDITIONAL] Stream Handle Leak
* **Location:** `evalsbench/runner.py` (line 230)
* **Violation:** `proc.stdout` from `subprocess.Popen` is not explicitly closed via `proc.stdout.close()` or a context manager, leaking file descriptors across sequential benchmarks.
* **Proposed Fix:** Ensure `proc.stdout.close()` is called in the `finally` block.

#### [CONDITIONAL] Memory Saturation on Archive Load
* **Location:** `evalsbench/exporters.py` (line 1765)
* **Violation:** `_load_eval_log_from_path` reads and decodes every sample JSON in `.eval` zip archives into a single in-memory list, causing high memory spikes on large test suites.
* **Proposed Fix:** Stream and extract only the score summary and target samples on demand.

#### [CONDITIONAL] Recursive State Diffing Cycle Risk
* **Location:** `evalsbench/eds/world.py` (line 163)
* **Violation:** `_deep_diff` traverses state trees recursively without cycle detection or depth bounding, risking `RecursionError` on nested circular structures.
* **Proposed Fix:** Introduce a `visited` set and depth limit to `_deep_diff`.

#### [CONDITIONAL] False-Positive Error Recovery
* **Location:** `evalsbench/runner.py` (line 280)
* **Violation:** When `proc.returncode != 0`, `run_benchmark` still prints `✅ Completed`, generates empty reports, and updates `models.yaml` with empty score dictionaries.
* **Proposed Fix:** Short-circuit on non-zero return codes, log error output, and skip scorecard export.

#### [CONDITIONAL] Line Number Offset in Specification Parser
* **Location:** `evalsbench/eds/parser.py` (line 265)
* **Violation:** In `_split_body_sections`, `abs_line` resets to 1 instead of offsetting by frontmatter line count, leading to inaccurate error line reporting in linter diagnostics.
* **Proposed Fix:** Pass the frontmatter line offset into `_split_body_sections`.

---

### 2. 📋 Functional & Documentation Audit Findings

#### [CONDITIONAL] Invalid CLI Suite Choice in `SKILL.md`
* **Location:** `skills/run_evals/SKILL.md` (line 47)
* **Discrepancy:** Documents `--suite <standard7|screening|coding|agentic|instruction|vision|agency|full>`, but `agency` does not exist in `evalsbench/registry.py` `PRESET_SUITES` or `cli.py`, causing `argparse` to abort with `invalid choice: agency`.
* **Proposed Fix:** Remove `agency` from `SKILL.md` or register it in `PRESET_SUITES` mapping to `minicorp`.

#### [CONDITIONAL] Suite Composition Divergence for `agentic`
* **Location:** `evalsbench/registry.py` vs. `AGENTS.md`, `README.md`, `SKILL.md`
* **Discrepancy:** `evalsbench/registry.py` includes `minicorp` in `PRESET_SUITES["agentic"]`, but `AGENTS.md` (line 78), `README.md` (line 113), and `SKILL.md` (line 31) document the suite as containing only `agentbench, pawbench, gaia`.
* **Proposed Fix:** Align documentation to reflect `minicorp` inclusion in the `agentic` suite.

#### [CONDITIONAL] Missing Catalog & Architecture Entries in Documentation
* **Location:** `README.md` and `AGENTS.md`
* **Discrepancies:**
  - `README.md` Supported Benchmark Catalog omits `minicorp`.
  - `README.md` and `AGENTS.md` Directory Layout trees omit `evalsbench/eds/`.
  - Neither `README.md` nor `AGENTS.md` documents `validate-spec` or `new-eval` CLI subcommands.
* **Proposed Fix:** Add `evalsbench/eds/` layout, `minicorp` catalog entry, and subcommand documentation to both `README.md` and `AGENTS.md`.

---

### 3. 🐕 Dogfood & UX Integration Findings

* **Unit Test Health:** 273 passed, 0 failed in `tests/eds/` (6.97s).
* **Static Compilation:** 0 syntax errors across `evalsbench/` and `tests/`.
* **Spec Linter Execution:** Canonical `minicorp_booking.eds.md` passes with 0 errors and 0 warnings.
* **Domain Scaffolder Execution:** `evalsbench new-eval` generates valid package directories, and scaffolded `.eds.md` passes validation cleanly.
* **Usability Findings:**
  1. `evalsbench --help` does not show subcommands (`validate-spec`, `new-eval`) because they are intercepted prior to `argparse`.
  2. Scaffolder CLI flags (`--domain`, `--base-dir`) diverge from standard positional `<domain>` and `--output-dir` conventions.

#### Copy-Pasteable User Verification Commands
```bash
# 1. Spec Linting
PYTHONPATH=. /home/sumergoconicio/.venv/bin/python -m evalsbench validate-spec evalsbench/eds/specs/examples/minicorp_booking.eds.md

# 2. Domain Scaffolding
PYTHONPATH=. /home/sumergoconicio/.venv/bin/python -m evalsbench new-eval --domain test_domain --base-dir scratch/test_scaffold
PYTHONPATH=. /home/sumergoconicio/.venv/bin/python -m evalsbench validate-spec scratch/test_scaffold/test_domain/specs/
rm -rf scratch/test_scaffold

# 3. Pytest Regression
PYTHONPATH=. /home/sumergoconicio/.venv/bin/pytest tests/eds/ -v
```

---

### 4. 🐴 Code Hygiene & Over-Engineering Findings (worker_ponytail)

**Potential Code Reduction:** ~223 lines across 17 identified locations.

1. **`evalsbench/eds/linter.py` (line 468):** Import `_split_params` and tool regexes from `parser.py` instead of duplicating (-21 lines).
2. **`evalsbench/eds/tools.py` (line 33):** Remove unused `get_type_hints` import (-1 line).
3. **`evalsbench/eds/tools.py` (line 563):** Consolidate duplicate `json.dumps` try/except branches in `_format_result` (-6 lines).
4. **`evalsbench/eds/scaffold.py` (line 299):** Remove redundant `world.record_event` in scaffolded template (-5 lines).
5. **`evalsbench/eds/telemetry.py` (line 403):** Pass `_metrics_timeout_s` to `_scrape` (-4 lines).
6. **`evalsbench/eds/scorers/tri_axis.py` (line 318):** Unify `_predicate_text_or_names` and `_predicate_text_content` (-20 lines).
7. **`evalsbench/eds/scorers/tri_axis.py` (line 937):** Simplify `dotted.split('.')` (-1 line).
8. **`evalsbench/eds/world.py` (line 132):** Unify `_flatten_added` and `_flatten_removed` into `_flatten_mutation` (-10 lines).
9. **`evalsbench/eds/parser.py` (line 671):** Modularize 169-line `_build_spec` into sub-parsers (-35 lines).
10. **`evalsbench/eds/parser.py` (line 970):** Reuse `_serialise_section` in `_build_sample` (-18 lines).
11. **`evalsbench/exporters.py` (line 394):** Consolidate 4 formatting closures in `_format_eds_section` into a single parameterized helper (-25 lines).
12. **`evalsbench/exporters.py` (line 635):** Replace bare `except Exception: pass` with logger warning (-3 lines).
13. **`evalsbench/cli.py` (line 150):** Register subcommands via standard `add_subparsers()` (-22 lines).
14. **`evalsbench/runner.py` (line 100):** Extract shared `_build_eval_cmd` between preflight and benchmark runner (-20 lines).
15. **`evalsbench/runner.py` (line 290):** Sanitize table parser against Unicode delimiters (-8 lines).
16. **`evalsbench/runner.py` (line 78):** Unify API key sniffing with `cli.py` into `config.py` (-10 lines).

---

## 🔧 Remediation Roadmap

To achieve `PASS (CLEARED FOR MERGE)`, the following remediation sequence is required:

- [x] **Phase 1: Concurrency & Process Safety (Blockers 1 & 2)**
  - Addressed process group isolation; concurrency proven atomic in-loop across 5 tests.
- [x] **Phase 2: Pipeline Wiring (Blockers 3 & 4)**
  - Wired `TelemetryCollector` and `measure_generate` into `evalsbench/eds/solver.py`.
  - Wired `write_eds_scorecard` into `evalsbench/runner.py` for EDS benchmark runs.
- [x] **Phase 3: Terminal Parser & Registry Hardening (Blocker 5)**
  - `runner.py` now ingests `.eval` logs via `extract_eds_metrics()` for EDS tasks.
- [x] **Phase 4: Documentation & CLI Polish (Conditionals)**
  - Updated `AGENTS.md`, `README.md`, and `SKILL.md` (resolved `--suite agency` bug).
  - Surfaced subcommands in top-level `evalsbench --help` epilog.

---

## 📋 Audit Round 2 — 2026-09-22 22:25

### 🚦 Executive Verdict: BLOCKER (1 Remaining Blocker; 4 Resolved)

Significant progress was achieved in the remediation pass:
- **Blocker 2 (Concurrency Data Race):** **RESOLVED.** Atomic in-loop execution contract validated and pinned by 5 tests in `tests/eds/test_world_concurrency.py`.
- **Blocker 3 (Telemetry Disconnection):** **RESOLVED.** `TelemetryCollector` wired inside `eds_agent_solver` in `evalsbench/eds/solver.py`, `measure_generate` attached, and run-level metric validated in `tests/eds/test_telemetry_wiring.py`.
- **Blocker 4 (Scorecard Export Gap):** **RESOLVED.** `write_eds_scorecard` actively invoked in `runner.py` for EDS tasks, generating `report.eds.md` and `results.eds.json`.
- **Blocker 5 (Terminal Parser Delimiter Pollution):** **RESOLVED.** Direct `.eval` artifact metric extraction via `extract_eds_metrics()` bypasses stdout box-character parsing.
- **Dogfood & Code Hygiene:** Both workers issued **`PASS`** verdicts. Unit test suite expanded from 273 to **301 passing tests**.

**Single Remaining Blocker:** A critical ordering flaw in `evalsbench/runner.py` leaves child process hang prevention incomplete.

---

### 1. 🛡️ Systems Audit Findings (`worker_systemsaudit`)

#### [BLOCKER] Synchronous Blocking `readline()` Call Precedes `proc.wait(timeout)`
* **Location:** `evalsbench/runner.py` (lines 351–376)
* **Failure Mode:** `_proc_stdout.readline()` is a synchronous OS pipe read syscall executed inside `iter(_proc_stdout.readline, "")`. If a child process deadlocks or hangs without output and without closing stdout (e.g., frozen CUDA kernel or deadlocked container socket), `readline()` blocks indefinitely at the kernel level. As a result, execution never reaches line 375 `proc.wait(timeout=_wait_budget_s)`. This failure mode was masked in unit tests by mocking `Popen` with `stdout = None`.
* **Concrete Proposed Fix:** Implement an asynchronous watchdog timer (`threading.Timer`) or non-blocking reader thread that enforces `_wait_budget_s` regardless of stream activity. If the watchdog fires, it triggers `_terminate_process_group(proc)`, which breaks the kernel read syscall on the pipe and allows execution to recover cleanly.

#### [CONDITIONAL] Orphan Process Risk on Unhandled Interruption
* **Location:** `evalsbench/runner.py` (lines 502–506)
* **Failure Mode:** Subprocess spawned with `start_new_session=True` is detached from the terminal session. If `run_benchmark` raises an unhandled exception or receives `KeyboardInterrupt` before completing `proc.wait()`, the outer `finally:` block does not invoke `_terminate_process_group(proc)`, leaving orphaned background child processes running on host compute.
* **Concrete Proposed Fix:** In `finally:`, verify if `proc.poll() is None`; if still running, invoke `_terminate_process_group(proc)`.

---

### 2. 📋 Functional & Documentation Audit Findings (`worker_functionalaudit`)

#### Status: CONDITIONAL
* **Resolved:** `--suite agency` bug in `SKILL.md` removed; directory trees and EDS documentation populated in `docs/eds_guide.md` and `AGENTS.md`.
* **Remaining Minor Parity Items:**
  1. `README.md` directory tree still omits `evalsbench/eds/` and `docs/`.
  2. `README.md` preset suites table lists `agentic` as `agentbench, pawbench, gaia`, omitting `minicorp`.
  3. `AGENTS.md` section "How to Run Evaluations" should include an explicit command snippet for `validate-spec` and `new-eval`.

---

### 3. 🐕 Dogfood & Integration Findings (`worker_dogfood`)

#### Status: PASS
* **Capability Check:** `echo ok` verified.
* **Test Suite:** 301/301 tests passed in 7.72s.
* **CLI Discovery:** `python -m evalsbench --help` renders epilog advertising `validate-spec` and `new-eval` with usage examples.
* **Scaffolding Lifecycle:** `new-eval` package generation, spec validation, and directory cleanup verified end-to-end.

---

### 4. 🐴 Code Hygiene & Over-Engineering (`worker_ponytail`)

#### Status: PASS
* Remediation code in `runner.py`, `solver.py`, and `world.py` is clean and idiomatic.
* Zero architectural bloat introduced.
* 157 lines of optional code hygiene opportunities cataloged across 14 non-blocking items (parser/linter utility deduplication, exporter closures).

---

### 📉 Final Certification Step to Achieve `PASS (CLEARED FOR MERGE)`

- [ ] **Subprocess Watchdog & Cleanup (Blocker 1):**
  - Add a `threading.Timer` watchdog to enforce `_wait_budget_s` during stream reading in `runner.py`.
  - Ensure `_terminate_process_group(proc)` is called in the outer `finally:` if the process is still alive.
- [ ] **Documentation Polish (Conditionals):**
  - Update `README.md` file tree and preset suite table to reflect `minicorp`.
  - Add `validate-spec` / `new-eval` examples to `AGENTS.md`.
