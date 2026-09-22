"""
EvalsBench EDS (Evaluation Development System) subpackage.

Wave 0 foundations: typed Pydantic v2 models, copy-on-write world state,
and append-only tool event tracing.
"""

from .models import (
    Actor,
    EpisodeMetadata,
    EpisodeSpec,
    HiddenTruth,
    InteractionLimits,
    PolicyRule,
    PolicyViolation,
    PreconditionFailed,
    Provenance,
    Scorecard,
    TaggedEntity,
    ToolEvent,
    WorldFixture,
)
from .world import WorldState

__all__ = [
    "Actor",
    "EpisodeMetadata",
    "EpisodeSpec",
    "HiddenTruth",
    "InteractionLimits",
    "PolicyRule",
    "PolicyViolation",
    "PreconditionFailed",
    "Provenance",
    "Scorecard",
    "TaggedEntity",
    "ToolEvent",
    "WorldFixture",
    "WorldState",
]
