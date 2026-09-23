"""Validated object-local grasp candidates for one robot TCP."""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import Field, model_validator

from scale_bench.config.base import (
    FiniteFloat,
    FrozenModel,
    Name,
    NonNegativeInt,
    Position3,
    PositiveFloat,
    require_unit_quaternion,
)
from scale_bench.config.models.robot import TcpConfig


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


__all__ = ["AssetGraspCandidateConfig", "AssetGraspsConfig"]
