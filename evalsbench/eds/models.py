"""
Typed Pydantic v2 models and domain exceptions for the EDS (Evaluation
Development System) subpackage of EvalsBench.

This module is the single source of truth for episode specifications,
world fixtures, actors, append-only tool events, policy rules, and per
episode scorecards (including the safety-gate invariant).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# ---------------------------------------------------------------------------
# Domain Exceptions (typed for the EDS tool execution layer)
# ---------------------------------------------------------------------------


class PreconditionFailed(Exception):
    """Raised when a tool call violates a stated episode precondition."""

    def __init__(self, message: str, *, tool: Optional[str] = None) -> None:
        super().__init__(message)
        self.tool = tool


class PolicyViolation(Exception):
    """Raised when a tool call violates a critical policy rule."""

    def __init__(
        self,
        message: str,
        *,
        rule: Optional[str] = None,
        tool: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.rule = rule
        self.tool = tool


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Provenance(str, Enum):
    """Provenance tier classifying the reliability of a fixture entity."""

    CANONICAL = "canonical"
    ADVISORY = "advisory"
    UNVERIFIED = "unverified"


# ---------------------------------------------------------------------------
# Primitive components
# ---------------------------------------------------------------------------


class TaggedEntity(BaseModel):
    """Fixture entity carrying an explicit provenance tier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Provenance
    payload: Dict[str, Any] = Field(default_factory=dict)


class Actor(BaseModel):
    """The principal (human or agent) authorized to interact with the world."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_id: str = Field(..., min_length=1)
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

    @field_validator("roles", "permissions")
    @classmethod
    def _strip_blanks(cls, value: List[str]) -> List[str]:
        return [item for item in (token.strip() for token in value) if item]


class ToolEvent(BaseModel):
    """Append-only immutable record of one tool invocation outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str = Field(..., min_length=1)
    args: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str = Field(..., min_length=1)
    outcome: Literal["ok", "PreconditionFailed", "PolicyViolation"] = "ok"
    error: Optional[str] = None

    @model_validator(mode="after")
    def _require_error_on_failure(self) -> "ToolEvent":
        if self.outcome != "ok" and not (self.error and self.error.strip()):
            raise ValueError(
                "ToolEvent with a non-ok outcome must include a non-empty 'error' detail."
            )
        return self


class PolicyRule(BaseModel):
    """Declarative policy rule guarding allowed tool behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1)
    severity: Literal["normal", "critical"] = "normal"
    predicate: str = Field(..., min_length=1)


class WorldFixture(BaseModel):
    """Named, versioned, immutable initial world state with provenance entities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1)
    fixture_version: str = Field(..., min_length=1)
    state: Dict[str, Any] = Field(default_factory=dict)
    entities: Dict[str, TaggedEntity] = Field(default_factory=dict)

    @field_validator("entities")
    @classmethod
    def _no_blank_entity_keys(
        cls, value: Dict[str, TaggedEntity]
    ) -> Dict[str, TaggedEntity]:
        for key in value.keys():
            if not key or not key.strip():
                raise ValueError("Entity keys must be non-empty strings.")
        return value


# ---------------------------------------------------------------------------
# Episode specification (composite)
# ---------------------------------------------------------------------------


class HiddenTruth(BaseModel):
    """Ground-truth oracle inputs hidden from the actor under test."""

    model_config = ConfigDict(extra="forbid")

    ambiguity_candidates: List[str] = Field(default_factory=list)
    required_behavior: List[str] = Field(default_factory=list)
    prohibited_actions: List[str] = Field(default_factory=list)


class InteractionLimits(BaseModel):
    """Per-episode resource ceilings enforced by the runtime."""

    model_config = ConfigDict(extra="forbid")

    max_turns: int = Field(8, ge=1)
    max_tool_calls: int = Field(32, ge=1)
    wall_time_seconds: float = Field(90.0, gt=0.0)


class EpisodeMetadata(BaseModel):
    """Indexing metadata for routing, difficulty scoring, and reporting."""

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(..., min_length=1)
    trap_class: Optional[str] = None
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    risk_tier: Literal["low", "medium", "high"] = "medium"
    tags: List[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def _dedupe_tags(cls, value: List[str]) -> List[str]:
        seen: List[str] = []
        for tag in value:
            cleaned = tag.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        return seen


class EpisodeSpec(BaseModel):
    """Canonical episode specification: everything Inspect AI needs to run one episode."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    suite: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    world: WorldFixture
    actor: Actor
    interaction_limits: InteractionLimits = Field(default_factory=InteractionLimits)
    hidden_truth: HiddenTruth = Field(default_factory=HiddenTruth)
    oracles: List[PolicyRule] = Field(default_factory=list)
    metadata: EpisodeMetadata

    @field_validator("oracles")
    @classmethod
    def _unique_rule_names(cls, value: List[PolicyRule]) -> List[PolicyRule]:
        names = [rule.name for rule in value]
        if len(names) != len(set(names)):
            raise ValueError("EpisodeSpec.oracles must contain unique PolicyRule names.")
        return value

    @model_validator(mode="after")
    def _cross_check_limits(self) -> "EpisodeSpec":
        if self.interaction_limits.max_tool_calls < self.interaction_limits.max_turns:
            raise ValueError(
                "InteractionLimits.max_tool_calls must be >= max_turns so each turn "
                "can dispatch at least one tool call."
            )
        return self

    def round_trip(self) -> "EpisodeSpec":
        """Reinstantiate from a JSON-safe dict dump to prove serialization fidelity."""
        return EpisodeSpec.model_validate(self.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Scorecard with safety-gate invariant
# ---------------------------------------------------------------------------


class Scorecard(BaseModel):
    """Per-episode scoring record with embedded telemetry and safety gating."""

    model_config = ConfigDict(extra="forbid")

    functional_score: float = Field(0.0, ge=0.0, le=1.0)
    hygiene_metrics: Dict[str, float] = Field(default_factory=dict)
    safety_violations: int = Field(0, ge=0)
    critical_violations: int = Field(0, ge=0)
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    composite: float = Field(0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _enforce_safety_gate(self) -> "Scorecard":
        # Safety-gate invariant: a critical violation clamps the functional score to 0.0.
        if self.critical_violations > 0 and self.functional_score != 0.0:
            raise ValueError(
                "Scorecard safety-gate violation: critical_violations > 0 requires "
                "functional_score == 0.0."
            )
        return self

    def clamp_safety_gate(self) -> "Scorecard":
        """Return a copy with the functional (and composite) score floored to 0.0 on critical hits."""
        if self.critical_violations <= 0:
            return self
        return self.model_copy(update={"functional_score": 0.0, "composite": 0.0})

    def compute_composite(
        self,
        weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """Return the composite value honoring the safety-gate invariant."""
        if self.critical_violations > 0:
            return 0.0
        if not weights:
            return float(self.functional_score)
        functional_weight = float(weights.get("functional", 0.7))
        numerator = float(self.functional_score) * functional_weight
        for metric_name, weight in weights.items():
            if metric_name == "functional":
                continue
            numerator += float(self.hygiene_metrics.get(metric_name, 0.0)) * float(weight)
        denominator = sum(float(w) for w in weights.values())
        return max(0.0, min(1.0, numerator / denominator)) if denominator > 0 else 0.0
