"""
Execution engine with preflight validation, auto-healing dependencies,
live streaming progress bar, polite Docker hygiene, and a watchdog
safety net that prevents runaway inspect_ai subprocesses from
holding the parent blocked on a kernel-level ``readline()`` past
their nominal wall-clock budget.
"""

import os
import signal
import sys
import threading
import time
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import get_log_dir_for_benchmark, load_chai_env
from .registry import BENCHMARK_REGISTRY, BenchmarkTask, get_difficulty_task_args
from .shims import apply_inspect_openai_shims
from .sandboxes import prune_inspect_containers
from .doctor import ensure_dependencies_for_task
from .progress import LiveProgressBar
from .exporters import (
    EDS_BENCHMARK_KEYS,
    extract_eds_metrics,
    write_benchmark_report,
    write_eds_scorecard,
    update_models_yaml,
    sync_to_chai_vault,
)


# ---------------------------------------------------------------------------
# Repo-root resolution for PYTHONPATH injection
# ---------------------------------------------------------------------------

#: Absolute path to the repository root that owns the ``evalsbench``
#: package. The runner injects this directory into the spawned
#: ``python -m inspect_ai eval`` subprocess's ``PYTHONPATH`` so that
#: locally-defined tasks (e.g. the EDS MiniCorp ``tasks.py``) can
#: ``import evalsbench`` after :func:`inspect_ai._util.path.chdir_python`
#: changes the subprocess cwd to the task file's parent.
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def _build_subprocess_env(*, base_url: str, api_key: str) -> Dict[str, str]:
    """Compose the subprocess env with PYTHONPATH and endpoint overrides.

    Args:
        base_url: OpenAI-compatible endpoint URL injected as
            ``OPENAI_BASE_URL``.
        api_key: API key injected as ``OPENAI_API_KEY``.

    Returns:
        Dict[str, str]: a copy of ``os.environ`` with the
        ``PYTHONPATH`` prefix pointing at the repository root and the
        OpenAI-compatible endpoint variables set.
    """
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    paths: List[str] = [str(_REPO_ROOT)]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["OPENAI_BASE_URL"] = base_url
    env["OPENAI_API_KEY"] = api_key
    return env


# ---------------------------------------------------------------------------
# BLOCKER 1 — subprocess orphan / hang remediation
# ---------------------------------------------------------------------------
#: Wall-clock margin (seconds) added to ``task.time_limit`` when waiting
#: on a live inspect_ai child. Generous on purpose: tool-heavy
#: benchmarks (BFCL/GAIA/AgentBench) frequently overrun their nominal
#: turn budget while flushing the final ``.eval`` zip. Anything that
#: still hasn't exited by ``time_limit + margin`` is hung and gets the
#: SIGTERM → SIGKILL escalation below.
_SUBPROCESS_WAIT_MARGIN_S: int = 300

#: Drain windows (seconds) for each kill escalation phase. Short enough
#: that the CLI keeps moving on slow nodes; long enough that inspect_ai
#: has a chance to flush its ``.eval`` archive on SIGTERM.
_SUBPROCESS_DRAIN_S: float = 5.0


def _terminate_process_group(proc: Optional[subprocess.Popen]) -> None:
    """Escalate SIGTERM → SIGKILL on the subprocess's process group.

    The RPC-style inspect_ai evals occasionally hang past their nominal
    wall-clock budget (e.g. socket starvation under heavy concurrent
    agentic workloads). Left alone, those orphans hold GPU/CPU compute
    and prevent the next benchmark from launching. This helper drops
    the entire process group via :func:`os.killpg`, then reaps the
    zombie so the OS frees the slot before the next call.

    Args:
        proc: The :class:`subprocess.Popen` handle whose process group
            should be terminated. ``None`` is tolerated for symmetry
            with optional :class:`Popen` slots and is a no-op.

    Returns:
        None: Side effects only. Never raises; defensive against
        re-entry (idempotent on already-dead PID), ``PermissionError``
        (non-root process), and ``OSError`` edge cases.
    """
    if proc is None:
        return
    pid = getattr(proc, "pid", None)
    if pid is None:
        return

    # SIGTERM first — child processes get a chance to flush the .eval
    # archive and exit cleanly. Catch every killpg failure mode
    # (already-dead PID, permission, generic OS errors) beneath a
    # broad noqa so the helper never bubbles an exception upward.
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    # Polite drain window — the child may already have raced to exit.
    try:
        proc.wait(timeout=_SUBPROCESS_DRAIN_S)
        return
    except subprocess.TimeoutExpired:
        pass

    # Escalate to SIGKILL when SIGTERM was ignored / blocked.
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    # Final reap; if the kernel still hasn't released the slot we
    # abandon the wait rather than block the runner indefinitely.
    try:
        proc.wait(timeout=_SUBPROCESS_DRAIN_S)
    except subprocess.TimeoutExpired:
        pass


