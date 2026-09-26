"""Room, surfaces, mounts, cameras, and lighting configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scale_bench.config.base import (
    AssetReference,
    CameraConvention,
    ConfigReference,
    FiniteFloat,
    FrozenModel,
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
    require_unique,
)


class StaticPropMetadata(BaseModel):
    """Geometry contract shared by spawning and conservative planning bounds."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    size_object_m: tuple[PositiveFloat, PositiveFloat, PositiveFloat]
    role: Literal["background"]
    origin: Literal["visual_aabb_center"]
    meters_per_unit: Literal[1.0]
    up_axis: Literal["Z"]


class StaticPropConfig(FrozenModel):
    """A centered, metre/Z-up background asset resting at a fixed support point.

    Props stay upright; yaw changes their heading without changing support height.
    Their measured bounds are also used by CuRobo as conservative obstacles.
    """

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    usd_path: AssetReference
    metadata_path: AssetReference
    support_position_env_m: Position3
    yaw_env_rad: FiniteFloat

    @property
    def size_object_m(self) -> tuple[float, float, float]:
        metadata = StaticPropMetadata.model_validate_json(
            Path(self.metadata_path).read_text(encoding="utf-8")
        )
        return metadata.size_object_m

    @property
    def object_position_env_m(self) -> tuple[float, float, float]:
        x_m, y_m, support_z_m = self.support_position_env_m
        return x_m, y_m, support_z_m + self.size_object_m[2] / 2


class RoomConfig(FrozenModel):
    usd_path: AssetReference
    scale: PositiveFloat = 0.5
    # Existing room assets are authored at the environment origin.
    room_position_env_m: Position3 = (0.0, 0.0, 0.0)
    yaw_env_rad: FiniteFloat = 0.0
    # Paths are relative to the USD default prim; presets omit duplicates here.
    excluded_prim_paths: tuple[str, ...] = ()

    @field_validator("excluded_prim_paths")
    @classmethod
    def _validate_exclusions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not path or path.startswith("/") or ".." in path.split("/") for path in value):
            raise ValueError("room exclusions must be paths below the default prim")
        return value


class ScalarTextureConfig(FrozenModel):
    """Select one channel from a scalar map or a packed ORM texture."""

    path: AssetReference
    channel: Literal["r", "g", "b"]


class PbrMaterialConfig(FrozenModel):
    """Metallic/roughness PBR textures with physical repeat dimensions."""

    base_color_texture: AssetReference
    normal_texture: AssetReference
    roughness: ScalarTextureConfig
    metallic: ScalarTextureConfig
    texture_size_m: tuple[PositiveFloat, PositiveFloat]


class SurfaceConfig(FrozenModel):
    position_m: Position3
    size_m: tuple[PositiveFloat, PositiveFloat, PositiveFloat]
    material_path: OptionalAssetReference
    uv_scale: tuple[PositiveFloat, PositiveFloat] = (1.0, 1.0)
    static_friction: NonNegativeFloat
    dynamic_friction: NonNegativeFloat
    restitution: UnitIntervalFloat
    # MDL and untextured legacy surfaces omit PBR; PBR surfaces set material_path: null.
    pbr: PbrMaterialConfig | None = None

    @model_validator(mode="after")
    def _validate_material(self) -> Self:
        if self.pbr is not None and self.material_path is not None:
            raise ValueError("choose either material_path (MDL) or pbr")
        if self.pbr is not None and self.uv_scale != (1.0, 1.0):
            raise ValueError("PBR uses texture_size_m instead of uv_scale")
        return self


class RobotMountConfig(FrozenModel):
    position_xy_m: Position2
    orientation_xyzw: Quaternion

    @model_validator(mode="after")
    def _validate_orientation(self) -> Self:
        require_unit_quaternion(self.orientation_xyzw, "orientation_xyzw")
        return self


class RobotMountsConfig(FrozenModel):
    left: RobotMountConfig
    right: RobotMountConfig


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


class AreaLightConfig(FrozenModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    light_position_env_m: Position3
    light_orientation_env_xyzw: Quaternion
    radius_m: PositiveFloat
    intensity: NonNegativeFloat
    color: tuple[UnitIntervalFloat, UnitIntervalFloat, UnitIntervalFloat]

    @model_validator(mode="after")
    def _validate_orientation(self) -> Self:
        require_unit_quaternion(self.light_orientation_env_xyzw, "light_orientation_env_xyzw")
        return self


class LightingProfileConfig(FrozenModel):
    lights: tuple[AreaLightConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_names(self) -> Self:
        require_unique(tuple(light.name for light in self.lights), "light names")
        return self


class LightingConfig(FrozenModel):
    texture_path: AssetReference
    intensity: NonNegativeFloat
    # The original scene uses only its HDRI; themed scenes select a key light.
    profile_path: str | None = Field(
        default=None, json_schema_extra={"path_kind": "config"},
    )


class TaskObjectPlacementArea(FrozenModel):
    x_range_m: tuple[FiniteFloat, FiniteFloat]
    y_range_m: tuple[FiniteFloat, FiniteFloat]

    @field_validator("x_range_m", "y_range_m")
    @classmethod
    def _validate_range(cls, value: tuple[float, float]) -> tuple[float, float]:
        if value[0] >= value[1]:
            raise ValueError("lower bound must be less than upper bound")
        return value


class SceneConfig(FrozenModel):
    """Static scene description, excluding environment lifecycle settings."""

    room: RoomConfig
    ground: SurfaceConfig
    table: SurfaceConfig
    task_object_placement_area: TaskObjectPlacementArea
    robot_mounts: RobotMountsConfig
    manipulation: ManipulationConfig
    camera: OverheadCameraConfig
    lighting: LightingConfig
    # Existing scenes have no props; themed scenes explicitly populate this list.
    props: tuple[StaticPropConfig, ...] = ()

    @model_validator(mode="after")
    def _validate_props(self) -> Self:
        require_unique(tuple(prop.name for prop in self.props), "scene prop names")
        return self

    @property
    def table_top_z_m(self) -> float:
        return self.table.position_m[2] + self.table.size_m[2] / 2.0
