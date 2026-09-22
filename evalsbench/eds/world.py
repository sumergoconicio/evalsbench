"""
World state container with copy-on-write isolation and append-only tracing.

Each `WorldState` instance receives a `WorldFixture`, deep-copies its state
into a working copy, and never mutates the upstream fixture. All tool
executions produce immutable `ToolEvent` records that accumulate in the
append-only `trace` list. Mutation diffs are computed against a pristine
reference snapshot for downstream scoring decisions.

Concurrency contract
--------------------
``set_entity`` and ``record_event`` are intentionally lock-free. Their
correctness under the inspected execution paths rests on three pinning
invariants validated by ``tests/eds/test_world_concurrency.py``:

1. The EDS tool dispatcher (``evalsbench.eds.tools.bind_tools``) wraps
   every :func:`@mock_tool <mock_tool>` raw function in an ``async def
   execute()`` closure whose body contains NO ``await`` keyword between
   the ``spec.raw_fn(...)`` call and the closing
   ``world.record_event(...)`` call. A sibling coroutine scheduled on
   the same event-loop thread cannot pre-empt this slice.
2. ``inspect_ai.model._call_tools.execute_tools`` (the executor the
   EDS solver uses) runs tool bodies on the asyncio event loop.
   ``parallel=False`` is the default for the EDS wrapper, so
   multi-call assistant messages degrade into serial one-call stages;
   with ``parallel=True`` the anyio task group still schedules on the
   asyncio loop, not a thread pool.
3. The per-sample solver builds its ``WorldState`` inside the inner
   ``solve`` closure so concurrent samples never share this object's
   reference, removing cross-sample race surface entirely.

If invariant (1) is broken - for example by introducing an ``await``
inside ``_build_bound_callable.execute()`` between the raw function
call and the closing ``record_event`` - the single-event-loop-thread
atomicity argument no longer holds and an explicit threading lock
(or asyncio.Lock) MUST be added to ``set_entity`` and
``record_event`` together with a regression update to
``tests/eds/test_world_concurrency.py``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from .models import ToolEvent, WorldFixture


class WorldState:
    """Ephemeral copy-on-write world state for one episode run."""

    def __init__(self, fixture: WorldFixture) -> None:
        # Pristine reference snapshot used for diff/audit comparisons.
        self._initial: Dict[str, Any] = copy.deepcopy(fixture.state)
        # Working copy that the actor and tools are allowed to mutate.
        self._state: Dict[str, Any] = copy.deepcopy(fixture.state)
        # Append-only event trace.
        self.trace: List[ToolEvent] = []
        # Cache the fixture reference but do not rely on the caller to mutate it.
        self._fixture = fixture

    # ------------------------------------------------------------------
    # Fixture accessors (read-only by convention)
    # ------------------------------------------------------------------

    @property
    def fixture(self) -> WorldFixture:
        return self._fixture

    # ------------------------------------------------------------------
    # Entity lookup
    # ------------------------------------------------------------------

    def get_entity(self, path: str, default: Any = None) -> Any:
        """Resolve a dotted path through the working state tree."""
        if not path:
            return default
        node: Any = self._state
        for part in self._split_path(path):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def __getattr__(self, name: str) -> Any:
        """Attribute-style shortcut for top-level entity keys."""
        if name.startswith("_") or name == "trace" or name == "fixture":
            raise AttributeError(name)
        try:
            state = object.__getattribute__(self, "_state")
        except AttributeError:
            raise AttributeError(name)
        if isinstance(state, dict) and name in state:
            return state[name]
        raise AttributeError(f"WorldState has no entity named {name!r}")

    # ------------------------------------------------------------------
    # Mutation API
    # ------------------------------------------------------------------

    def set_entity(self, path: str, value: Any) -> None:
        """Write through a dotted path; intermediate dicts are auto-created."""
        parts = self._split_path(path)
        if not parts:
            raise ValueError("WorldState.set_entity requires a non-empty path.")
        node: Any = self._state
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    # ------------------------------------------------------------------
    # Trace API
    # ------------------------------------------------------------------

    def record_event(
        self,
        *,
        tool: str,
        actor: str,
        outcome: str = "ok",
        args: Dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ToolEvent:
        """Append an immutable event to the trace and return the constructed record."""
        if outcome not in ("ok", "PreconditionFailed", "PolicyViolation"):
            raise ValueError(f"Unsupported outcome tag: {outcome!r}.")
        event = ToolEvent(
            tool=tool,
            args=args if args is not None else {},
            actor=actor,
            outcome=outcome,  # type: ignore[arg-type]
            error=error,
        )
        self.trace.append(event)
        return event

    # ------------------------------------------------------------------
    # Diff API
    # ------------------------------------------------------------------

    def snapshot_diff(self) -> Dict[str, Any]:
        """Return the mutations applied since the pristine initial state."""
        return _deep_diff(self._initial, self._state)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_path(path: str) -> List[str]:
        return [segment for segment in path.split(".") if segment]


# ---------------------------------------------------------------------------
# Tree diff utility (module-local helper)
# ---------------------------------------------------------------------------


def _flatten_added(diff: Dict[str, Any], value: Any, prefix: str) -> None:
    """Record an entirely-added subtree as individual dotted leaf entries."""
    if isinstance(value, dict):
        if not value:
            diff[prefix] = {"added": {}}
            return
        for key, child in value.items():
            _flatten_added(diff, child, f"{prefix}.{key}")
    else:
        diff[prefix] = {"added": value}


def _flatten_removed(diff: Dict[str, Any], value: Any, prefix: str) -> None:
    """Record an entirely-removed subtree as individual dotted leaf entries."""
    if isinstance(value, dict):
        if not value:
            diff[prefix] = {"removed": {}}
            return
        for key, child in value.items():
            _flatten_removed(diff, child, f"{prefix}.{key}")
    else:
        diff[prefix] = {"removed": value}


def _deep_diff(before: Any, after: Any, prefix: str = "") -> Dict[str, Any]:
    """Recursive structural diff returning only the mutated leaves as dotted paths."""
    diff: Dict[str, Any] = {}
    if type(before) is not type(after):
        diff[prefix or "<root>"] = {"before": before, "after": after}
        return diff
    if isinstance(before, dict):
        keys = set(before.keys()) | set(after.keys())
        for key in keys:
            new_prefix = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                _flatten_added(diff, after[key], new_prefix)
            elif key not in after:
                _flatten_removed(diff, before[key], new_prefix)
            elif before[key] != after[key]:
                inner = _deep_diff(before[key], after[key], new_prefix)
                if not inner and not isinstance(before[key], (dict, list)):
                    diff[new_prefix] = {"before": before[key], "after": after[key]}
                else:
                    diff.update(inner)
    elif isinstance(before, list):
        if before != after:
            diff[prefix or "<root>"] = {"before": before, "after": after}
    else:
        if before != after:
            diff[prefix or "<root>"] = {"before": before, "after": after}
    return diff
