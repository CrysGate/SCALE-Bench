"""A resolved tabletop task composes object data, layout, a goal, and an expert."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from torch import Tensor

from scale_bench.config.base import ConfigReference, FrozenModel, Name, PositiveInt
from scale_bench.config.models.scene import SceneConfig
from scale_bench.skills.models import SkillRequest

from .evaluation import (
    BatchedEvaluatorObservation,
    EvaluationResult,
    EvaluatorObservation,
    TaskGoal,
)
from .layout import TaskLayout
from .placement import (
    PlacementContext,
    TabletopLayoutConfig,
    generate_tabletop_layout,
    validate_tabletop_layout,
)
from .rigid_object import (
    RigidObjectAssetConfig,
    RigidObjectMetadata,
    RigidObjects,
)


class TaskConfig(FrozenModel):
    """One task variant, including objects, layout, and success settings."""

    name: Name
    task: Name
    instruction: Name
    object_set: ConfigReference
    layout: TabletopLayoutConfig
    success_stability_steps: PositiveInt = 10


@dataclass(frozen=True, slots=True)
class Task(ABC):
    """One configured task; goal semantics do not depend on its controller."""

    task_id: str
    instruction: str
    config: TaskConfig
    objects: RigidObjects
    goal: TaskGoal

    @abstractmethod
    def expert(self, scene: SceneConfig, layout: TaskLayout) -> Iterator[SkillRequest]:
        """Yield this task's reference skill program for one episode."""

    @property
    def assets(self) -> Mapping[str, RigidObjectAssetConfig]:
        return self.objects.assets

    @property
    def metadata(self) -> Mapping[str, RigidObjectMetadata]:
        return self.objects.metadata

    def generate_layout(self, context: PlacementContext, seed: int) -> TaskLayout:
        return generate_tabletop_layout(
            task_id=self.task_id,
            context=context,
            asset_sizes_m=self.objects.sizes_m,
            seed=seed,
            **self.config.layout.model_dump(),
        )

    def validate_layout(self, context: PlacementContext, layout: TaskLayout) -> None:
        settings = self.config.layout
        validate_tabletop_layout(
            task_id=self.task_id,
            context=context,
            layout=layout,
            asset_sizes_m=self.objects.sizes_m,
            spawn_clearance_m=settings.spawn_clearance_m,
            minimum_object_gap_m=settings.minimum_object_gap_m,
        )

    def validate_asset_layout(self, layout: TaskLayout) -> None:
        if layout.task_id != self.task_id:
            raise ValueError(f"layout task_id {layout.task_id!r} does not match {self.task_id!r}")
        if set(layout.assets) != set(self.assets):
            raise ValueError("layout assets do not match the task's object set")

    def load_layout(self, context: PlacementContext, path: Path) -> TaskLayout:
        layout = TaskLayout.load(path)
        self.validate_layout(context, layout)
        return layout

    def check_success(self, observation: BatchedEvaluatorObservation) -> Tensor:
        return self.goal.check_success(observation)

    def evaluate(self, observation: EvaluatorObservation) -> EvaluationResult:
        return self.goal.evaluate(observation)


__all__ = ["Task", "BatchedEvaluatorObservation", "EvaluatorObservation"]