def _load_eval_log_for_extract(source: Optional[Any]) -> Optional[Any]:
    """Resolve an ``.eval`` source for :func:`extract_eds_metrics`.

    Prefers :func:`inspect_ai.log.read_eval_log` when it is installed
    (the contract keeps the Inspect-native reader in the loop when
    available). Falls back to the raw path string so the exporters
    module's zip/JSON fallback reader can carry the load when Inspect's
    reader is unavailable or raises.

    Args:
        source: Path, EvalLog object, ``None``.

    Returns:
        Optional[Any]: Resolved source for ``extract_eds_metrics``.
        ``None`` propagates as ``None`` so the exporter contract
        degrades to an empty dict.
    """
    if source is None:
        return None
    try:
        from inspect_ai.log import read_eval_log  # type: ignore
    except Exception:
        return source
    try:
        return read_eval_log(str(source))
    except Exception:
        return source


class EvalsRunner:
    def __init__(
        self,
        model_name: str,
        endpoint_url: str,
        api_key: Optional[str] = None,
        max_connections: int = 8,
        chai_sync: bool = True,
        difficulty_profile: Optional[str] = None,
    ):
        self.model_name = model_name
        self.endpoint_url = endpoint_url.rstrip("/")
        self.max_connections = max_connections
        self.chai_sync = chai_sync
        self.difficulty_profile = difficulty_profile
        
        # Resolve API Key
        chai_env = load_chai_env()
        if not api_key:
            if "openrouter.ai" in self.endpoint_url:
                self.api_key = chai_env.get("OPENROUTER_API_KEY", "dummy")
            elif "api.openai.com" in self.endpoint_url:
                self.api_key = chai_env.get("OPENAI_API_KEY", "dummy")
            else:
                self.api_key = "dummy"
        else:
            self.api_key = api_key

        apply_inspect_openai_shims()

    def run_preflight_check(self, task: BenchmarkTask) -> bool:
        """
        Runs a fast 1-sample preflight test to verify connectivity, tokenization,
        and Docker sandbox readiness within 10 seconds.
        """
        print(f"\n🔍 [Preflight Gate] Testing 1 sample for {task.name}...")
        env = _build_subprocess_env(
            base_url=self.endpoint_url,
            api_key=self.api_key,
        )

        cmd = [
            sys.executable,
            "-m",
            "inspect_ai",
            "eval",
            task.task_id,
            "--model",
            f"openai/{self.model_name}",
            "-M",
            "responses_api=false",
            "--limit",
            "1",
            "--max-connections",
            "1",
            "--turn-limit",
            str(task.turn_limit),
            "--time-limit",
            str(task.time_limit),
            "--max-tool-output",
            str(task.max_tool_output),
            "--reasoning-history",
            task.reasoning_history,
        ]
        if task.args:
            cmd.extend(task.args)

        try:
            start_t = time.time()
            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=task.time_limit + 60,
            )
            elapsed = time.time() - start_t
            if proc.returncode == 0:
                print(f"✅ [Preflight Passed] {task.name} verified in {elapsed:.1f}s.")
                return True
            else:
                print(f"❌ [Preflight Failed] {task.name} exited with code {proc.returncode}.")
                print(proc.stderr[:500] if proc.stderr else proc.stdout[:500])
                return False
        except Exception as e:
            print(f"❌ [Preflight Error] {task.name} failed: {e}")
            return False
        finally:
            if task.docker_required:
                prune_inspect_containers()

    def run_benchmark(
        self,
        task_key: str,
        limit: Optional[int] = None,
        sample_shuffle: int = 42,
        skip_preflight: bool = False,
    ) -> Tuple[bool, Dict[str, Any], float]:
        """
        Executes a single benchmark task with auto-healing dependencies,
        live transparent progress bar, and polite post-eval Docker pruning.

        The function enforces two safety nets around the spawned
        :class:`subprocess.Popen` child:

        1. **Watchdog timer (R5):** a :class:`threading.Timer` armed
           with ``task.time_limit + _SUBPROCESS_WAIT_MARGIN_S`` fires
           if the readline iterator has not consumed EOF by then. A
           hung child that closes neither end of the stdout pipe
           (CUDA freeze / deadlocked Docker socket / network stall)
           would otherwise block the parent in a kernel-level read
           and prevent ``proc.wait(timeout=...)`` from ever firing.
           The watchdog terminates the process group, which closes
           the pipe and unblocks the readline loop. The timer is
           cancelled immediately when the streaming loop exits for
           any reason (normal EOF, exception, or break).
        2. **Orphan-process guard (R5):** the outer ``finally``
           block reaps the process group if ``run_benchmark`` exits
           via ``KeyboardInterrupt`` or an unhandled exception while
           the child is still alive (``start_new_session=True``),
           ensuring the child does not become an orphan.
        """
        task = BENCHMARK_REGISTRY.get(task_key)
        if not task:
            raise ValueError(f"Unknown benchmark: {task_key}. Available: {list(BENCHMARK_REGISTRY.keys())}")

        # 1. Auto-doctor dependency check
        ensure_dependencies_for_task(task_key)

        samples = limit or task.default_limit
        log_dir = get_log_dir_for_benchmark(self.model_name, task.name)

        print("\n" + "=" * 65)
        print(f"🚀 Launching Benchmark: {task.name} ({samples} samples, {self.max_connections} slots)")
        print(f"Model: {self.model_name} @ {self.endpoint_url}")
        print(f"Log Directory: {log_dir}")
        print("=" * 65)

        # 2. Preflight validation gate
        if not skip_preflight:
            if not self.run_preflight_check(task):
                print(f"⚠️ Skipping full batch for {task.name} due to preflight check failure.")
                return False, {}, 0.0

        env = _build_subprocess_env(
            base_url=self.endpoint_url,
            api_key=self.api_key,
        )

        cmd = [
            sys.executable,
            "-m",
            "inspect_ai",
            "eval",
            task.task_id,
            "--model",
            f"openai/{self.model_name}",
            "-M",
            "responses_api=false",
            "--limit",
            str(samples),
            "--sample-shuffle",
            str(sample_shuffle),
            "--max-connections",
            str(self.max_connections),
            "--turn-limit",
            str(task.turn_limit),
            "--time-limit",
            str(task.time_limit),
            "--max-tool-output",
            str(task.max_tool_output),
            "--reasoning-history",
            task.reasoning_history,
            "--log-dir",
            str(log_dir),
        ]
        if task.args:
            cmd.extend(task.args)
        diff_args = get_difficulty_task_args(task_key, self.difficulty_profile)
        if diff_args:
            cmd.extend(diff_args)

        start_time = time.time()
        raw_output_lines = []
        progress_bar = LiveProgressBar(task.name, total_samples=samples)

        # Pre-bind ``proc`` so the outer ``finally`` orphan-guard
        # can reference it even when ``subprocess.Popen`` itself
        # raises (e.g. executable not found): without this, an
        # exception inside ``Popen`` would leave ``proc`` undefined
        # and the orphan-guard would ``NameError`` instead of being
        # a true no-op.
        proc: Optional[subprocess.Popen] = None

        try:
            # 3. Stream process line-by-line to drive the live progress bar.
            # ``start_new_session=True`` ensures the subprocess owns its
            # own process group so the BLOCKER 1 timeout handler below
            # can ``killpg`` the entire tree on hang / runaway GPU/CPU.
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            _proc_stdout = proc.stdout

            # R5 (BLOCKER): arm a watchdog timer BEFORE entering the
            # kernel-level ``readline()`` loop. ``proc.wait(timeout=...)``
            # below is unreachable while the loop holds readline — a
            # child that hangs WITHOUT closing stdout (CUDA freeze,
            # deadlocked Docker socket, network stall) would otherwise
            # block the parent forever. The timer fires after
            # ``task.time_limit + _SUBPROCESS_WAIT_MARGIN_S`` seconds,
            # calls :func:`_terminate_process_group` on the entire
            # process group (closing the pipe), and unblocks the
            # readline iterator. The timer is cancelled as soon as the
            # loop exits for ANY reason — normal EOF, exception, or
            # ``break`` — so no zombie timer thread lingers.
            _wait_budget_s = task.time_limit + _SUBPROCESS_WAIT_MARGIN_S
            _watchdog = threading.Timer(
                _wait_budget_s,
                _terminate_process_group,
                args=(proc,),
            )
            _watchdog.daemon = True  # never block interpreter shutdown
            _watchdog.start()

            try:
                if _proc_stdout:
                    for line in iter(_proc_stdout.readline, ""):
                        raw_output_lines.append(line)
                        progress_bar.update_from_inspect_line(line)
            finally:
                # R5 cancel: stop the watchdog whether the loop exited
                # via normal EOF (cancel returns True — timer was
                # pending), an exception, or because the watchdog
                # itself already fired (cancel returns False — already
                # fired; the kill has already taken effect). Both
                # outcomes satisfy the contract: ``cancel()`` was
                # called unconditionally so NO lingering timer thread
                # can out-live the streaming loop. Wrapped in
                # try/except so a stale ``_watchdog`` reference
                # (e.g. CancellationError from a future Python
                # release) never masks the real exception.
                try:
                    _watchdog.cancel()
                except Exception:
                    pass
                # CONDITIONAL: defensive stream-close — prevent the
                # inspect_ai stdout pipe from leaking the file
                # descriptor across the long-running CLI session.
                if _proc_stdout is not None:
                    try:
                        _proc_stdout.close()
                    except Exception:
                        pass

            # BLOCKER 1: bounded wait with process-group kill
            # escalation. ``_wait_budget_s`` (defined above for the
            # R5 watchdog) is the wall-clock ceiling for this final
            # ``proc.wait(timeout=...)``. ``task.time_limit + 300s``
            # is a generous fallback that catches slow-tool
            # benchmarks without permitting indefinite CLI hangs.
            # On timeout the entire process group is
            # SIGTERM-then-SIGKILLed and the run is marked failed
            # (rather than abandoned to a zombie) so the next
            # benchmark can launch.
            try:
                proc.wait(timeout=_wait_budget_s)
            except subprocess.TimeoutExpired:
                _terminate_process_group(proc)
                try:
                    proc.wait(timeout=_SUBPROCESS_DRAIN_S)
                except subprocess.TimeoutExpired:
                    pass
                progress_bar.close()
                _hang_duration_s = time.time() - start_time
                print(
                    f"\n⚠️  inspect_ai exceeded {_wait_budget_s}s wall-clock budget "
                    f"for {task.name}; process group killed."
                )
                return False, {}, _hang_duration_s

            progress_bar.close()

            duration_s = time.time() - start_time
            raw_output = "".join(raw_output_lines)

            # Parse scores
            scores = self._parse_scores_from_output(raw_output)

            # Locate .eval file
            eval_files = list(log_dir.glob("*.eval"))
            eval_log_path = str(eval_files[0]) if eval_files else None

            # BLOCKER 5: EDS-aware metric ingestion. The legacy
            # ``_parse_scores_from_output`` helper above splits stdout
            # naively and can ingest box-drawing delimiters (``│``)
            # plus error log lines as numeric metric keys, which then
            # corrupts ``configs/models.yaml``. For EDS benchmarks
            # (MiniCorp / eds_minicorp / eds) we instead ingest the
            # Inspect ``.eval`` log artifact directly through the
            # exporters module's :func:`extract_eds_metrics` helper,
            # which guarantees clean numeric EDS aggregate keys
            # (see :data:`evalsbench.exporters.EDS_AGGREGATE_KEYS`).
            # Legacy non-EDS benchmarks keep their existing parsing
            # path unchanged (the user's original code path is
            # preserved verbatim for every other registry entry).
            _eds_aggregates: Dict[str, Any] = {}
            _eds_eval_log_path: Optional[str] = None
            if task_key in EDS_BENCHMARK_KEYS:
                _eds_eval_log_path = eval_log_path
                if not _eds_eval_log_path and eval_files:
                    _eds_eval_log_path = str(eval_files[0])
                try:
                    _eds_resolved = _load_eval_log_for_extract(_eds_eval_log_path)
                    _eds_aggregates = extract_eds_metrics(_eds_resolved)
                except Exception as _eds_err:
                    # Offline-first contract: a broken EDS ingest
                    # must never fail the benchmark run. Fall back
                    # to the legacy stdout-splitter scores so the
                    # rest of the pipeline still sees a payload.
                    _eds_aggregates = {}
                    print(
                        f"Warning: EDS metric ingestion failed for "
                        f"{task.name}: {_eds_err}"
                    )
                if _eds_aggregates:
                    # Overlay ONLY numeric aggregate keys onto the
                    # score dict so models.yaml, write_benchmark_report,
                    # and downstream consumers see canonical EDS keys
                    # rather than anything the stdout splitter grabbed.
                    scores = {
                        key: value
                        for key, value in _eds_aggregates.items()
                        if isinstance(value, (int, float))
                    }

            # Generate structured reports
            report_file = write_benchmark_report(
                log_dir=log_dir,
                model_name=self.model_name,
                endpoint_url=self.endpoint_url,
                benchmark_name=task.name,
                samples_count=samples,
                duration_s=duration_s,
                raw_output=raw_output,
                scores=scores,
                eval_log_path=eval_log_path,
            )

            # BLOCKER 4: invoke ``write_eds_scorecard`` for EDS
            # benchmarks so the renderer can populate
            # ``report.eds.md`` and ``results.eds.json`` from the
            # run's log directory. Wrapped in try/except so export
            # failures degrade to a warning rather than failing the
            # benchmark run (offline-first contract).
            if task_key in EDS_BENCHMARK_KEYS:
                try:
                    _eds_scorecard_payload = (
                        _eds_aggregates
                        if _eds_aggregates
                        else scores
                    )
                    write_eds_scorecard(
                        log_dir=log_dir,
                        benchmark_name=task.name,
                        aggregates=_eds_scorecard_payload,
                        model_name=self.model_name,
                        endpoint_url=self.endpoint_url,
                        raw_path=_eds_eval_log_path or eval_log_path,
                    )
                except Exception as _eds_err:
                    print(
                        f"Warning: EDS scorecard export failed for "
                        f"{task.name}: {_eds_err}"
                    )

            # Update dynamic models.yaml
            update_models_yaml(
                model_name=self.model_name,
                endpoint_url=self.endpoint_url,
                benchmark_name=task.name,
                scores=scores,
                duration_s=duration_s,
            )

            # Sync to ChAI Vault if enabled
            if self.chai_sync:
                sync_to_chai_vault(self.model_name, report_file, task.name)

            print(f"\n✅ {task.name} Completed in {duration_s:.1f}s")
            print(f"📝 Report saved to: {report_file}")
            return proc.returncode == 0, scores, duration_s

        finally:
            # 4. Polite Docker sandbox and dangling image cleanup
            if task.docker_required:
                prune_inspect_containers()
            # R5 orphan-process guard. ``subprocess.Popen`` was
            # spawned with ``start_new_session=True`` so it owns
            # its own process group. If ``run_benchmark`` exits via
            # ``KeyboardInterrupt`` or any unhandled exception while
            # the child is still alive, the group would otherwise
            # survive as an orphan, holding GPU/CPU compute and
            # blocking the next benchmark from launching. Reap the
            # group defensively without ever masking the original
            # exception. Safe even when ``proc`` was never assigned
            # (``subprocess.Popen`` raised): ``proc`` is pre-bound to
            # ``None`` above the outer ``try``.
            if proc is not None:
                try:
                    if proc.poll() is None:
                        _terminate_process_group(proc)
                except Exception:
                    # Never let the guard's own failure mask the
                    # real exception that triggered the finally.
                    pass

    def _parse_scores_from_output(self, text: str) -> Dict[str, Any]:
        """Extracts numerical metric key-values from Inspect AI tables."""
        scores = {}
        for line in text.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("─") or line_str.startswith("═") or "total time:" in line_str:
                continue
            parts = line_str.split()
            if len(parts) >= 2:
                key, val = parts[0], parts[1]
                try:
                    scores[key] = float(val)
                except ValueError:
                    pass
        return scores
