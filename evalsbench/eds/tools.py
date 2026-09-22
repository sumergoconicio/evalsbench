"""
Mock Tool Bus for the EDS (Evaluation Development System) subpackage.

File:    evalsbench/eds/tools.py
Module:  evalsbench.eds
Purpose: Register plain Python functions as typed EDS mock tools, derive
         their Inspect AI tool schema from type hints and docstring (with
         the WorldState binding slot filtered out), and bind per-sample
         world state and actor identity to each callable so that domain
         exceptions are captured as controlled results rather than
         crashes.

The ``@mock_tool`` decorator stores a ``MockToolSpec`` on the wrapped
function; ``bind_tools(world, tool_fns)`` then constructs per-sample
Inspect AI ``Tool`` callables whose closures reference ONLY this
sample's WorldState instance. Domain exceptions
(:class:`PreconditionFailed`, :class:`PolicyViolation`) raised inside
the user-supplied tool function are converted into ``ToolEvent`` rows
with matching outcome tags and the model is returned a descriptive
``"Error: <message>"`` string so the multi-turn loop never crashes.
Unexpected exceptions are logged at warning level and surfaced as
internal-error strings tagged ``PreconditionFailed`` so that an
unrelated wrapper bug never trips the scorecard safety-gate invariant.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, get_type_hints

from inspect_ai._util.registry import (
    RegistryInfo,
    set_registry_info,
    set_registry_params,
)
from inspect_ai.tool import Tool
from inspect_ai.tool._tool_description import (
    ToolDescription,
    set_tool_description,
)
from inspect_ai.tool._tool_info import (
    ToolInfo,
    ToolParams,
    parse_tool_info,
)

from .models import PolicyViolation, PreconditionFailed
from .world import WorldState


# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger("evalsbench.eds.tools")


# ---------------------------------------------------------------------------
# Schema derivation from decorated functions
# ---------------------------------------------------------------------------


# Parameter names recognized as the per-sample WorldState binding slot.
_WORLD_PARAM_NAMES: frozenset = frozenset({"world", "world_state"})


@dataclass(frozen=True)
class MockToolSpec:
    """Captured schema + raw reference for one ``@mock_tool``-decorated function.

    Attributes:
        name: Tool name (defaults to the wrapped function ``__name__``).
        description: Short description pulled from the wrapped function
            docstring via :func:`inspect_ai.tool._tool_info.parse_tool_info`.
        parameters: Public-parameter schema (``ToolParams``) with the
            WorldState binding slot stripped from both ``properties`` and
            ``required``.
        raw_fn: Original function reference accepting
            ``(world, **public_kwargs)``.
    """

    name: str
    description: str
    parameters: ToolParams
    raw_fn: Callable[..., Any]


def mock_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: register a Python function as an EDS mock tool.

    The decorated function must accept a per-sample ``WorldState`` binding
    slot (named ``world``, ``world_state``, or annotated with the
    :class:`~evalsbench.eds.world.WorldState` type) followed by the
    public keyword arguments that will be exposed to the model in the
    derived JSON schema via Inspect AI's docstring + type hint parser.

    The function may return any JSON-serializable value or raise the
    typed EDS exceptions :class:`PreconditionFailed` and
    :class:`PolicyViolation` to signal controlled failure outcomes to
    the model. ``bind_tools`` performs the dispatch and exception
    capture; the decorated function itself is never invoked directly.

    Args:
        fn: The function reference to register. Expected to accept
            ``(world, **public_kwargs)``.

    Returns:
        Callable: a placeholder wrapper carrying ``__eds_spec__`` and
        ``__eds_is_mock_tool__`` attributes so ``bind_tools`` can build
        per-sample ``Tool`` callables.

    Raises:
        ValueError: if no WorldState binding parameter is detected or
            Inspect AI's tool introspector rejects the function
            signature or docstring.
    """
    tool_info = _derive_mock_tool_info(fn)
    spec = MockToolSpec(
        name=tool_info.name,
        description=tool_info.description,
        parameters=tool_info.parameters,
        raw_fn=fn,
    )

    @functools.wraps(fn)
    def _placeholder(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            f"EDS mock tool {spec.name!r} must be dispatched through "
            "bind_tools(), which produces a per-sample Tool callable."
        )

    setattr(_placeholder, "__eds_spec__", spec)
    setattr(_placeholder, "__eds_is_mock_tool__", True)
    return _placeholder


