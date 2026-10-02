"""Immutable task-expert requests and geometric targets."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, TypeAlias

Arm: TypeAlias = Literal["left", "right"]
ArmSelection: TypeAlias = Arm | Literal["auto"]


@dataclass(frozen=True, slots=True)
class Pose:
    """Position and orientation in the frame named by ``<subject>_pose_<frame>``.

    For example, ``tcp_pose_object`` expresses the TCP in the object frame;
    ``env`` denotes one environment's local world frame.
    """

    position_m: tuple[float, float, float]
    orientation_xyzw: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        values = (*self.position_m, *self.orientation_xyzw)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("pose values must be finite")
        norm = math.sqrt(sum(value * value for value in self.orientation_xyzw))
        if not math.isclose(norm, 1.0, abs_tol=1.0e-6):
            raise ValueError("pose orientation must be a unit quaternion")


@dataclass(frozen=True, slots=True)
class Pick:
    object_name: str
    arm: ArmSelection
    settle_steps: int = 5


@dataclass(frozen=True, slots=True)
class PickAndPlace:
    object_name: str
    arm: ArmSelection
    target_object_pose_env: Pose
    grasp_settle_steps: int = 5
    release_settle_steps: int = 5


SkillRequest: TypeAlias = Pick | PickAndPlace


__all__ = [
    "Arm",
    "ArmSelection",
    "Pick",
    "PickAndPlace",
    "Pose",
    "SkillRequest",
]
