"""
Execution engine with preflight validation, native Inspect AI runner, and Docker hygiene.
"""

import asyncio
import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .config import get_log_dir_for_benchmark, load_chai_env
from .registry import BENCHMARK_REGISTRY, BenchmarkTask
from .shims import apply_inspect_openai_shims
from .sandboxes import prune_inspect_containers
from .exporters import write_benchmark_report, update_models_yaml, sync_to_chai_vault


class EvalsRunner:
    def __init__(
        self,
        model_name: str,
        endpoint_url: str,
        api_key: Optional[str] = None,
        max_connections: int = 8,
        chai_sync: bool = True,
    ):
        self.model_name = model_name
        self.endpoint_url = endpoint_url.rstrip("/")
        self.max_connections = max_connections
        self.chai_sync = chai_sync
        
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
        env = os.environ.copy()
        env["OPENAI_BASE_URL"] = self.endpoint_url
        env["OPENAI_API_KEY"] = self.api_key

        cmd = [
            sys.executable,
            "-m",
            "inspect_ai",
            "eval",
            task.task_id,
            "--model",
            f"openai/{self.model_name}",
            "--limit",
            "1",
            "--max-connections",
            "1",
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
                timeout=90,
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
        Executes a single benchmark task, saving outputs strictly to:
        logs/YYYYMMDD_modelname_benchmarkname/
        """
        task = BENCHMARK_REGISTRY.get(task_key)
        if not task:
            raise ValueError(f"Unknown benchmark: {task_key}. Available: {list(BENCHMARK_REGISTRY.keys())}")

        samples = limit or task.default_limit
        log_dir = get_log_dir_for_benchmark(self.model_name, task.name)

        print("\n" + "=" * 65)
        print(f"🚀 Launching Benchmark: {task.name} ({samples} samples, {self.max_connections} slots)")
        print(f"Model: {self.model_name} @ {self.endpoint_url}")
        print(f"Log Directory: {log_dir}")
        print("=" * 65)

        # Preflight validation gate
        if not skip_preflight:
            if not self.run_preflight_check(task):
                print(f"⚠️ Skipping full batch for {task.name} due to preflight check failure.")
                return False, {}, 0.0

        env = os.environ.copy()
        env["OPENAI_BASE_URL"] = self.endpoint_url
        env["OPENAI_API_KEY"] = self.api_key

        cmd = [
            sys.executable,
            "-m",
            "inspect_ai",
            "eval",
            task.task_id,
            "--model",
            f"openai/{self.model_name}",
            "--limit",
            str(samples),
            "--sample-shuffle",
            str(sample_shuffle),
            "--max-connections",
            str(self.max_connections),
            "--log-dir",
            str(log_dir),
        ]
        if task.args:
            cmd.extend(task.args)

        start_time = time.time()
        try:
            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            duration_s = time.time() - start_time
            raw_output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
            
            # Print live tail of inspect output
            print(raw_output[-1500:] if len(raw_output) > 1500 else raw_output)

            # Parse scores
            scores = self._parse_scores_from_output(raw_output)

            # Locate .eval file
            eval_files = list(log_dir.glob("*.eval"))
            eval_log_path = str(eval_files[0]) if eval_files else None

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

            print(f"✅ {task.name} Completed in {duration_s:.1f}s")
            print(f"📝 Report saved to: {report_file}")
            return proc.returncode == 0, scores, duration_s

        finally:
            if task.docker_required:
                prune_inspect_containers()

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