def _derive_mock_tool_info(fn: Callable[..., Any]) -> ToolInfo:
    """Derive an Inspect AI ``ToolInfo`` for ``fn`` with the world slot stripped.

    Walks the function's signature to identify exactly one parameter
    carrying the per-sample WorldState binding, then strips that
    parameter from both the JSON schema ``properties`` map and the
    ``required`` list before re-validating the schema via Inspect AI's
    ``parse_tool_info``.

    Args:
        fn: The decorated function reference.

    Returns:
        ToolInfo: schema carrying only the public parameter surface.

    Raises:
        ValueError: if no world-binding slot is found, or if
            Inspect AI's introspector rejects the function's
            signature or docstring.
    """
    sig = inspect.signature(fn)
    world_params = {
        name: param
        for name, param in sig.parameters.items()
        if _is_world_binding(name, param)
    }
    if not world_params:
        raise ValueError(
            f"@mock_tool target {fn.__name__!r} must expose a per-sample "
            "WorldState binding parameter named 'world' / 'world_state' "
            "or annotated with evalsbench.eds.world.WorldState."
        )
    if len(world_params) > 1:
        raise ValueError(
            f"@mock_tool target {fn.__name__!r} exposes multiple world "
            "binding parameters; exactly one is required."
        )

    try:
        raw_info = parse_tool_info(fn)
    except Exception as exc:
        raise ValueError(
            f"@mock_tool target {fn.__name__!r} failed Inspect AI "
            f"introspection: {exc}."
        ) from exc

    world_key = next(iter(world_params))
    props = {
        key: value
        for key, value in raw_info.parameters.properties.items()
        if key != world_key
    }
    required = [
        name for name in (raw_info.parameters.required or []) if name != world_key
    ]
    clean = ToolParams(
        properties=props,
        required=required,
        additionalProperties=False,
    )
    if not raw_info.description:
        raise ValueError(
            f"@mock_tool target {fn.__name__!r} docstring must provide a "
            "tool description; Inspect AI introspection could not derive one."
        )
    return ToolInfo(
        name=raw_info.name,
        description=raw_info.description,
        parameters=clean,
    )


def _is_world_binding(name: str, param: inspect.Parameter) -> bool:
    """Return True iff ``param`` carries the per-sample WorldState binding.

    A parameter is considered a world binding if its name matches one
    of the conventional slot names (``world`` / ``world_state``) or if
    its annotation is the :class:`~evalsbench.eds.world.WorldState`
    class.

    Args:
        name: The parameter name as it appears in the function signature.
        param: The ``inspect.Parameter`` instance for that name.

    Returns:
        bool: True iff the parameter is the WorldState binding slot.
    """
    if name in _WORLD_PARAM_NAMES:
        return True
    annotation = param.annotation
    if annotation is inspect.Parameter.empty:
        return False
    annotation_name = getattr(annotation, "__name__", str(annotation))
    return annotation_name == "WorldState"


# ---------------------------------------------------------------------------
# Per-sample tool binding
# ---------------------------------------------------------------------------


def bind_tools(
    world: WorldState,
    tool_fns: List[Callable[..., Any]],
    *,
    actor: str = "actor",
    logger_override: Optional[logging.Logger] = None,
) -> List[Tool]:
    """Build Inspect AI ``Tool`` callables bound to a per-sample ``WorldState``.

    Each returned callable closes over ONLY the supplied ``world`` and
    ``actor`` arguments, ensuring sibling samples cannot share per-sample
    tool state when ``max_connections > 1``.

    Domain exceptions raised inside the raw function are converted into
    ``ToolEvent`` rows with matching outcome tags and the loop is
    returned a descriptive ``"Error: <message>"`` string so the agent
    loop never crashes. Unexpected exceptions are logged at warning
    level and surfaced as an internal-error string whose outcome is
    tagged ``PreconditionFailed`` so that an unrelated wrapper bug never
    trips the scorecard safety-gate invariant (which would otherwise
    zero out the entire composite score on a critical violation).

    Args:
        world: Per-sample :class:`WorldState`. The world is deep-copied
            from its fixture at construction so upstream fixtures are
            never mutated.
        tool_fns: Ordered list of ``@mock_tool``-decorated functions
            (or any callable exposing ``__eds_spec__`` from the
            decorator). Order is preserved in the returned tool list.
        actor: Principal id stamped on every recorded ``ToolEvent``.
            Defaults to the literal string ``"actor"``.
        logger_override: Optional logger for unexpected-exception
            capture. When unset, the module-level
            ``evalsbench.eds.tools`` logger is used so application logs
            can be filtered without changing the behavior of
            ``bind_tools()``.

    Returns:
        List[Tool]: one Inspect AI ``Tool`` per input function, in the
        same order as ``tool_fns``. Each callable's closure references
        ONLY this sample's ``world`` argument, preserving per-sample
        isolation under concurrent execution.

    Raises:
        ValueError: if any ``tool_fns`` entry does not carry a
            ``__eds_spec__`` produced by ``@mock_tool``.
    """
    bound_log = logger_override or logger
    bound: List[Tool] = []
    for fn in tool_fns:
        spec = _extract_spec(fn)
        callable_obj = _build_bound_callable(
            world=world,
            spec=spec,
            actor=actor,
            logger=bound_log,
        )
        _register_tool_metadata(
            callable_obj,
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters,
        )
        bound.append(callable_obj)  # type: ignore[arg-type]
    return bound


