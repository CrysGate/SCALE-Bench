"""Simulator-independent task evaluation result values."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol, TypeAlias

from torch import Tensor

from .placement import PlacementContext


EvaluatorObservation: TypeAlias = Mapping[str, Tensor]
BatchedEvaluatorObservation: TypeAlias = Mapping[str, Tensor]


@dataclass(frozen=True, slots=True)
class ObjectPositions:
    """Environment-frame positions of the named rigid objects."""

    object_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObjectOrientations:
    """Environment-frame XYZW orientations of the named rigid objects."""

    object_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixedPositions:
    """Task-provided environment-frame positions for fixed destinations."""

    positions_env_m: tuple[tuple[float, float, float], ...]


# The three observation sources consumed by the existing goals.
ObservationSource: TypeAlias = ObjectPositions | ObjectOrientations | FixedPositions


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Success, progress, and diagnostics for one environment."""

    success: bool
    progress: float
    metrics: Mapping[str, float] = field(default_factory=dict)
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.success) is not bool:
            raise TypeError("success must be a bool")
        if not math.isfinite(self.progress) or not 0.0 <= self.progress <= 1.0:
            raise ValueError("progress must be a finite value between 0 and 1")
        if any(not name for name in self.metrics):
            raise ValueError("metric names must not be empty")
        if any(not math.isfinite(value) for value in self.metrics.values()):
            raise ValueError("metrics must contain only finite values")
        if self.success and self.failure_reason is not None:
            raise ValueError("a successful evaluation cannot have a failure reason")
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


class TaskGoal(Protocol):
    """Pure goal semantics; adapters implement observation sources."""

    def observation_sources(
        self, context: PlacementContext,
    ) -> Mapping[str, ObservationSource]: ...

    def check_success(self, observation: BatchedEvaluatorObservation) -> Tensor: ...

    def evaluate(self, observation: EvaluatorObservation) -> EvaluationResult: ...


__all__ = [
    "BatchedEvaluatorObservation", "EvaluationResult",
    "EvaluatorObservation", "FixedPositions", "ObjectOrientations",
    "ObjectPositions", "ObservationSource", "TaskGoal",
]
