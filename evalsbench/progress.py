"""
Real-time telemetry and progress engine for EvalsBench.

Implements the V2 :class:`LiveTelemetryMonitor` (PRD §5): a dual-row
terminal renderer that shows sample completion progress, transparent
scoring mode (Immediate vs Deferred), and per-question hardware
telemetry — prompt token volume with KV-cache hit percentage, TTFT /
prefill latency, decode throughput, speculative decoding (MTP) draft
acceptance, and multi-stream slot saturation.

The legacy :class:`LiveProgressBar` is retained for backward
compatibility with existing callers and tests; the runner now drives
:class:`LiveTelemetryMonitor` instead.
"""

import sys
import time
import re
from typing import Any, Dict, List, Optional, Tuple


class LiveTelemetryMonitor:
    """
    Dual-row live monitor: progress row + telemetry card row.

    Handles both interactive TTY terminals (in-place multi-row redraw)
    and non-TTY agent transcripts (milestone summaries at 20% steps and
    on completion).

    Scoring mode transparency (PRD §5.1):

    * ``immediate`` — running accuracy is printed per completed sample
      (``Acc: 87.5% (7/8)``) and the last sample verdict is shown.
    * ``deferred`` — the monitor explicitly reports
      ``Scoring: Deferred (Batch Graded at Run Conclusion) | Status:
      RECORDED (Pending Grade)`` instead of a running accuracy figure.
    """

    #: Bar width for the progress row.
    BAR_LEN = 24

    def __init__(
        self,
        task_name: str,
        total_samples: int,
        scoring_mode: str = "deferred",
        is_tty: Optional[bool] = None,
        model_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        max_connections: int = 1,
    ):
        self.task_name = task_name
        self.total_samples = max(total_samples, 1)
        self.scoring_mode = scoring_mode if scoring_mode in ("immediate", "deferred") else "deferred"
        self.is_tty = sys.stdout.isatty() if is_tty is None else is_tty
        self.model_name = model_name
        self.endpoint_url = endpoint_url
        self.max_connections = max(1, max_connections)

        self.completed_samples = 0
        self.start_time = time.time()
        self.last_reported_pct = -1
        self.last_accuracy: Optional[float] = None
        self.passed_samples = 0
        self.graded_samples = 0

        # Per-sample hardware telemetry (last sample + running aggregates).
        self._last_sample_id: Optional[int] = None
        self._last_sample_label: str = ""
        self._last_prompt_tok: Optional[int] = None
        self._last_cached_tok: Optional[int] = None
        self._last_output_tok: Optional[int] = None
        self._last_latency_s: Optional[float] = None
        self._last_ttft_ms: Optional[float] = None
        self._last_decode_tps: Optional[float] = None
        self._last_mtp: Optional[Tuple[int, int]] = None
        self._last_verdict: Optional[str] = None

        self._ttft_samples: List[float] = []
        self._decode_samples: List[float] = []
        self._cache_hits: List[Tuple[int, int]] = []  # (cached, prompt)

        # Multi-stream saturation state (updated by the runner's poller).
        self.active_slots: int = 0
        self.total_slots: int = self.max_connections
        self.aggregate_tps: Optional[float] = None

    # ------------------------------------------------------------------
    # Telemetry ingestion
    # ------------------------------------------------------------------

    def record_sample_telemetry(
        self,
        sample_id: int,
        prompt_tok: Optional[int],
        cached_tok: Optional[int],
        output_tok: Optional[int],
        ttft_ms: Optional[float],
        decode_tps: Optional[float],
        mtp_stat: Optional[Any],
        verdict: Optional[str],
        latency_s: Optional[float] = None,
        label: str = "",
    ) -> None:
        """Record hardware telemetry for one completed sample.

        Args:
            sample_id: 1-based sample index.
            prompt_tok: Raw prompt token count (KV context volume).
            cached_tok: Tokens served from the KV cache.
            output_tok: Generated completion token count.
            ttft_ms: Time To First Token in milliseconds (prefill latency).
            decode_tps: Decode throughput in tokens per second.
            mtp_stat: Speculative decoding stats — ``None``/falsy when
                MTP is disabled, otherwise a ``(accepted, drafted)``
                pair or a mapping with those keys.
            verdict: ``"PASS"`` / ``"FAIL"`` for immediate scoring;
                ``None`` when scoring is deferred.
            latency_s: Wall-clock per-sample latency in seconds.
            label: Optional scenario/sample label for the transcript.
        """
        self._last_sample_id = sample_id
        self._last_sample_label = label
        self._last_prompt_tok = prompt_tok
        self._last_cached_tok = cached_tok
        self._last_output_tok = output_tok
        self._last_latency_s = latency_s
        self._last_ttft_ms = ttft_ms
        self._last_decode_tps = decode_tps
        self._last_mtp = self._coerce_mtp(mtp_stat)
        self._last_verdict = verdict

        if ttft_ms is not None and ttft_ms > 0:
            self._ttft_samples.append(float(ttft_ms))
        if decode_tps is not None and decode_tps > 0:
            self._decode_samples.append(float(decode_tps))
        if prompt_tok and cached_tok is not None and prompt_tok > 0:
            self._cache_hits.append((int(cached_tok), int(prompt_tok)))

        if verdict:
            self.graded_samples += 1
            if str(verdict).upper() == "PASS":
                self.passed_samples += 1
            self.last_accuracy = self.passed_samples / self.graded_samples

        self.render()

    @staticmethod
    def _coerce_mtp(mtp_stat: Optional[Any]) -> Optional[Tuple[int, int]]:
        """Normalize MTP stats to an ``(accepted, drafted)`` pair."""
        if not mtp_stat:
            return None
        if isinstance(mtp_stat, dict):
            accepted = mtp_stat.get("accepted")
            drafted = mtp_stat.get("drafted") or mtp_stat.get("draft")
            try:
                if accepted is not None and drafted:
                    return int(accepted), int(drafted)
            except (TypeError, ValueError):
                return None
        if isinstance(mtp_stat, (tuple, list)) and len(mtp_stat) >= 2:
            try:
                return int(mtp_stat[0]), int(mtp_stat[1])
            except (TypeError, ValueError):
                return None
        return None

    def update_from_inspect_line(self, line: str) -> None:
        """Extracts sample completion progress from live inspect stdout lines.

        Mirrors the legacy :class:`LiveProgressBar` parsing so the
        runner can keep streaming raw subprocess output directly into
        the monitor.
        """
        match = re.search(r"(\d+)/" + str(self.total_samples), line)
        if match:
            new_count = int(match.group(1))
            if new_count > self.completed_samples:
                self.completed_samples = new_count
                self.render()

        acc_match = re.search(r"accuracy:\s*([\d\.]+)", line)
        if acc_match and self.scoring_mode == "immediate":
            try:
                self.last_accuracy = float(acc_match.group(1))
            except ValueError:
                pass

    def set_slot_status(self, active: int, total: int) -> None:
        """Update multi-stream saturation from the inference /slots poller."""
        self.active_slots = max(0, active)
        if total and total > 0:
            self.total_slots = total

    def set_aggregate_tps(self, tps: Optional[float]) -> None:
        """Update aggregate token throughput across concurrent streams."""
        if tps is not None and tps > 0:
            self.aggregate_tps = float(tps)

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Run-level telemetry summary for the models.yaml ledger."""
        def _avg(values: List[float]) -> Optional[float]:
            return round(sum(values) / len(values), 4) if values else None

        cache_hit_rate = None
        if self._cache_hits:
            total_cached = sum(c for c, _ in self._cache_hits)
            total_prompt = sum(p for _, p in self._cache_hits)
            cache_hit_rate = round(total_cached / total_prompt, 4) if total_prompt else None

        mtp_summary: Optional[str] = None
        if self._last_mtp:
            accepted, drafted = self._last_mtp
            if drafted:
                mtp_summary = round(accepted / drafted, 4)

        return {
            "avg_ttft_ms": _avg(self._ttft_samples),
            "avg_decode_tps": _avg(self._decode_samples),
            "cache_hit_rate": cache_hit_rate,
            "mtp_acceptance_rate": mtp_summary,
        }

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _scoring_fragment(self) -> str:
        if self.scoring_mode == "immediate":
            if self.graded_samples > 0:
                pct = self.last_accuracy * 100
                return f"Acc: {pct:.1f}% ({self.passed_samples}/{self.graded_samples})"
            return "Scoring: Immediate (live grading)"
        return "Scoring: Deferred (Batch Graded at Run Conclusion) | Status: RECORDED (Pending Grade)"

    def _progress_row(self) -> str:
        elapsed = time.time() - self.start_time
        pct = int((self.completed_samples / self.total_samples) * 100)

        if self.completed_samples > 0:
            avg_per_sample = elapsed / self.completed_samples
            remaining_s = (self.total_samples - self.completed_samples) * avg_per_sample
            eta_str = f"{int(remaining_s // 60)}m {int(remaining_s % 60):02d}s"
        else:
            eta_str = "estimating..."

        elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60):02d}s"
        filled_len = int(self.BAR_LEN * self.completed_samples // self.total_samples)
        bar = "█" * filled_len + "░" * (self.BAR_LEN - filled_len)

        return (
            f"[{self.task_name}] [{bar}] {self.completed_samples}/{self.total_samples} "
            f"({pct}%) | Elapsed: {elapsed_str} | ETA: {eta_str} | {self._scoring_fragment()}"
        )

    def _fmt_int(self, value: Optional[int]) -> str:
        return f"{value:,}" if value is not None else "—"

    def _telemetry_rows(self) -> List[str]:
        if self._last_sample_id is None:
            return []
        rows: List[str] = []
        label = f" ({self._last_sample_label})" if self._last_sample_label else ""

        prompt_part = f"Prompt: {self._fmt_int(self._last_prompt_tok)} tok"
        if self._last_cached_tok is not None and self._last_prompt_tok:
            cache_pct = (self._last_cached_tok / self._last_prompt_tok) * 100
            prompt_part += f" ({self._last_cached_tok} cached, {cache_pct:.1f}%)"

        output_part = (
            f"Output: {self._fmt_int(self._last_output_tok)} tok"
            if self._last_output_tok is not None
            else "Output: —"
        )
        latency_part = (
            f"Latency: {self._last_latency_s:.1f}s"
            if self._last_latency_s is not None
            else "Latency: —"
        )
        rows.append(
            f"⚡ Last Sample #{self._last_sample_id}{label}: "
            f"{prompt_part} | {output_part} | {latency_part}"
        )

        ttft_part = f"TTFT: {self._last_ttft_ms:.0f} ms" if self._last_ttft_ms is not None else "TTFT: —"
        decode_part = (
            f"Decode: {self._last_decode_tps:.1f} tok/s"
            if self._last_decode_tps is not None
            else "Decode: —"
        )
        mtp_part = self._render_mtp(self._last_mtp)
        verdict_part = f"Verdict: {self._last_verdict}" if self._last_verdict else "Verdict: Pending"
        rows.append(f"   {ttft_part} | {decode_part} | {mtp_part} | {verdict_part}")
        return rows

    @staticmethod
    def _render_mtp(mtp: Optional[Tuple[int, int]]) -> str:
        if not mtp or not mtp[1]:
            return "MTP: Disabled"
        accepted, drafted = mtp
        rate = (accepted / drafted) * 100
        mean_tau = 1 + (accepted / drafted)
        return f"MTP: {rate:.1f}% ({accepted}/{drafted} accepted, τ̄={mean_tau:.2f} tok/step)"

    def _saturation_row(self) -> str:
        total = max(self.total_slots, 1)
        pct = (self.active_slots / total) * 100
        agg = (
            f"{self.aggregate_tps:.1f} tok/s"
            if self.aggregate_tps is not None
            else "—"
        )
        return f"📡 Stream Saturation: {self.active_slots}/{total} active slots ({pct:.0f}%) | Aggregate: {agg}"

    def render(self) -> None:
        """Renders the dual-row progress + telemetry card."""
        progress_row = self._progress_row()
        telemetry_rows = self._telemetry_rows()
        saturation_row = self._saturation_row()
        block_rows = [progress_row] + telemetry_rows + [saturation_row]
        pct = int((self.completed_samples / self.total_samples) * 100)

        if self.is_tty:
            block = "\n".join(block_rows)
            sys.stdout.write("\r" + block)
            sys.stdout.flush()
        else:
            # Non-TTY logging: print milestones every 20% or on finish.
            if pct != self.last_reported_pct and (pct % 20 == 0 or pct == 100):
                print("\n".join(block_rows))
                self.last_reported_pct = pct

    def render_milestone_summary(self) -> None:
        """Non-TTY final summary card (PRD §5.3 transcript display)."""
        elapsed = time.time() - self.start_time
        elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60):02d}s"
        filled_len = int(self.BAR_LEN * self.completed_samples // self.total_samples)
        bar = "█" * filled_len + "░" * (self.BAR_LEN - filled_len)
        pct = int((self.completed_samples / self.total_samples) * 100)
        final_acc = (
            f"Final Acc: {self.last_accuracy * 100:.1f}% "
            f"({self.passed_samples}/{self.graded_samples})"
        ) if self.last_accuracy is not None else self._scoring_fragment()

        s = self.summary()
        ttft_s = f"{s['avg_ttft_ms']:.0f}ms" if s["avg_ttft_ms"] is not None else "—"
        decode_s = f"{s['avg_decode_tps']:.1f} tok/s" if s["avg_decode_tps"] is not None else "—"
        cache_s = f"{s['cache_hit_rate'] * 100:.1f}%" if s["cache_hit_rate"] is not None else "—"
        mtp_s = self._render_mtp(self._last_mtp).replace("MTP: ", "")
        print(f"[{self.task_name}] [{bar}] {self.completed_samples}/{self.total_samples} "
              f"({pct}%) | Elapsed: {elapsed_str} | {final_acc}")
        print(f"⚡ Telemetry Summary: Avg TTFT: {ttft_s} | Avg Decode: {decode_s} | "
              f"Cache Hit Rate: {cache_s} | MTP: {mtp_s}")

    def close(self) -> None:
        """Finishes the live display."""
        if self.is_tty:
            sys.stdout.write("\n")
            sys.stdout.flush()
        else:
            self.render_milestone_summary()


class LiveProgressBar:
    """
    Legacy single-row progress bar. Retained for backward compatibility;
    new code should prefer :class:`LiveTelemetryMonitor`.
    """

    def __init__(self, task_name: str, total_samples: int, is_tty: Optional[bool] = None):
        self.task_name = task_name
        self.total_samples = max(total_samples, 1)
        self.completed_samples = 0
        self.start_time = time.time()
        self.is_tty = sys.stdout.isatty() if is_tty is None else is_tty
        self.last_reported_pct = -1
        self.last_accuracy: Optional[float] = None
        self.current_tps: Optional[float] = None

    def update_from_inspect_line(self, line: str):
        """Extracts sample progress and accuracy from live inspect stdout lines."""
        # Pattern matching inspect progress like: '12/25' or '12/25 accuracy: 0.84'
        match = re.search(r"(\d+)/" + str(self.total_samples), line)
        if match:
            self.completed_samples = int(match.group(1))

        acc_match = re.search(r"accuracy:\s*([\d\.]+)", line)
        if acc_match:
            try:
                self.last_accuracy = float(acc_match.group(1))
            except ValueError:
                pass

        self.render()

    def render(self):
        """Renders the transparent progress bar."""
        elapsed = time.time() - self.start_time
        pct = int((self.completed_samples / self.total_samples) * 100)

        # Calculate ETA
        if self.completed_samples > 0:
            avg_per_sample = elapsed / self.completed_samples
            remaining_s = (self.total_samples - self.completed_samples) * avg_per_sample
            eta_str = f"{int(remaining_s // 60)}m {int(remaining_s % 60):02d}s"
        else:
            eta_str = "estimating..."

        elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60):02d}s"

        bar_len = 24
        filled_len = int(bar_len * self.completed_samples // self.total_samples)
        bar = "█" * filled_len + "░" * (bar_len - filled_len)

        acc_str = f" | Acc: {self.last_accuracy*100:.1f}%" if self.last_accuracy is not None else ""

        status_text = (
            f"[{self.task_name}] [{bar}] {self.completed_samples}/{self.total_samples} "
            f"({pct}%) | Elapsed: {elapsed_str} | ETA: {eta_str}{acc_str}"
        )

        if self.is_tty:
            sys.stdout.write(f"\r{status_text}")
            sys.stdout.flush()
        else:
            # Non-TTY logging: print milestones every 20% or on finish
            if pct != self.last_reported_pct and (pct % 20 == 0 or pct == 100):
                print(status_text)
                self.last_reported_pct = pct

    def close(self):
        """Finishes the progress display."""
        if self.is_tty:
            sys.stdout.write("\n")
            sys.stdout.flush()
