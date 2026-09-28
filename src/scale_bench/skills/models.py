"""Immutable task-expert requests and geometric targets."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, TypeAlias

Arm: TypeAlias = Literal["left", "right"]
ArmSelection: TypeAlias = Arm | Literal["auto"]


@dataclass(frozen=True, slots=True)
class Pose:
    """Frame-agnostic position and orientation.

    Variables carrying a pose use ``<subject>_pose_<reference_frame>``; for
    example, ``tcp_pose_object`` is the TCP pose expressed in the object frame.
    ``env`` always means one environment's local world frame.
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


@dataclass(frozen=True, slots=True)
class Place:
    """Place an already held object using its holding arm and grasp approach axis.

    As in PickAndPlace, target yaw is free; placement chooses a reachable yaw.
    The approach axis comes from the active grasp, not a new grasp selection.
    Standalone calls use the default settling times; the composite forwards
    its configured grasp/release settling times to preserve its timing.
    """

    object_name: str
    arm: Arm
    target_object_pose_env: Pose
    approach_axis_tcp: tuple[float, float, float]
    support_settle_steps: int = 5
    release_settle_steps: int = 5

    def __post_init__(self) -> None:
        if self.arm not in ("left", "right"):
            raise ValueError("Place requires the arm already holding the object")
        if not math.isclose(math.hypot(*self.approach_axis_tcp), 1.0, abs_tol=1.0e-6):
            raise ValueError("grasp approach axis must be a unit vector")
        if self.support_settle_steps < 1 or self.release_settle_steps < 1:
            raise ValueError("placement settling requires at least one step")


SkillRequest: TypeAlias = Pick | Place | PickAndPlace


__all__ = [
    "Arm",
    "ArmSelection",
    "Pick",
    "PickAndPlace",
    "Place",
    "Pose",
    "SkillRequest",
]
