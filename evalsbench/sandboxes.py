"""
Polite Docker sandbox lifecycle management and post-evaluation cleanup.
"""

import subprocess
import shutil
from typing import List

# Never terminate persistent services or databases
PROTECTED_PREFIXES = [
    "vllm_",
    "claire_",
    "comfyui",
    "redis",
    "qdrant",
    "gitea",
    "postgres",
    "minio",
    "tika",
    "playwright",
]


def list_inspect_containers() -> List[str]:
    """Returns IDs of active Inspect AI and Harbor test containers."""
    if not shutil.which("docker"):
        return []
    try:
        res = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.ID}} {{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        cids = []
        for line in res.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                cid, name = parts[0], parts[1]
                # Protect critical server containers
                if any(name.startswith(p) for p in PROTECTED_PREFIXES):
                    continue
                # Target inspect and harbor test containers
                if name.startswith("inspect") or name.startswith("harbor") or "startup-" in name:
                    cids.append(cid)
        return cids
    except Exception:
        return []


def prune_inspect_containers():
    """Politely stops and removes lingering test containers and dangling build images."""
    if not shutil.which("docker"):
        return

    # 1. Stop and remove test containers
    containers = list_inspect_containers()
    if containers:
        try:
            subprocess.run(["docker", "rm", "-f"] + containers, capture_output=True, check=False)
        except Exception:
            pass

    # 2. Prune dangling untagged (<none>) build images left behind by Dockerfile builds
    try:
        subprocess.run(
            ["docker", "image", "prune", "-f", "--filter", "dangling=true"],
            capture_output=True,
            check=False,
        )
    except Exception:
        pass
