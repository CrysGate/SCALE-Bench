"""Validated object-local grasp candidates for one robot TCP."""

from __future__ import annotations

import math
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, StrictBool, field_validator, model_validator

from scale_bench.config.base import (
    FiniteFloat,
    FrozenModel,
    Name,
    NonNegativeFloat,
    NonNegativeInt,
    Position3,
    PositiveFloat,
    PositiveInt,
    UnitIntervalFloat,
    require_unit_quaternion,
)
from scale_bench.config.models.robot import TcpConfig


class AnyGraspConfig(FrozenModel):
    """Runtime AnyGrasp HTTP service and candidate-selection settings."""

    service_url: Name = "http://127.0.0.1:5001"
    request_timeout_s: PositiveFloat = 60.0
    capture_distance_m: PositiveFloat
    capture_elevation_deg: float
    capture_azimuth_offset_deg: float
    depth_trunc_m: PositiveFloat = 2.0
    top_k: PositiveInt = 100
    min_score: UnitIntervalFloat = 0.0
    collision_detection: StrictBool = True
    dense_grasp: StrictBool = False
    approach_distance_m: PositiveFloat = 0.10
    target_margin_m: NonNegativeFloat = 0.015
    minimum_target_points: PositiveInt = 128
    minimum_point_height_above_table_m: NonNegativeFloat = 0.002
    minimum_tcp_height_above_table_m: NonNegativeFloat = 0.015
    maximum_open_axis_vertical_dot: UnitIntervalFloat = 0.35

    @field_validator("service_url")
    @classmethod
    def _validate_service_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("service_url must be an absolute HTTP(S) URL")
        if parsed.query or parsed.fragment:
            raise ValueError("service_url must not contain a query or fragment")
        return normalized


class AssetGraspCandidateConfig(FrozenModel):
    """One GraspDataGen stable-closure TCP pose in the object frame."""

    candidate_id: NonNegativeInt
    robot: Name
    pose_object_tcp_xyz_xyzw: tuple[
        FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat,
        FiniteFloat, FiniteFloat, FiniteFloat,
    ]
    approach_axis_object: Position3
    closed_joint_positions_m: dict[Name, FiniteFloat] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_pose(self) -> Self:
        require_unit_quaternion(
            self.pose_object_tcp_xyz_xyzw[3:],
            "pose_object_tcp_xyz_xyzw quaternion",
        )
        axis_norm = math.sqrt(sum(value * value for value in self.approach_axis_object))
        if not math.isclose(axis_norm, 1.0, abs_tol=1.0e-6):
            raise ValueError("approach_axis_object must be a unit vector")
        return self


class AssetGraspsConfig(FrozenModel):
    """The compact grasps.yaml stored beside one object asset."""

    object: Name
    position_unit: Literal["m"]
    pose_layout: tuple[
        Literal["x"], Literal["y"], Literal["z"], Literal["qx"],
        Literal["qy"], Literal["qz"], Literal["qw"],
    ]
    tcp: TcpConfig
    approach_distance_m: PositiveFloat
    candidates: tuple[AssetGraspCandidateConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_candidates(self) -> Self:
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate grasp candidate IDs")
        return self


__all__ = ["AnyGraspConfig", "AssetGraspCandidateConfig", "AssetGraspsConfig"]
