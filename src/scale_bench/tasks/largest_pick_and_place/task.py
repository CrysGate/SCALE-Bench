"""Select the unique tallest candidate and bind it to a placement goal."""

import math
from collections.abc import Iterator
from typing import Self

from pydantic import model_validator

from scale_bench.config.base import FrozenModel, PositiveFloat, UnitIntervalFloat
from scale_bench.config.models.scene import SceneConfig
from scale_bench.skills.models import PickAndPlace, Pose, SkillRequest
from scale_bench.tasks.common.fixed_target import (
    PlacementTaskConfig,
    make_placement_goal,
)
from scale_bench.tasks.common.layout import TaskLayout
from scale_bench.tasks.common.placement import PlacementContext
from scale_bench.tasks.common.rigid_object import RigidObjects
from scale_bench.tasks.common.task import Task


class TargetMatConfig(FrozenModel):
    """Visible tabletop marking; the table remains the physical support."""

    edge_margin_m: PositiveFloat
    surface_offset_m: PositiveFloat
    color_rgb: tuple[UnitIntervalFloat, UnitIntervalFloat, UnitIntervalFloat]
    center_color_rgb: tuple[UnitIntervalFloat, UnitIntervalFloat, UnitIntervalFloat]


class LargestPickAndPlaceTaskConfig(PlacementTaskConfig):
    """Separate a source area from one visible delivery destination."""

    target_mat: TargetMatConfig
    minimum_source_target_gap_m: PositiveFloat

    @model_validator(mode="after")
    def _validate_target_count(self) -> Self:
        if len(self.target_positions_env_xy_m) != 1:
            raise ValueError("largest_pick_and_place requires exactly one target mat")
        return self


class LargestPickAndPlaceTask(Task):
    """Select the tallest object and place it upright at its destination."""

    config: LargestPickAndPlaceTaskConfig

    def __init__(self, config: LargestPickAndPlaceTaskConfig, objects: RigidObjects) -> None:
        heights_m: dict[str, float] = {
            name: metadata.size[2] for name, metadata in objects.metadata.items()
        }
        maximum_height_m: float = max(heights_m.values())
        target_names: tuple[str, ...] = tuple(
            name for name, height_m in heights_m.items() if height_m == maximum_height_m
        )
        if len(heights_m) < 2 or len(target_names) != 1:
            raise ValueError(
                "largest_pick_and_place requires candidates with one unique tallest object"
            )
        super().__init__(
            task_id=config.task,
            instruction=config.instruction,
            config=config,
            objects=objects,
            goal=make_placement_goal(
                config=config,
                objects=objects,
                object_order=target_names,
            ),
        )

    @property
    def target_mat_size_xy_m(self) -> tuple[float, float]:
        object_name, = self.goal.object_names
        object_size_m: tuple[float, float, float] = self.metadata[object_name].size
        # Enclose the footprint at any sampled yaw, including placement tolerance.
        side_m: float = math.hypot(*object_size_m[:2]) + 2.0 * (
            self.config.position_tolerance_m + self.config.target_mat.edge_margin_m
        )
        return side_m, side_m

    def initial_placement_context(self, context: PlacementContext) -> PlacementContext:
        target_position_env_xy_m, = self.config.target_positions_env_xy_m
        source_lower_y_env_m: float = (
            target_position_env_xy_m[1]
            + self.target_mat_size_xy_m[1] / 2.0
            + self.config.minimum_source_target_gap_m
        )
        if source_lower_y_env_m >= context.y_range_m[1]:
            raise ValueError("target mat and source gap leave no initial placement area")
        return PlacementContext(
            table_top_z_m=context.table_top_z_m,
            x_range_m=context.x_range_m,
            y_range_m=(
                max(context.y_range_m[0], source_lower_y_env_m), context.y_range_m[1]
            ),
        )

    def expert(self, scene: SceneConfig, layout: TaskLayout) -> Iterator[SkillRequest]:
        object_name, = self.goal.object_names
        target_placements_env = self.goal.target_placements(scene.table_top_z_m)
        yield PickAndPlace(
            object_name=object_name,
            arm="auto",
            target_object_pose_env=Pose(
                position_m=target_placements_env[object_name].position_m,
                orientation_xyzw=layout.assets[object_name].orientation_xyzw,
            ),
        )
