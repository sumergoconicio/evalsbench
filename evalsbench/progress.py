"""
Transparent live progress bar and status monitor for EvalsBench.
"""

import sys
import time
import re
from typing import Optional


class LiveProgressBar:
    """
    Renders an in-place live progress bar and throughput monitor.
    Gracefully handles both interactive TTY terminals and background agent logging.
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