def is_mock_tool(obj: Any) -> bool:
    """Return True iff ``obj`` was registered via :func:`@mock_tool <mock_tool>`.

    Args:
        obj: The candidate object to inspect.

    Returns:
        bool: True iff ``obj.__eds_is_mock_tool__`` is truthy.
    """
    return bool(getattr(obj, "__eds_is_mock_tool__", False))


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_spec(fn: Callable[..., Any]) -> MockToolSpec:
    """Pull the captured ``MockToolSpec`` off a ``@mock_tool``-decorated callable.

    Args:
        fn: The candidate decorated function.

    Returns:
        MockToolSpec: the dataclass instance stored by the decorator.

    Raises:
        ValueError: if ``fn`` was not decorated with ``@mock_tool``.
    """
    spec = getattr(fn, "__eds_spec__", None)
    if spec is None or not isinstance(spec, MockToolSpec):
        raise ValueError(
            f"Function {fn.__name__!r} is not an EDS mock tool. Apply "
            "@mock_tool before passing it to bind_tools()."
        )
    return spec


def _build_bound_callable(
    *,
    world: WorldState,
    spec: MockToolSpec,
    actor: str,
    logger: logging.Logger,
) -> Callable[..., Any]:
    """Construct a per-sample async ``Tool`` callable capturing world + actor.

    The returned ``async def execute(**public_kwargs)`` closure overrides
    its ``__signature__`` and ``__annotations__`` so Inspect AI's
    introspection sees the public parameter surface defined by
    ``spec.parameters`` rather than the internal ``**public_kwargs``
    collection.

    Args:
        world: Per-sample world whose mutation and trace apparatus the
            closure should manage.
        spec: Captured schema carrying the raw function reference.
        actor: Principal id stamped on every recorded ``ToolEvent``.
        logger: Logger used for unexpected-exception capture.

    Returns:
        Callable[..., Any]: an undecorated async callable ready for
        ``_register_tool_metadata`` to attach registry info.
    """

    async def execute(**public_kwargs: Any) -> Any:
        """Invoke the underlying raw function against the bound world.

        Args:
            **public_kwargs: Public arguments dispatched by the model.

        Returns:
            A ``ToolResult``-compatible value: either the formatted
            success payload or a descriptive ``"Error: <message>"``
            string for controlled failures.

        Records:
            Exactly one ``ToolEvent`` is appended to ``world.trace``
            per invocation, regardless of the outcome tag.
        """
        tool_name = spec.name
        try:
            result = spec.raw_fn(world=world, **public_kwargs)
        except PreconditionFailed as exc:
            world.record_event(
                tool=tool_name,
                actor=actor,
                outcome="PreconditionFailed",
                args=public_kwargs,
                error=str(exc),
            )
            return _format_error(exc)
        except PolicyViolation as exc:
            world.record_event(
                tool=tool_name,
                actor=actor,
                outcome="PolicyViolation",
                args=public_kwargs,
                error=str(exc),
            )
            return _format_error(exc)
        except Exception as exc:  # noqa: BLE001 - we explicitly catch-all here.
            logger.exception(
                "Unexpected exception in EDS mock tool %s", tool_name
            )
            error_message = (
                f"Internal error in tool '{tool_name}' "
                f"({type(exc).__name__}: {exc})."
            )
            world.record_event(
                tool=tool_name,
                actor=actor,
                outcome="PreconditionFailed",
                args=public_kwargs,
                error=error_message,
            )
            return f"Error: {error_message}"

        world.record_event(
            tool=tool_name,
            actor=actor,
            outcome="ok",
            args=public_kwargs,
        )
        return _format_result(result)

    # Override the introspected surface so Inspect AI sees the public
    # parameter list instead of the internal ``**public_kwargs``.
    _apply_signature_override(execute, spec)
    execute.__name__ = spec.name
    execute.__doc__ = spec.description
    return execute


