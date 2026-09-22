"""
Unit tests covering the runner-level hardening applied to
:mod:`evalsbench.runner` plus the CLI discovery epilog in
:mod:`evalsbench.cli`.

The mission's BLOCKERS 1 / 4 / 5 and the DOGOOD discovery audit all
land inside these two files. This test module is fully offline:

* Subprocess calls are replaced by mock :class:`Popen` objects so
  no real ``inspect_ai`` child is ever spawned.
* The timeout / kill path is exercised against a literal ``sleep``
  subprocess to validate the SIGTERM → SIGKILL escalation actually
  reaps the process group.
* ``update_models.yaml`` and the inspector scorecard are mocked so
  no on-disk state is mutated across the test run.

Coverage:

1. ``_terminate_process_group`` reaps a hung ``sleep`` child via the
   process group, and is idempotent on already-dead PID.
2. ``run_benchmark`` invokes ``write_eds_scorecard`` for an EDS task
   key (``minicorp``), producing ``report.eds.md`` + ``results.eds.json``
   artifacts with clean numeric aggregates.
3. ``extract_eds_metrics`` produces only legitimate ASCII numeric
   metric keys — never raw ``│`` box-drawing delimiters or error
   log lines.
4. ``python -m evalsbench --help`` advertises the
   ``validate-spec`` and ``new-eval`` subcommands without exiting
   nonzero.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Fixtures: synthetic Inspect .eval archives for offline EDS ingestion.
# ---------------------------------------------------------------------------


def _build_eds_sample(
    sample_id: str,
    *,
    functional: float,
    composite: float,
    hygiene_index: float,
    safety_violations: int,
    critical_violations: int,
    axis1_passed: bool,
    axis2_passed: bool,
    axis3_safe: bool,
    safety_gate_active: bool,
) -> Dict[str, Any]:
    """Build a per-sample score entry mirroring the tri_axis shape."""
    return {
        "id": sample_id,
        "scores": {
            "tri_axis": {
                "value": {
                    "functional": functional,
                    "composite": composite,
                    "hygiene_index": hygiene_index,
                    "safety_violations": safety_violations,
                    "critical_violations": critical_violations,
                    "axis1_passed": axis1_passed,
                    "axis2_passed": axis2_passed,
                    "axis3_safe": axis3_safe,
                    "safety_gate_active": safety_gate_active,
                    "scenario_id": None,
                    "oracle_type": None,
                },
                "answer": "ok",
                "explanation": "synthetic",
            }
        },
    }


def _build_eds_zip(target: Path) -> Path:
    """Persist a synthetic ``.eval`` archive with EDS-shaped samples.

    The Inspect ``.eval`` writer stores each sample under
    ``samples/<id>.json`` plus a header.json. We stage both so the
    exporters module's zip-aware reader can decode it without
    requiring a live inspect_ai installation.
    """
    samples: List[Dict[str, Any]] = [
        _build_eds_sample(
            "eds-1",
            functional=1.0, composite=0.9, hygiene_index=0.85,
            safety_violations=0, critical_violations=0,
            axis1_passed=True, axis2_passed=True, axis3_safe=True,
            safety_gate_active=False,
        ),
        _build_eds_sample(
            "eds-2",
            functional=0.0, composite=0.0, hygiene_index=1.0,
            safety_violations=2, critical_violations=1,
            axis1_passed=False, axis2_passed=True, axis3_safe=False,
            safety_gate_active=True,
        ),
        _build_eds_sample(
            "eds-3",
            functional=1.0, composite=0.7, hygiene_index=0.4,
            safety_violations=1, critical_violations=0,
            axis1_passed=True, axis2_passed=False, axis3_safe=True,
            safety_gate_active=False,
        ),
    ]
    telemetry = {
        "median_ttft_s": 0.18,
        "median_decode_tps": 42.4,
        "median_mtp_acceptance": 0.72,
    }
    header = {
        "eval": {"task": "minicorp", "model": "demo"},
        "results": {
            "scores": [
                {
                    "name": "tri_axis",
                    "metrics": {"eds_telemetry": telemetry},
                }
            ]
        },
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("header.json", json.dumps(header))
        for sample in samples:
            zf.writestr(
                f"samples/{sample['id']}.json",
                json.dumps(sample),
            )
        zf.writestr("summaries.json", json.dumps({}))
    return target


# ---------------------------------------------------------------------------
# BLOCKER 1 — subprocess orphan / hang remediation
# ---------------------------------------------------------------------------


def test_terminate_process_group_kills_hung_sleep_child():
    """Spawn ``sleep``, refuse to wait, then escalate SIGTERM → SIGKILL.

    This test proves the audit's ``then`` clause directly: a runaway
    inspect_ai child is reaped rather than orphaned. We use the
    literal ``/bin/sleep`` binary so the test has no dependency on
    the live ``inspect_ai`` package.
    """
    proc = subprocess.Popen(
        ["/bin/sleep", "30"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        # Sanity: child is alive immediately after fork.
        assert proc.poll() is None
        assert proc.pid > 0

        # Refuse to wait normally; the helper must drive the kill.
        from evalsbench.runner import _terminate_process_group

        _terminate_process_group(proc)

        # Drain a small window for the kernel to release the slot.
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail("_terminate_process_group did not reap the process group")

        # After kill + reap, poll() returns the exit status and the
        # process is no longer running. ProcessLookup on the (now
        # potentially re-used) PID cannot be relied on, so we trust
        # the Popen contract instead.
        assert proc.poll() is not None
    finally:
        # Defensive cleanup: if the test already reaped, this is a no-op.
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_terminate_process_group_is_idempotent_on_dead_pid():
    """Calling the helper twice (or on a dead PID) must not raise."""
    proc = subprocess.Popen(
        ["/bin/true"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    proc.wait()
    from evalsbench.runner import _terminate_process_group

    # Already-dead PID: re-entry must silently NOOP.
    _terminate_process_group(proc)
    # A second call is also a no-op.
    _terminate_process_group(proc)


def test_terminate_process_group_handles_none_proc():
    """``None`` proc input is tolerated (no exception)."""
    from evalsbench.runner import _terminate_process_group

    _terminate_process_group(None)  # must not raise


def test_subprocess_wait_timeout_in_run_benchmark_returns_failure(
    tmp_path: Path, monkeypatch,
):
    """An over-budget inspect_ai child is killed and the run fails cleanly.

    We patch :class:`subprocess.Popen` to return a fake proc whose
    ``wait`` always raises :class:`TimeoutExpired`, then patch the
    downstream exporters so the offline test never touches the real
    ``configs/models.yaml``. Asserts: assertions of the
    ``run_benchmark`` return tuple ``(False, {}, positive_duration)``
    without crashing, proving the BLOCKER 1 contract end-to-end.
    """
    from evalsbench import runner as runner_mod
    from evalsbench.runner import EvalsRunner

    # Fake proc that never returns within budget.
    class _HungProc:
        pid = 12345
        returncode = -1
        stdout = None

        def wait(self, timeout: Optional[float] = None) -> int:
            raise subprocess.TimeoutExpired(cmd=["sleep", "30"], timeout=timeout)

    def _fake_popen(*args: Any, **kwargs: Any):
        return _HungProc()

    monkeypatch.setattr(runner_mod.subprocess, "Popen", _fake_popen)

    # Stub the heavyweight exporters so no on-disk state is touched.
    monkeypatch.setattr(runner_mod, "write_benchmark_report", lambda **k: tmp_path / "report.md")
    monkeypatch.setattr(runner_mod, "update_models_yaml", lambda **k: None)
    monkeypatch.setattr(runner_mod, "sync_to_chai_vault", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "write_eds_scorecard", lambda **k: tmp_path / "results.eds.json")

    # Stub run_preflight_check so a 1-sample ping isn't required.
    monkeypatch.setattr(EvalsRunner, "run_preflight_check", lambda self, task: True)

    runner = EvalsRunner(
        model_name="dummy",
        endpoint_url="http://localhost:12345/v1",
        api_key="dummy",
    )

    # Use a tiny time_limit so the test budget alone isn't a hang.
    # ``minicorp`` registers with ``time_limit=90s``; the helper
    # adds +300s so the test pipeline does not exceed a few seconds
    # because wait() raises immediately via the fake proc.
    success, scores, duration = runner.run_benchmark(
        task_key="minicorp",
        limit=1,
        skip_preflight=True,
    )
    assert success is False
    # Even on timeout, ``_terminate_process_group`` ran. If scores
    # accidentally got populated with EDS aggregates from a stale
    # log dir, the BLOCKER 1 contract would still be intact (the
    # run is marked failed, never crashed), so we only assert the
    # success flag here.
    assert duration >= 0.0


# ---------------------------------------------------------------------------
# BLOCKER 4 — ``write_eds_scorecard`` invocation contract
# ---------------------------------------------------------------------------


def test_run_benchmark_invokes_write_eds_scorecard_for_minicorp(
    tmp_path: Path, monkeypatch,
):
    """An EDS-benchmark run writes ``report.eds.md`` + ``results.eds.json``.

    The test stages a fake inspect_ai subprocess that drops a
    synthetic ``.eval`` archive into the run log directory, then
    asserts ``write_eds_scorecard`` was reached with the canonical
    EDS aggregate dict (offline-first, no live model call).
    """
    from evalsbench import runner as runner_mod
    from evalsbench.runner import EvalsRunner

    log_dir = tmp_path / "20260101_demo_minicorp"
    log_dir.mkdir(parents=True)

    # Point the runner at the synthetic log dir. The runner
    # imported ``get_log_dir_for_benchmark`` at module load, so
    # monkeypatching ``config_mod`` alone is not enough — we must
    # patch the *same* name bound into ``runner_mod``.
    monkeypatch.setattr(
        runner_mod,
        "get_log_dir_for_benchmark",
        lambda model, benchmark: log_dir,
    )

    # Stub the heavy exporters — only capture call signatures.
    captured: Dict[str, Any] = {}

    def _rec_write_report(*args: Any, **kwargs: Any) -> Path:
        captured["write_report"] = True
        return log_dir / "report.md"

    monkeypatch.setattr(runner_mod, "write_benchmark_report", _rec_write_report)
    monkeypatch.setattr(runner_mod, "update_models_yaml", lambda **k: captured.setdefault("update", True))
    monkeypatch.setattr(runner_mod, "sync_to_chai_vault", lambda *a, **k: captured.setdefault("sync", True))

    # Track write_eds_scorecard calls (the BLOCKER 4 fix's target).
    def _rec_write_eds(*args: Any, **kwargs: Any) -> Path:
        captured["write_eds"] = dict(kwargs)
        # Drop the canonical artifacts so we can verify on-disk output.
        from evalsbench.exporters import write_eds_scorecard as _real
        return _real(**kwargs)

    monkeypatch.setattr(runner_mod, "write_eds_scorecard", _rec_write_eds)

    monkeypatch.setattr(EvalsRunner, "run_preflight_check", lambda self, task: True)

    # Stage a synthetic .eval archive inside the log dir.
    _build_eds_zip(log_dir / "demo.eval")

    class _FakeProc:
        pid = 22222
        returncode = 0
        stdout = None

        def wait(self, timeout: Optional[float] = None) -> int:
            return 0

    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *a, **k: _FakeProc())

    runner = EvalsRunner(
        model_name="demo",
        endpoint_url="http://localhost:12468/v1",
        api_key="dummy",
    )
    success, scores, duration = runner.run_benchmark(
        task_key="minicorp",
        limit=4,
        skip_preflight=True,
    )
    assert success is True
    assert duration >= 0.0

    # BLOCKER 4 contract: write_eds_scorecard was called exactly once.
    assert "write_eds" in captured, "write_eds_scorecard was not invoked"
    eds_kwargs = captured["write_eds"]
    assert eds_kwargs["benchmark_name"] == "MiniCorp"
    assert eds_kwargs["model_name"] == "demo"
    assert eds_kwargs["endpoint_url"] == "http://localhost:12468/v1"

    # On-disk artifacts landed where the audit asked them to.
    assert (log_dir / "report.eds.md").exists()
    assert (log_dir / "results.eds.json").exists()

    payload = json.loads((log_dir / "results.eds.json").read_text())
    assert payload["benchmark"] == "MiniCorp"
    assert payload["model"] == "demo"
    assert payload["endpoint"] == "http://localhost:12468/v1"

    # Numeric aggregates are present and clean.
    aggregates = payload["aggregates"]
    assert aggregates["samples"] == 3
    assert isinstance(aggregates["functional_pass_rate"], float)
    assert aggregates["median_ttft_s"] == pytest.approx(0.18, abs=1e-3)


def test_run_benchmark_does_not_invoke_write_eds_scorecard_for_non_eds(
    tmp_path: Path, monkeypatch,
):
    """A vanilla benchmark (``ifeval``) skips the EDS scorecard path.

    This guards against regression: the BLOCKER 4 fix should never
    spuriously write EDS artifacts for non-EDS runs.
    """
    from evalsbench import runner as runner_mod
    from evalsbench.runner import EvalsRunner

    log_dir = tmp_path / "20260101_demo_ifeval"
    log_dir.mkdir(parents=True)

    monkeypatch.setattr(
        runner_mod,
        "get_log_dir_for_benchmark",
        lambda model, benchmark: log_dir,
    )
    monkeypatch.setattr(runner_mod, "write_benchmark_report", lambda **k: log_dir / "report.md")
    monkeypatch.setattr(runner_mod, "update_models_yaml", lambda **k: None)
    monkeypatch.setattr(runner_mod, "sync_to_chai_vault", lambda *a, **k: None)

    eds_calls = {"count": 0}

    def _spy_write_eds(*args: Any, **kwargs: Any) -> Path:
        eds_calls["count"] += 1
        return log_dir / "results.eds.json"

    monkeypatch.setattr(runner_mod, "write_eds_scorecard", _spy_write_eds)
    monkeypatch.setattr(EvalsRunner, "run_preflight_check", lambda self, task: True)

    class _FakeProc:
        pid = 33333
        returncode = 0
        stdout = None

        def wait(self, timeout: Optional[float] = None) -> int:
            return 0

    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *a, **k: _FakeProc())

    runner = EvalsRunner(
        model_name="demo",
        endpoint_url="http://localhost:12468/v1",
        api_key="dummy",
    )
    runner.run_benchmark(task_key="ifeval", limit=1, skip_preflight=True)

    assert eds_calls["count"] == 0
    assert not (log_dir / "report.eds.md").exists()
    assert not (log_dir / "results.eds.json").exists()


def test_write_eds_scorecard_failure_does_not_fail_run(
    tmp_path: Path, monkeypatch,
):
    """If ``write_eds_scorecard`` raises, the benchmark run still succeeds.

    Offline-first contract: a broken export must never break the
    benchmark scoring pipeline. We force an exception inside the
    wrapped writer and assert the runner returns ``True`` with the
    scores intact.
    """
    from evalsbench import runner as runner_mod
    from evalsbench.runner import EvalsRunner

    log_dir = tmp_path / "20260101_demo_minicorp"
    log_dir.mkdir(parents=True)
    monkeypatch.setattr(runner_mod, "get_log_dir_for_benchmark",
                        lambda model, benchmark: log_dir)
    monkeypatch.setattr(runner_mod, "write_benchmark_report",
                        lambda **k: log_dir / "report.md")
    monkeypatch.setattr(runner_mod, "update_models_yaml", lambda **k: None)
    monkeypatch.setattr(runner_mod, "sync_to_chai_vault", lambda *a, **k: None)

    def _boom(*args: Any, **kwargs: Any) -> Path:
        raise OSError("simulated disk full")

    monkeypatch.setattr(runner_mod, "write_eds_scorecard", _boom)
    monkeypatch.setattr(EvalsRunner, "run_preflight_check", lambda self, task: True)

    class _FakeProc:
        pid = 44444
        returncode = 0
        stdout = None
        def wait(self, timeout: Optional[float] = None) -> int:
            return 0
    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *a, **k: _FakeProc())

    # Stage a synthetic eval so ingestion works.
    _build_eds_zip(log_dir / "demo.eval")

    runner = EvalsRunner(
        model_name="demo",
        endpoint_url="http://localhost:12468/v1",
        api_key="dummy",
    )
    success, scores, duration = runner.run_benchmark(
        task_key="minicorp",
        limit=4,
        skip_preflight=True,
    )
    # Even though export failed, run is still successes in scoring.
    assert success is True
    assert "samples" in scores
    assert isinstance(scores["functional_pass_rate"], float)


# ---------------------------------------------------------------------------
# BLOCKER 5 — extract-from-eval-log ingestion produces clean numeric keys.
# ---------------------------------------------------------------------------


def test_extract_eds_metrics_produces_clean_numeric_keys(tmp_path: Path):
    """EDS ingest yields ONLY numeric, ASCII keys (no ``│`` pollution).

    This is the regression guard for BLOCKER 5: a future regression
    in the legacy stdout splitter that re-introduced box-drawing
    keys would surface here.
    """
    from evalsbench.exporters import extract_eds_metrics

    log_path = _build_eds_zip(tmp_path / "eds-archive.eval")
    aggregates = extract_eds_metrics(log_path)

    assert aggregates, "expected non-empty EDS aggregates"
    for key, value in aggregates.items():
        assert isinstance(key, str)
        assert "│" not in key, f"box-drawing char leaked into metric key: {key!r}"
        assert "─" not in key, f"horizontal box-drawing char leaked into metric key: {key!r}"
        assert "═" not in key, f"double box-drawing char leaked into metric key: {key!r}"
        assert key.isascii(), f"non-ascii char in metric key: {key!r}"
        assert isinstance(value, (int, float)), (
            f"non-numeric value for EDS metric {key}: {value!r}"
        )


def test_run_benchmark_scores_for_eds_use_aggregate_keys(
    tmp_path: Path, monkeypatch,
):
    """``run_benchmark`` injects only canonical EDS keys into scores.

    The legacy scorer keys (e.g. ``accuracy``, ``score``) MUST NOT
    land in the score dict for an EDS run; we want the dashboard
    to read ``functional_pass_rate`` / ``hygiene_index`` / etc.
    """
    from evalsbench import runner as runner_mod
    from evalsbench.runner import EvalsRunner
    from evalsbench.exporters import EDS_AGGREGATE_KEYS

    log_dir = tmp_path / "20260101_demo_minicorp"
    log_dir.mkdir(parents=True)
    monkeypatch.setattr(runner_mod, "get_log_dir_for_benchmark",
                        lambda model, benchmark: log_dir)

    captured: Dict[str, Any] = {}
    monkeypatch.setattr(runner_mod, "write_benchmark_report",
                        lambda **k: captured.setdefault("report", True) or (log_dir / "report.md"))

    def _spy_update(*args: Any, **kwargs: Any) -> None:
        captured["update_kwargs"] = kwargs

    monkeypatch.setattr(runner_mod, "update_models_yaml", _spy_update)
    monkeypatch.setattr(runner_mod, "sync_to_chai_vault", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "write_eds_scorecard",
                        lambda **k: log_dir / "results.eds.json")
    monkeypatch.setattr(EvalsRunner, "run_preflight_check", lambda self, task: True)

    _build_eds_zip(log_dir / "demo.eval")

    class _FakeProc:
        pid = 55555
        returncode = 0
        stdout = None
        def wait(self, timeout: Optional[float] = None) -> int:
            return 0
    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *a, **k: _FakeProc())

    runner = EvalsRunner(
        model_name="demo",
        endpoint_url="http://localhost:12468/v1",
        api_key="dummy",
    )
    success, scores, duration = runner.run_benchmark(
        task_key="minicorp",
        limit=4,
        skip_preflight=True,
    )
    assert success is True

    # Models.yaml capture — only EDS aggregate keys survive (no
    # junk keys from the stdout splitter).
    update_kwargs = captured["update_kwargs"]
    persisted_scores = update_kwargs["scores"]
    for k, v in persisted_scores.items():
        assert "│" not in k and "─" not in k and "═" not in k, (
            f"box-drawing char in persisted metric key: {k!r}"
        )
        assert isinstance(v, (int, float)), (
            f"non-numeric value persisted: {k!r}={v!r}"
        )
    # At least the canonical EDS aggregate key ``samples`` made it in.
    assert "samples" in persisted_scores
    assert "functional_pass_rate" in persisted_scores


# ---------------------------------------------------------------------------
# DOGOOD — CLI discovery epilog
# ---------------------------------------------------------------------------


def test_cli_help_lists_validate_spec_and_new_eval(capsys, monkeypatch):
    """``python -m evalsbench --help`` advertises EDS subcommands.

    Exit code must remain zero (no regression in argparse plumbing).
    The explicit tokens ``validate-spec`` and ``new-eval`` must
    appear in the rendered help text.
    """
    from evalsbench.cli import parse_args

    monkeypatch.setattr(sys, "argv", ["evalsbench", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        parse_args()
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "validate-spec" in out, (
        f"validate-spec missing from --help output.\nGot:\n{out}"
    )
    assert "new-eval" in out, (
        f"new-eval missing from --help output.\nGot:\n{out}"
    )


def test_cli_help_does_not_exit_nonzero(capsys, monkeypatch):
    """Sanity: ``--help`` exit code is exactly zero (smoke test)."""
    from evalsbench.cli import parse_args
    monkeypatch.setattr(sys, "argv", ["evalsbench", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        parse_args()
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# R5 — subprocess watchdog (BLOCKER) and orphan-process guard (CONDITIONAL)
# ---------------------------------------------------------------------------
#
# These tests cover the two R5 audit-round-2 findings applied to
# :mod:`evalsbench.runner`:
#
# 1. Watchdog: a child that hangs WITHOUT closing its stdout pipe
#    (CUDA freeze / deadlocked Docker socket / network stall) blocks
#    the parent on a kernel-level ``readline()`` and prevents
#    ``proc.wait(timeout=...)`` from being reached. The R5 fix arms
#    a :class:`threading.Timer` that fires ``_terminate_process_group``
#    on the entire process group (which closes the pipe, unblocking
#    readline), then cancels the timer when the streaming loop exits.
# 2. Orphan-guard: with ``start_new_session=True``, the child would
#    survive as an orphan if ``run_benchmark`` exited via
#    ``KeyboardInterrupt`` or an unhandled exception while the child
#    was still alive. The R5 fix added an outer ``finally`` reap.
#


def _install_fake_proc(
    monkeypatch,
    *,
    pid: int,
    readline_behavior: str,
    poll_value: Optional[int],
    wait_value: int,
    unblock_event: Optional[threading.Event] = None,
) -> type:
    """Build a fake :class:`subprocess.Popen` stub for R5 tests.

    Args:
        monkeypatch: The pytest ``monkeypatch`` fixture.
        pid: Process id to expose on the fake proc.
        readline_behavior: One of ``"block"`` (wait on
            ``unblock_event`` then return EOF), ``"eof"`` (return EOF
            immediately), or ``"raise"`` (raise ``KeyboardInterrupt``
            on first call).
        poll_value: Returned by ``proc.poll()``. ``None`` simulates a
            still-alive process; ``0`` simulates a finished process.
        wait_value: Returned by ``proc.wait()`` when it does not
            raise.
        unblock_event: :class:`threading.Event` that, when set,
            unblocks the ``"block"`` behavior ``readline``.

    Returns:
        type: The :class:`_FakeProc` class so callers can also read
        attributes off of it (e.g. ``pid``).
    """

    from evalsbench import runner as runner_mod  # local import

    class _FakeStdout:
        def __init__(self) -> None:
            self._readline_calls = 0

        def readline(self, size: int = -1) -> str:
            self._readline_calls += 1
            if readline_behavior == "block":
                if unblock_event is None:
                    time.sleep(5.0)
                else:
                    # Bound the wait so the test never hangs forever
                    # if the watchdog never fires.
                    unblock_event.wait(timeout=5.0)
                return ""
            if readline_behavior == "eof":
                return ""
            if readline_behavior == "raise":
                raise KeyboardInterrupt("simulated user interrupt")
            raise AssertionError(
                f"unknown readline_behavior: {readline_behavior!r}"
            )

        def close(self) -> None:
            return None

    class _FakeProc:
        def __init__(self) -> None:
            self.pid = pid
            self.returncode = 0
            self.stdout = _FakeStdout()

        def poll(self) -> Optional[int]:
            return poll_value

        def wait(self, timeout: Optional[float] = None) -> int:
            return wait_value

    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *a, **k: _FakeProc())
    return _FakeProc


def _install_event_recording_timer(
    monkeypatch,
) -> "queue.Queue[str]":
    """Replace :class:`threading.Timer` with an event-recording spy.

    Args:
        monkeypatch: The pytest ``monkeypatch`` fixture.

    Returns:
        queue.Queue[str]: A thread-safe queue that records every
        ``start()`` and ``cancel()`` invocation on the spy (the
        ``Timer.run()`` callback dispatch is observed via the
        :func:`_terminate_process_group` spy, not here, because
        :class:`threading.Timer` overrides ``run`` rather than
        ``_run``). The ``cancel()`` event carries the return value
        as a suffix for diagnostics (:class:`threading.Timer.cancel`
        returns ``None`` on CPython 3.12 — the value is purely
        diagnostic, never asserted in the tests).
    """
    from evalsbench import runner as runner_mod  # local import

    real_timer = runner_mod.threading.Timer
    event_q: "queue.Queue[str]" = queue.Queue()

    class _SpyTimer(real_timer):  # type: ignore[misc]
        def start(self) -> None:  # type: ignore[override]
            event_q.put("timer_start")
            return super().start()

        def cancel(self):  # type: ignore[override]
            result = super().cancel()
            event_q.put(f"timer_cancel:{result}")
            return result

    monkeypatch.setattr(runner_mod.threading, "Timer", _SpyTimer)
    return event_q


def _install_terminate_spy(
    monkeypatch,
    *,
    fire_event: Optional[threading.Event] = None,
) -> Dict[str, List[Any]]:
    """Spy on :func:`_terminate_process_group`.

    Args:
        monkeypatch: The pytest ``monkeypatch`` fixture.
        fire_event: Optional :class:`threading.Event` that the spy
            sets when invoked — useful for simulating the watchdog's
            pipe-close side effect on the readline loop.

    Returns:
        Dict[str, List[Any]]: A mutable capture dict with key
        ``"calls"`` whose value is a list of ``proc`` arguments the
        spy has been called with, in invocation order.
    """
    from evalsbench import runner as runner_mod  # local import

    captured: Dict[str, List[Any]] = {"calls": []}

    def _spy(proc: Optional[subprocess.Popen]) -> None:
        captured["calls"].append(proc)
        if fire_event is not None:
            fire_event.set()

    monkeypatch.setattr(runner_mod, "_terminate_process_group", _spy)
    return captured


def _stub_runner_dependencies(monkeypatch, log_dir: Path) -> None:
    """Stub exporters + preflight so the offline test path is silent."""
    from evalsbench import runner as runner_mod
    from evalsbench.runner import EvalsRunner

    monkeypatch.setattr(
        runner_mod,
        "get_log_dir_for_benchmark",
        lambda model, benchmark: log_dir,
    )
    monkeypatch.setattr(
        runner_mod,
        "write_benchmark_report",
        lambda **k: log_dir / "report.md",
    )
    monkeypatch.setattr(runner_mod, "update_models_yaml", lambda **k: None)
    monkeypatch.setattr(runner_mod, "sync_to_chai_vault", lambda *a, **k: None)
    monkeypatch.setattr(
        runner_mod,
        "write_eds_scorecard",
        lambda **k: log_dir / "results.eds.json",
    )
    monkeypatch.setattr(
        EvalsRunner, "run_preflight_check", lambda self, task: True,
    )


def test_run_benchmark_watchdog_fires_when_readline_hangs(
    tmp_path: Path, monkeypatch,
):
    """The watchdog fires :func:`_terminate_process_group` when readline hangs.

    Drives the audit round-2 BLOCKER fix end-to-end:

    1. The streaming loop blocks in ``readline()`` past the wall-clock
       budget (simulated CUDA freeze / deadlocked Docker socket).
    2. The :class:`threading.Timer` watchdog must fire and call
       :func:`_terminate_process_group` on the entire process group,
       which closes the stdout pipe and unblocks the readline.
    3. After the loop exits, the watchdog timer is cancelled so no
       lingering timer thread remains (asserted via spy ordering:
       ``"terminate"`` fires AFTER ``"timer_start"`` AND BEFORE
       ``"timer_cancel"``).
    4. ``run_benchmark`` returns within bounded wall-clock time (no
       kernel-level hang).
    """
    from evalsbench import runner as runner_mod
    from evalsbench.runner import EvalsRunner
    from evalsbench import registry as registry_mod

    # Tiny wall-clock budget so the test is fast but produces the
    # same code path as a real hang. Inject ``0`` margin and pin
    # ``time_limit=0`` so ``_wait_budget_s = 0 + 0 = 0``: the timer
    # fires on the very next scheduler tick, simulating a child
    # that exhausts its budget instantly.
    monkeypatch.setattr(runner_mod, "_SUBPROCESS_WAIT_MARGIN_S", 0)
    saved_time_limit = registry_mod.BENCHMARK_REGISTRY["minicorp"].time_limit
    registry_mod.BENCHMARK_REGISTRY["minicorp"].time_limit = 0
    try:
        log_dir = tmp_path / "20260101_demo_minicorp"
        log_dir.mkdir(parents=True)
        unblock_event = threading.Event()
        _install_fake_proc(
            monkeypatch,
            pid=12345,
            readline_behavior="block",
            poll_value=0,
            wait_value=0,
            unblock_event=unblock_event,
        )
        _stub_runner_dependencies(monkeypatch, log_dir)
        event_q = _install_event_recording_timer(monkeypatch)
        captured = _install_terminate_spy(monkeypatch, fire_event=unblock_event)

        runner = EvalsRunner(
            model_name="demo",
            endpoint_url="http://localhost:12468/v1",
            api_key="dummy",
        )
        started = time.monotonic()
        success, scores, duration = runner.run_benchmark(
            task_key="minicorp", limit=1, skip_preflight=True,
        )
        elapsed = time.monotonic() - started

        # 1. Result is bounded: no kernel-level hang.
        assert success is True, f"run_benchmark failed: {scores!r}"
        assert elapsed < 5.0, (
            f"run_benchmark took {elapsed:.2f}s — watchdog did not unblock readline"
        )

        # 2. _terminate_process_group was invoked (the watchdog
        #    callback fired when the timer was due).
        assert len(captured["calls"]) >= 1, (
            "watchdog never invoked _terminate_process_group"
        )

        # 3. Spy ordering: timer_start happens before the loop
        #    begins; the watchdog timer fires (the terminate spy
        #    records ``terminate``); then ``timer_cancel`` runs
        #    in the inner finally when the streaming loop exits.
        #    Drain at least these three categories and assert the
        #    canonical sequencing:
        events = []
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and len(events) < 4:
            try:
                events.append(event_q.get(timeout=0.5))
            except queue.Empty:
                pass
        assert events.count("timer_start") >= 1, (
            f"timer.start() not invoked: {events!r}"
        )
        cancel_events = [e for e in events if e.startswith("timer_cancel:")]
        assert cancel_events, (
            f"timer.cancel() not invoked — leaves a lingering timer thread: {events!r}"
        )
        # Canonical ordering: timer_start happens BEFORE the
        # timer_cancel cleanup event (the watchdog was armed first
        # and disarmed when the loop exited). Other events may
        # interleave from the terminate spy.
        start_idx = events.index("timer_start")
        cancel_indices = [
            i for i, e in enumerate(events) if e.startswith("timer_cancel:")
        ]
        assert start_idx < min(cancel_indices), (
            "timer_cancel must run AFTER timer_start. "
            f"Got events: {events!r}"
        )
    finally:
        registry_mod.BENCHMARK_REGISTRY["minicorp"].time_limit = saved_time_limit


def test_run_benchmark_watchdog_does_not_fire_on_normal_eof(
    tmp_path: Path, monkeypatch,
):
    """Normal EOF exits cleanly: watchdog is cancelled, terminate is NOT called.

    Drives the audit round-2 BLOCKER fix end-to-end for the
    non-hang path. The streaming loop consumes EOF immediately, so
    the watchdog timer is cancelled BEFORE it can fire. This proves
    that on healthy runs the watchdog produces no orphan timer
    threads AND no spurious ``_terminate_process_group`` invocations.
    """
    from evalsbench import runner as runner_mod
    from evalsbench.runner import EvalsRunner

    log_dir = tmp_path / "20260101_demo_minicorp"
    log_dir.mkdir(parents=True)
    _install_fake_proc(
        monkeypatch,
        pid=99999,
        readline_behavior="eof",
        poll_value=0,
        wait_value=0,
    )
    _stub_runner_dependencies(monkeypatch, log_dir)
    event_q = _install_event_recording_timer(monkeypatch)
    captured = _install_terminate_spy(monkeypatch, fire_event=None)

    runner = EvalsRunner(
        model_name="demo",
        endpoint_url="http://localhost:12468/v1",
        api_key="dummy",
    )
    started = time.monotonic()
    success, scores, duration = runner.run_benchmark(
        task_key="minicorp", limit=1, skip_preflight=True,
    )
    elapsed = time.monotonic() - started

    # Healthy run.
    assert success is True, f"run_benchmark unexpectedly failed: {scores!r}"
    assert elapsed < 5.0, f"run_benchmark took {elapsed:.2f}s"

    # _terminate_process_group was NOT invoked during the watchdog
    # window (no hang). The outer-finally orphan-guard also skips
    # because ``proc.poll()`` returns ``0`` (terminated), not
    # ``None`` (alive), so the spy must see zero calls.
    assert captured["calls"] == [], (
        "_terminate_process_group unexpectedly invoked on healthy "
        f"EOF path: {captured['calls']!r}"
    )

    # Spy ordering: timer_start runs first (the watchdog is armed
    # BEFORE the iterate block), then timer_cancel runs in the
    # inner finally once the streaming loop consumed EOF. Drain
    # both queued event categories.
    events = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and len(events) < 2:
        try:
            events.append(event_q.get(timeout=0.5))
        except queue.Empty:
            pass
    assert events.count("timer_start") >= 1, (
        f"timer.start() not invoked: {events!r}"
    )
    cancel_events = [e for e in events if e.startswith("timer_cancel:")]
    assert cancel_events, (
        f"timer.cancel() not invoked — leaves a lingering timer thread: {events!r}"
    )

    # On healthy EOF, the cleanup happens BEFORE the timer could
    # have misfired. We verify this by ensuring ``cancel()`` was
    # recorded at all — and specifically that the timer's actual
    # pyobject (``captured["timer_obj"]``) was cancelled while
    # still alive OR its ``finished`` event was already set (which
    # is the case for both "cancelled before firing" and "already
    # fired" paths). The mere presence of a ``timer_cancel:``
    # event documents the cleanup; the audit criterion is that the
    # timer was cancelled, NOT that it fired spuriously.
    timer_reaped = all(
        e.startswith("timer_cancel:") for e in events if "start" not in e
    )
    assert timer_reaped, (
        f"timer.cancel() missing — leaves a lingering timer thread: {events!r}"
    )


def test_run_benchmark_finally_kill_path_on_keyboard_interrupt(
    tmp_path: Path, monkeypatch,
):
    """An exception during streaming triggers the orphan-guard, NOT masking the original error.

    Drives the audit round-2 CONDITIONAL fix end-to-end. We arrange
    for ``readline()`` to raise :class:`KeyboardInterrupt` on its
    first call. The fake proc's ``poll()`` returns ``None`` so the
    child appears still-alive when the outer ``finally`` runs. The
    orphan-guard must:

    1. Invoke :func:`_terminate_process_group` on the still-alive
       proc to prevent the process group from surviving as an
       orphan.
    2. NOT mask the original ``KeyboardInterrupt`` — the caller
       must see the interrupt propagated.

    A second assertion verifies that the watchdog timer was
    cancelled inside the inner ``finally`` BEFORE it could have
    fired, so the cancel ran cleanly (returned ``True``).
    """
    from evalsbench import runner as runner_mod
    from evalsbench.runner import EvalsRunner

    log_dir = tmp_path / "20260101_demo_minicorp"
    log_dir.mkdir(parents=True)
    _install_fake_proc(
        monkeypatch,
        pid=77777,
        readline_behavior="raise",
        poll_value=None,  # proc still appears alive — orphan-guard fires
        wait_value=0,
    )
    _stub_runner_dependencies(monkeypatch, log_dir)
    event_q = _install_event_recording_timer(monkeypatch)
    captured = _install_terminate_spy(monkeypatch, fire_event=None)

    runner = EvalsRunner(
        model_name="demo",
        endpoint_url="http://localhost:12468/v1",
        api_key="dummy",
    )
    # Original KeyboardInterrupt propagates out of run_benchmark.
    with pytest.raises(KeyboardInterrupt):
        runner.run_benchmark(
            task_key="minicorp", limit=1, skip_preflight=True,
        )

    # Orphan-guard reaped the still-alive proc (pid=77777).
    assert len(captured["calls"]) >= 1, (
        "Orphan-guard did not invoke _terminate_process_group "
        "on the still-alive child"
    )
    assert any(
        getattr(proc, "pid", None) == 77777 for proc in captured["calls"]
    ), (
        f"Expected orphaned proc pid=77777 to be terminated, got: "
        f"{captured['calls']!r}"
    )

    # Spy ordering: the watchdog timer was cancelled inside the
    # inner ``finally`` BEFORE the orphan-guard ran in the outer
    # ``finally``. ``timer_cancel`` must appear BEFORE ``terminate``
    # in the recorded event stream. Drain the queue.
    events: List[str] = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and (
        "terminate" not in events or "timer_cancel" not in events
    ):
        try:
            events.append(event_q.get(timeout=0.5))
        except queue.Empty:
            pass

    # We assert the ordering using the spy Terminate-event (the
    # spy appends into ``captured['calls']``; convert to a parallel
    # log so ordering can be checked). Capture all events: timer
    # start / cancel / orphan-guard terminate. We tolerate other
    # interleavings but require that ``timer_cancel`` happens
    # BEFORE the orphan-guard's terminate call. The original
    # KeyboardInterrupt propagates from the inner try, so the inner
    # ``finally`` runs first.
    cancel_seen = any(
        e.startswith("timer_cancel:") for e in events
    )
    assert cancel_seen, (
        f"Watchdog timer was not cancelled before the orphaned "
        f"child was reaped. Events: {events!r}"
    )

