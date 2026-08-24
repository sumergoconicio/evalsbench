"""
Docker sandbox lifecycle management and post-evaluation cleanup.
"""

import subprocess
import shutil
from typing import List


def list_inspect_containers() -> List[str]:
    """Returns IDs of active Inspect AI and Harbor docker containers."""
    if not shutil.which("docker"):
        return []
    try:
        res = subprocess.run(
            ["docker", "ps", "-q", "--filter", "name=inspect"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [cid.strip() for cid in res.stdout.splitlines() if cid.strip()]
    except Exception:
        return []


def prune_inspect_containers():
    """Prunes lingering inspect test containers to keep the host clean."""
    containers = list_inspect_containers()
    if containers:
        try:
            subprocess.run(["docker", "rm", "-f"] + containers, capture_output=True, check=False)
        except Exception:
            pass