def _apply_signature_override(
    async_callable: Callable[..., Any], spec: MockToolSpec
) -> None:
    """Override the introspected signature of an async Tool callable.

    Args:
        async_callable: An ``async def`` callable whose public
            parameters should be exposed to introspection as
            keyword-only with proper type annotations and docstring
            descriptions.
        spec: Source schema describing the public parameter surface.

    Returns:
        None. Mutates the callable in place to carry the override
        signature, annotations, and per-parameter docstring slice.
    """
    type_hints = _python_annotation_for(spec.parameters.properties)
    params_list: List[inspect.Parameter] = []
    required_set = set(spec.parameters.required or [])
    for key, param_def in spec.parameters.properties.items():
        annotation = type_hints[key]
        default = inspect.Parameter.empty if key in required_set else None
        params_list.append(
            inspect.Parameter(
                name=key,
                kind=inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=default,
            )
        )
    async_callable.__signature__ = inspect.Signature(parameters=params_list)
    async_callable.__annotations__ = type_hints
    # Embed inline per-parameter docstring so parse_tool_info can
    # attribute descriptions per param.
    per_param = "\n".join(
        f"  {key}: {param_def.description or ''}".rstrip()
        for key, param_def in spec.parameters.properties.items()
    )
    async_callable.__doc__ = (
        f"{spec.description}\n\nArgs:\n{per_param}"
        if per_param
        else spec.description
    )


def _python_annotation_for(
    property_map: Dict[str, Any],
) -> Dict[str, Any]:
    """Translate JSON-schema ``type`` literals to Python annotations.

    Args:
        property_map: Schema ``properties`` mapping from Inspect AI's
            ``ToolParams``.

    Returns:
        Dict[str, Any]: a mapping of parameter name to Python type
        suitable for assignment to ``__annotations__``.
    """
    out: Dict[str, Any] = {}
    for key, param in property_map.items():
        out[key] = _json_type_to_annotation(_json_type_of(param))
    return out


def _json_type_of(param: Any) -> str:
    """Normalize the JSON-schema ``type`` literal of a parameter.

    Args:
        param: A Inspect AI ``ToolParam`` (or compatible object) whose
            ``type`` field is either a single string or a list.

    Returns:
        str: the primary type literal (``"object"`` for fallback).
    """
    raw = getattr(param, "type", None)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list) and raw:
        return str(raw[0])
    return "object"


def _json_type_to_annotation(json_type: str) -> Any:
    """Translate a JSON-schema ``type`` literal to a Python annotation.

    Args:
        json_type: A JSON schema primitive like ``"string"``, ``"integer"``,
            ``"number"``, ``"boolean"``, ``"array"``, ``"object"``.

    Returns:
        Any: the corresponding Python builtin type (used as a
        ``__annotations__`` value).
    """
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return mapping.get(json_type, object)


def _format_result(result: Any) -> Any:
    """Coerce a raw tool result into an Inspect ``ToolResult``-shaped value.

    Native Python scalars and strings are passed through; container
    types are JSON-serialized; anything else falls back to ``str()``.

    Args:
        result: The raw return value of the user-supplied tool function.

    Returns:
        Any: a value matching Inspect AI's ``ToolResult`` type union.
    """
    if result is None:
        return ""
    if isinstance(result, (str, int, float, bool)):
        return result
    if isinstance(result, dict):
        try:
            return json.dumps(result, sort_keys=True, default=str)
        except TypeError:
            return str(result)
    if isinstance(result, list):
        try:
            return json.dumps(result, default=str)
        except TypeError:
            return str(result)
    return str(result)


def _format_error(exc: Exception) -> str:
    """Render a controlled failure as an Inspect-safe error string.

    Args:
        exc: The original :class:`PreconditionFailed` or
            :class:`PolicyViolation` exception captured by the wrapper.

    Returns:
        str: user-visible error message of the form ``"Error: <message>"``.
    """
    return f"Error: {exc}"


def _register_tool_metadata(
    callable_obj: Callable[..., Any],
    *,
    name: str,
    description: str,
    parameters: ToolParams,
) -> None:
    """Attach Inspect AI ``Tool`` metadata to an arbitrary async callable.

    Mirrors what ``@tool`` + ``tool_with()`` accomplish, but applied
    directly so that per-sample closures built in ``bind_tools`` (whose
    dynamic signature is overridden in code rather than in source) are
    recognized by Inspect's registry.

    Args:
        callable_obj: An ``async def`` callable accepting the public
            keyword arguments.
        name: Tool name to register in Inspect's registry.
        description: Tool description synced with the spec.
        parameters: Public-parameter schema to expose to the model.

    Returns:
        None. Mutates the callable in place to carry registry metadata.
    """
    descr = ToolDescription(
        name=name,
        description=description,
        parameters=parameters,
    )
    set_tool_description(callable_obj, descr)
    set_registry_params(callable_obj, {})
    set_registry_info(
        callable_obj,
        RegistryInfo(type="tool", name=name),
    )
