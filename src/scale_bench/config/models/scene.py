"""Room, surfaces, cameras, and lighting configuration."""

from __future__ import annotations

from typing import Annotated, Self
from pydantic import Field, model_validator

from scale_bench.config.base import (
    AssetReference,
    CameraConvention,
    ConfigReference,
    FrozenModel,
    FiniteFloat,
    NonNegativeFloat,
    NonNegativeInt,
    OptionalAssetReference,
    Position2,
    Position3,
    PositiveFloat,
    PositiveInt,
    Quaternion,
    UnitIntervalFloat,
    require_unit_quaternion,
)


class RoomConfig(FrozenModel):
    usd_path: AssetReference
    scale: PositiveFloat = 0.5


class SurfaceConfig(FrozenModel):
    position_m: Position3
    size_m: tuple[PositiveFloat, PositiveFloat, PositiveFloat]
    material_path: OptionalAssetReference
    uv_scale: tuple[PositiveFloat, PositiveFloat] = (1.0, 1.0)
    static_friction: NonNegativeFloat
    dynamic_friction: NonNegativeFloat
    restitution: UnitIntervalFloat


class ManipulationConfig(FrozenModel):
    lift_height_m: PositiveFloat
    place_approach_distance_m: PositiveFloat = 0.10
    retreat_distance_m: PositiveFloat = 0.06
    retreat_attempts: PositiveInt = 3
    planner_attempts: PositiveInt = 3
    grasp_attempts: PositiveInt = 3
    placement_retries: NonNegativeInt = 2
    tracking_position_tolerance_m: PositiveFloat = 0.015
    tracking_orientation_tolerance_rad: PositiveFloat = 0.10
    tracking_joint_tolerance_rad: PositiveFloat = 0.10
    grasp_slip_tolerance_m: PositiveFloat = 0.025
    placement_position_tolerance_m: PositiveFloat = 0.025
    support_height_tolerance_m: PositiveFloat = 0.015
    release_joint_tolerance_m: PositiveFloat = 0.005


class OverheadCameraConfig(FrozenModel):
    profile_path: ConfigReference
    stand_usd_path: AssetReference
    stand_position_xy_m: Position2
    stand_orientation_xyzw: Quaternion
    sensor_local_position_m: Position3
    sensor_local_orientation_xyzw: Quaternion
    convention: CameraConvention = "opengl"

    @model_validator(mode="after")
    def _validate_orientations(self) -> Self:
        require_unit_quaternion(
            self.stand_orientation_xyzw,
            "stand_orientation_xyzw",
        )
        require_unit_quaternion(
            self.sensor_local_orientation_xyzw,
            "sensor_local_orientation_xyzw",
        )
        return self


class LightingConfig(FrozenModel):
    texture_path: AssetReference
    intensity: NonNegativeFloat
    dome_rotation_z_world_rad: FiniteFloat = 0.0
    exposure: FiniteFloat = 0.0
    enable_color_temperature: bool = False
    color_temperature_k: Annotated[float, Field(ge=1000, le=10000)] = 6500.0


class SceneConfig(FrozenModel):
    """Static scene description, excluding environment lifecycle settings."""

    room: RoomConfig
    ground: SurfaceConfig
    table: SurfaceConfig
    manipulation: ManipulationConfig
    camera: OverheadCameraConfig
    lighting: LightingConfig

    @property
    def table_top_z_m(self) -> float:
        return self.table.position_m[2] + self.table.size_m[2] / 2.0
