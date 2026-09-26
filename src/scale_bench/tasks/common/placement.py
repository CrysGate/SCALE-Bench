"""Placement context plus deterministic tabletop layout algorithms."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from typing import Self

from pydantic import field_validator

from scale_bench.config.base import (
    FiniteFloat, FrozenModel, NonNegativeFloat, Position2, PositiveFloat, PositiveInt,
)
from scale_bench.config.models.scene import SceneConfig
from scale_bench.skills.geometry import quaternion_xyzw_from_rpy

from .layout import AssetPlacement, TaskLayout


class TabletopLayoutConfig(FrozenModel):
    """Sampling settings shared by tabletop task variants."""

    spawn_clearance_m: NonNegativeFloat = 0.003
    minimum_object_gap_m: NonNegativeFloat = 0.02
    sampling_attempts_per_object: PositiveInt = 1000
    layout_sampling_attempts: PositiveInt = 32


class PlacementObstacle(FrozenModel):
    """The upright footprint of a static scene prop."""

    name: str
    object_position_env_xy_m: Position2
    size_object_xy_m: tuple[PositiveFloat, PositiveFloat]
    yaw_env_rad: FiniteFloat

    def overlaps(self, object_position_env_xy_m: Position2, clearance_m: float) -> bool:
        delta_x_env_m, delta_y_env_m = (
            value - center for value, center in zip(
                object_position_env_xy_m, self.object_position_env_xy_m, strict=True,
            )
        )
        cosine, sine = math.cos(self.yaw_env_rad), math.sin(self.yaw_env_rad)
        point_x_object_m = cosine * delta_x_env_m + sine * delta_y_env_m
        point_y_object_m = -sine * delta_x_env_m + cosine * delta_y_env_m
        gap_x_object_m = max(abs(point_x_object_m) - self.size_object_xy_m[0] / 2, 0)
        gap_y_object_m = max(abs(point_y_object_m) - self.size_object_xy_m[1] / 2, 0)
        return math.hypot(gap_x_object_m, gap_y_object_m) < clearance_m


class PlacementContext(FrozenModel):
    """Scene-derived values needed by task placement algorithms."""

    table_top_z_m: FiniteFloat
    x_range_m: tuple[FiniteFloat, FiniteFloat]
    y_range_m: tuple[FiniteFloat, FiniteFloat]
    # The original empty worktable has no obstacles; themed presets supply props.
    obstacles: tuple[PlacementObstacle, ...] = ()

    @field_validator("x_range_m", "y_range_m")
    @classmethod
    def _validate_range(cls, value: tuple[float, float]) -> tuple[float, float]:
        if value[0] >= value[1]:
            raise ValueError("lower bound must be less than upper bound")
        return value

    @classmethod
    def from_scene_config(cls, scene_config: SceneConfig) -> Self:
        """Extract placement-only values from a scene configuration."""

        area = scene_config.task_object_placement_area
        return cls(
            table_top_z_m=scene_config.table_top_z_m,
            x_range_m=area.x_range_m,
            y_range_m=area.y_range_m,
            obstacles=tuple(
                PlacementObstacle(
                    name=prop.name,
                    object_position_env_xy_m=prop.support_position_env_m[:2],
                    size_object_xy_m=prop.size_object_m[:2],
                    yaw_env_rad=prop.yaw_env_rad,
                )
                for prop in scene_config.props
                if prop.support_position_env_m[2] + prop.size_object_m[2] > scene_config.table_top_z_m
            ),
        )


def generate_tabletop_layout(
    *,
    task_id: str,
    context: PlacementContext,
    asset_sizes_m: Mapping[str, tuple[float, float, float]],
    seed: int,
    spawn_clearance_m: float,
    minimum_object_gap_m: float,
    sampling_attempts_per_object: int,
    layout_sampling_attempts: int,
) -> TaskLayout:
    """Sample bounded full-layout attempts from one deterministic random stream."""

    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    radii = _footprint_radii(asset_sizes_m)
    rng = random.Random(seed)
    sampling_order = sorted(asset_sizes_m, key=radii.__getitem__, reverse=True)
    for _ in range(layout_sampling_attempts):
        placements: dict[str, AssetPlacement] = {}

        for name in sampling_order:
            placement = _sample_object_placement(
                name=name,
                context=context,
                asset_sizes_m=asset_sizes_m,
                radii=radii,
                placements=placements,
                rng=rng,
                spawn_clearance_m=spawn_clearance_m,
                minimum_object_gap_m=minimum_object_gap_m,
                sampling_attempts=sampling_attempts_per_object,
            )
            if placement is None:
                break
            placements[name] = placement

        if len(placements) == len(asset_sizes_m):
            return TaskLayout(
                task_id=task_id,
                seed=seed,
                assets={name: placements[name] for name in asset_sizes_m},
            )

    raise RuntimeError(
        f"Could not sample a complete layout within task_object_placement_area "
        f"after {layout_sampling_attempts} layout attempts for seed {seed} "
        f"({sampling_attempts_per_object} position attempts per object)"
    )


def _sample_object_placement(
    *,
    name: str,
    context: PlacementContext,
    asset_sizes_m: Mapping[str, tuple[float, float, float]],
    radii: Mapping[str, float],
    placements: Mapping[str, AssetPlacement],
    rng: random.Random,
    spawn_clearance_m: float,
    minimum_object_gap_m: float,
    sampling_attempts: int,
) -> AssetPlacement | None:
    """Return None when position attempts are exhausted, requiring a new layout."""

    radius = radii[name]
    x_range_m, y_range_m = _center_ranges(context, name, radius)
    for _ in range(sampling_attempts):
        x_env_m = rng.uniform(*x_range_m)
        y_env_m = rng.uniform(*y_range_m)
        if any(
            obstacle.overlaps((x_env_m, y_env_m), radius + minimum_object_gap_m)
            for obstacle in context.obstacles
        ):
            continue
        if any(
            math.hypot(
                x_env_m - previous.position_m[0],
                y_env_m - previous.position_m[1],
            )
            < radius + radii[previous_name] + minimum_object_gap_m
            for previous_name, previous in placements.items()
        ):
            continue

        yaw_env_rad = rng.uniform(-math.pi, math.pi)
        return AssetPlacement(
            position_m=(
                x_env_m,
                y_env_m,
                context.table_top_z_m + asset_sizes_m[name][2] / 2.0 + spawn_clearance_m,
            ),
            orientation_xyzw=quaternion_xyzw_from_rpy(0.0, 0.0, yaw_env_rad),
        )
    return None


def validate_tabletop_layout(
    *,
    task_id: str,
    context: PlacementContext,
    layout: TaskLayout,
    asset_sizes_m: Mapping[str, tuple[float, float, float]],
    spawn_clearance_m: float,
    minimum_object_gap_m: float,
) -> None:
    """Validate identity, asset set, placement bounds, height, and spacing."""

    if layout.task_id != task_id:
        raise ValueError(
            f"layout task_id {layout.task_id!r} does not match {task_id!r}"
        )
    expected_names = set(asset_sizes_m)
    actual_names = set(layout.assets)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        unexpected = sorted(actual_names - expected_names)
        raise ValueError(
            f"layout assets do not match the task; missing={missing}, "
            f"unexpected={unexpected}"
        )

    radii = _footprint_radii(asset_sizes_m)
    for name, placement in layout.assets.items():
        x_range, y_range = _center_ranges(context, name, radii[name])
        x_m, y_m, z_m = placement.position_m
        for obstacle in context.obstacles:
            if obstacle.overlaps((x_m, y_m), radii[name] + minimum_object_gap_m):
                raise ValueError(
                    f"{name} overlaps scene prop {obstacle.name!r} "
                    "or violates minimum_object_gap_m"
                )
        if not x_range[0] <= x_m <= x_range[1]:
            raise ValueError(
                f"{name} is outside task_object_placement_area on the X axis"
            )
        if not y_range[0] <= y_m <= y_range[1]:
            raise ValueError(
                f"{name} is outside task_object_placement_area on the Y axis"
            )

        expected_z = context.table_top_z_m + asset_sizes_m[name][2] / 2.0
        expected_z += spawn_clearance_m
        if not math.isclose(z_m, expected_z, rel_tol=0.0, abs_tol=1.0e-9):
            raise ValueError(f"{name} is not at its expected tabletop height")
        if not (
            math.isclose(placement.orientation_xyzw[0], 0.0, abs_tol=1.0e-9)
            and math.isclose(
                placement.orientation_xyzw[1], 0.0, abs_tol=1.0e-9
            )
        ):
            raise ValueError(f"{name} must have an upright yaw-only orientation")

    names = list(layout.assets)
    for index, first_name in enumerate(names):
        first = layout.assets[first_name]
        for second_name in names[index + 1 :]:
            second = layout.assets[second_name]
            distance = math.hypot(
                first.position_m[0] - second.position_m[0],
                first.position_m[1] - second.position_m[1],
            )
            required = (
                radii[first_name]
                + radii[second_name]
                + minimum_object_gap_m
            )
            if distance + 1.0e-9 < required:
                raise ValueError(
                    f"{first_name} and {second_name} overlap or violate "
                    "minimum_object_gap_m"
                )


def _footprint_radii(
    asset_sizes_m: Mapping[str, tuple[float, float, float]],
) -> dict[str, float]:
    return {
        name: math.hypot(*size[:2]) / 2.0
        for name, size in asset_sizes_m.items()
    }


def _center_ranges(
    context: PlacementContext,
    name: str,
    radius: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    x_range = (context.x_range_m[0] + radius, context.x_range_m[1] - radius)
    y_range = (context.y_range_m[0] + radius, context.y_range_m[1] - radius)
    if x_range[0] > x_range[1] or y_range[0] > y_range[1]:
        raise ValueError(f"{name} does not fit inside task_object_placement_area")
    return x_range, y_range


__all__ = [
    "PlacementContext",
    "TabletopLayoutConfig",
    "generate_tabletop_layout",
    "validate_tabletop_layout",
]
