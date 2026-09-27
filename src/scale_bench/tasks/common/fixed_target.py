"""Fixed-placement goals and tensor measurements, independent of controllers."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field
from torch import Tensor, where
from torch.linalg import vector_norm

from scale_bench.config.base import Position2, PositiveFloat

from .evaluation import (
    BatchedEvaluatorObservation, EvaluationResult, EvaluatorObservation,
    FixedPositions, ObjectOrientations, ObjectPositions, ObservationSource,
)
from .layout import AssetPlacement
from .placement import PlacementContext
from .rigid_object import RigidObjects
from .task import TaskConfig


class PlacementTaskConfig(TaskConfig):
    """Destinations and scoring tolerances for upright-placement tasks."""

    target_positions_env_xy_m: tuple[Position2, ...] = Field(min_length=1)
    position_tolerance_m: PositiveFloat = 0.025
    height_tolerance_m: PositiveFloat = 0.015
    upright_tolerance_rad: PositiveFloat = 0.10


@dataclass(frozen=True, slots=True)
class PlacementStatus:
    """Final object pose and geometric errors for one target slot."""

    object_name: str
    slot_index: int
    object_position_env_m: tuple[float, float, float]
    target_position_env_m: tuple[float, float, float]
    position_error_env_xyz_m: tuple[float, float, float]
    position_error_m: float
    height_error_m: float
    upright_error_rad: float
    placed: bool


@dataclass(frozen=True, slots=True)
class PlacementResult(EvaluationResult):
    """Task result with per-object fixed-target placement diagnostics."""

    statuses: tuple[PlacementStatus, ...] = ()


@dataclass(frozen=True, slots=True)
class _BatchedPlacementMeasurements:
    """Placement measurements with environment and object dimensions."""

    object_positions_env_m: Tensor
    target_positions_env_m: Tensor
    position_errors_env_xyz_m: Tensor
    planar_position_errors_env_m: Tensor
    height_errors_env_m: Tensor
    upright_errors_env_rad: Tensor
    placed: Tensor


@dataclass(frozen=True, slots=True)
class FixedPlacementGoal:
    """Ordered objects must be upright at their corresponding destinations."""

    object_names: tuple[str, ...]
    target_positions_env_xy_m: tuple[tuple[float, float], ...]
    object_heights_m: tuple[float, ...]
    config: PlacementTaskConfig

    def observation_sources(
        self, context: PlacementContext,
    ) -> dict[str, ObservationSource]:
        target_placements_env = self.target_placements(context)
        return {
            "object_positions_m": ObjectPositions(self.object_names),
            "object_orientations_xyzw": ObjectOrientations(self.object_names),
            "target_positions_m": FixedPositions(
                tuple(target_placements_env[name].position_m for name in self.object_names),
            ),
        }

    def target_placements(self, context: PlacementContext) -> dict[str, AssetPlacement]:
        return {
            name: AssetPlacement(
                position_m=(
                    *target_position_env_xy_m,
                    context.table_top_z_m + height_m / 2.0,
                ),
                orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            )
            for name, target_position_env_xy_m, height_m in zip(
                self.object_names, self.target_positions_env_xy_m,
                self.object_heights_m, strict=True,
            )
        }

    def evaluate(self, observation: EvaluatorObservation) -> PlacementResult:
        statuses = self._placement_statuses(observation)
        placed_count = sum(status.placed for status in statuses)
        success = placed_count == len(statuses)
        if len(statuses) == 1:
            status = statuses[0]
            metrics = {
                "position_error_m": status.position_error_m,
                "height_error_m": status.height_error_m,
                "upright_error_rad": status.upright_error_rad,
            }
            failure = f"{status.object_name} is outside the fixed target slot"
        else:
            metrics = {
                "placed_count": float(placed_count),
                "maximum_position_error_m": max(s.position_error_m for s in statuses),
                "maximum_height_error_m": max(s.height_error_m for s in statuses),
                "maximum_upright_error_rad": max(s.upright_error_rad for s in statuses),
            }
            failure = "one or more objects are misplaced"
        return PlacementResult(
            success=success, progress=placed_count / len(statuses), metrics=metrics,
            failure_reason=None if success else failure, statuses=statuses,
        )

    def check_success(
        self,
        observation: BatchedEvaluatorObservation,
    ) -> Tensor:
        """Require every object to satisfy its fixed-slot tolerances."""

        return self._measure_placements(observation).placed.all(dim=1)

    def _placement_statuses(
        self,
        observation: EvaluatorObservation,
    ) -> tuple[PlacementStatus, ...]:
        batched_observation = {
            "object_positions_m": _unbatched_observation_tensor(
                observation,
                "object_positions_m",
                object_count=len(self.object_names),
                components=3,
            ).unsqueeze(0),
            "target_positions_m": _unbatched_observation_tensor(
                observation,
                "target_positions_m",
                object_count=len(self.object_names),
                components=3,
            ).unsqueeze(0),
            "object_orientations_xyzw": _unbatched_observation_tensor(
                observation,
                "object_orientations_xyzw",
                object_count=len(self.object_names),
                components=4,
            ).unsqueeze(0),
        }
        measurements = self._measure_placements(batched_observation)
        object_positions_env_m = (
            measurements.object_positions_env_m[0].detach().cpu().tolist()
        )
        target_positions_env_m = (
            measurements.target_positions_env_m[0].detach().cpu().tolist()
        )
        position_errors_env_xyz_m = (
            measurements.position_errors_env_xyz_m[0].detach().cpu().tolist()
        )
        planar_position_errors_env_m = (
            measurements.planar_position_errors_env_m[0].detach().cpu().tolist()
        )
        height_errors_env_m = (
            measurements.height_errors_env_m[0].detach().cpu().tolist()
        )
        upright_errors_env_rad = (
            measurements.upright_errors_env_rad[0].detach().cpu().tolist()
        )
        placed = measurements.placed[0].detach().cpu().tolist()

        return tuple(
            PlacementStatus(
                object_name=object_name,
                slot_index=slot_index,
                object_position_env_m=tuple(object_positions_env_m[slot_index]),
                target_position_env_m=tuple(target_positions_env_m[slot_index]),
                position_error_env_xyz_m=tuple(
                    position_errors_env_xyz_m[slot_index]
                ),
                position_error_m=planar_position_errors_env_m[slot_index],
                height_error_m=height_errors_env_m[slot_index],
                upright_error_rad=upright_errors_env_rad[slot_index],
                placed=placed[slot_index],
            )
            for slot_index, object_name in enumerate(self.object_names)
        )

    def _measure_placements(
        self,
        observation: BatchedEvaluatorObservation,
    ) -> _BatchedPlacementMeasurements:
        object_count = len(self.object_names)
        object_positions_env_m = _batched_observation_tensor(
            observation,
            "object_positions_m",
            object_count=object_count,
            components=3,
        )
        target_positions_env_m = _batched_observation_tensor(
            observation,
            "target_positions_m",
            object_count=object_count,
            components=3,
        )
        object_orientations_env_xyzw = _batched_observation_tensor(
            observation,
            "object_orientations_xyzw",
            object_count=object_count,
            components=4,
        )

        position_errors_env_xyz_m = (
            object_positions_env_m - target_positions_env_m
        )
        planar_position_errors_env_m = vector_norm(
            position_errors_env_xyz_m[..., :2],
            dim=-1,
        )
        height_errors_env_m = position_errors_env_xyz_m[..., 2].abs()
        object_orientation_norm = vector_norm(
            object_orientations_env_xyzw,
            dim=-1,
        )
        safe_object_orientation_norm = object_orientation_norm.clamp_min(1.0e-8)
        normalized_orientation_env_xy = (
            object_orientations_env_xyzw[..., :2]
            / safe_object_orientation_norm.unsqueeze(-1)
        )
        object_up_dot_env = (
            1.0 - 2.0 * normalized_orientation_env_xy.square().sum(dim=-1)
        ).clamp(-1.0, 1.0)
        upright_errors_env_rad = object_up_dot_env.acos()
        upright_errors_env_rad = where(
            object_orientation_norm > 1.0e-8,
            upright_errors_env_rad,
            upright_errors_env_rad.new_full(
                upright_errors_env_rad.shape,
                float("inf"),
            ),
        )

        target_config = self.config
        placed = (
            (
                planar_position_errors_env_m
                <= target_config.position_tolerance_m
            )
            & (height_errors_env_m <= target_config.height_tolerance_m)
            & (upright_errors_env_rad <= target_config.upright_tolerance_rad)
        )
        return _BatchedPlacementMeasurements(
            object_positions_env_m=object_positions_env_m,
            target_positions_env_m=target_positions_env_m,
            position_errors_env_xyz_m=position_errors_env_xyz_m,
            planar_position_errors_env_m=planar_position_errors_env_m,
            height_errors_env_m=height_errors_env_m,
            upright_errors_env_rad=upright_errors_env_rad,
            placed=placed,
        )


def _batched_observation_tensor(
    observation: BatchedEvaluatorObservation,
    name: str,
    *,
    object_count: int,
    components: int,
) -> Tensor:
    value = observation[name]
    if value.ndim != 3 or value.shape[1:] != (object_count, components):
        raise ValueError(
            f"{name} must have shape (num_envs, {object_count}, {components})"
        )
    if not value.is_floating_point():
        raise TypeError(f"{name} must use a floating-point dtype")
    return value


def _unbatched_observation_tensor(
    observation: EvaluatorObservation,
    name: str,
    *,
    object_count: int,
    components: int,
) -> Tensor:
    value = observation[name]
    expected_shape = (object_count, components)
    if value.ndim != 2 or value.shape != expected_shape:
        raise ValueError(f"{name} must have shape {expected_shape}")
    if not value.is_floating_point():
        raise TypeError(f"{name} must use a floating-point dtype")
    return value


def make_placement_goal(
    *,
    config: PlacementTaskConfig,
    objects: RigidObjects,
    object_order: tuple[str, ...],
) -> FixedPlacementGoal:
    """Bind a selection/order rule to a reusable placement goal."""

    if len(object_order) != len(config.target_positions_env_xy_m):
        raise ValueError("the number of selected objects must match the target slots")
    return FixedPlacementGoal(
        object_names=object_order,
        target_positions_env_xy_m=config.target_positions_env_xy_m,
        object_heights_m=tuple(objects.metadata[name].size[2] for name in object_order),
        config=config,
    )
