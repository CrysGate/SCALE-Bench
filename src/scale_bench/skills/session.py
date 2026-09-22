"""Shared plan/execute/observe primitives and physical verification."""

from __future__ import annotations

import logging
import math
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass

from scale_bench.config.models.scene import ManipulationConfig

from .commands import MoveToJoints, MoveToPose, SkillCommand
from .context import GraspState, JointState, PlanningScene, SkillContext
from .errors import FailureCode, SegmentError
from .geometry import quaternion_angular_distance_rad
from .models import Arm, Pose
from .planner import SkillMotionPlanner

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SkillSettings:
    manipulation: ManipulationConfig
    arm_base_positions_env_m: Mapping[Arm, tuple[float, float, float]]
    safe_joint_positions: Mapping[Arm, tuple[float, ...]]
    gripper_open_positions: Mapping[Arm, Mapping[str, float]]


class SkillSession:
    """An episode's live context plus reusable, verified movement primitives."""

    def __init__(
        self, context: SkillContext, planner: SkillMotionPlanner, settings: SkillSettings,
    ) -> None:
        self.context = context
        self.planner = planner
        self.settings = settings
        self.config = settings.manipulation

    async def move_free(
        self, arm: Arm, target: Pose | JointState, scene: PlanningScene, stage: str,
    ) -> AsyncIterator[SkillCommand]:
        """Pose goals move the TCP; joint goals return to safe joints."""
        trajectory = await self.planner.plan_free(
            arm=arm, start=self.context.snapshot().robot(arm).joints,
            target=target, scene=scene, stage=stage,
        )
        if isinstance(target, Pose):
            yield MoveToPose(arm, target, trajectory, stage, "free")
        else:
            yield MoveToJoints(arm, target, trajectory, stage)
        self.verify_motion(arm, target, stage)

    async def move_linear(
        self, arm: Arm, target_tcp_pose_env: Pose, scene: PlanningScene,
        axis_env: tuple[float, float, float], stage: str,
    ) -> AsyncIterator[SkillCommand]:
        trajectory = await self.planner.plan_linear(
            arm=arm, start=self.context.snapshot().robot(arm).joints,
            target=target_tcp_pose_env, scene=scene, axis_env=axis_env, stage=stage,
        )
        yield MoveToPose(arm, target_tcp_pose_env, trajectory, stage, "linear")
        self.verify_motion(arm, target_tcp_pose_env, stage)

    def verify_motion(self, arm: Arm, target: Pose | JointState, stage: str) -> None:
        """Verify measured TCP tracking for poses and joints for configuration goals."""
        robot = self.context.snapshot().robot(arm)
        if isinstance(target, Pose):
            position_error_m = math.dist(robot.tcp_pose_env.position_m, target.position_m)
            orientation_error_rad = quaternion_angular_distance_rad(
                robot.tcp_pose_env.orientation_xyzw, target.orientation_xyzw,
            )
            metrics = {
                "check": "tcp_tracking",
                "position_error_m": position_error_m,
                "orientation_error_rad": orientation_error_rad,
            }
            passed = (
                position_error_m <= self.config.tracking_position_tolerance_m
                and orientation_error_rad <= self.config.tracking_orientation_tolerance_rad
            )
        else:
            joint_error_rad = float((robot.joints.positions - target.positions).abs().max())
            metrics = {"check": "joint_tracking", "joint_error_rad": joint_error_rad}
            passed = joint_error_rad <= self.config.tracking_joint_tolerance_rad
        self.verify(
            arm, stage, passed, FailureCode.TRACKING_FAILED,
            {**metrics, "actual_tcp_pose_env": asdict(robot.tcp_pose_env),
             "actual_joint_state": robot.joints.positions.tolist()},
        )

    def measure_grasp(self, object_name: str, arm: Arm, stage: str) -> GraspState:
        try:
            grasp = self.context.measure_grasp(object_name, arm)
        except SegmentError as error:
            self.verify(arm, stage, False, error.code,
                        {"check": "grasp_aperture", "reason": error.reason})
            raise
        self.verify(arm, stage, True, FailureCode.GRASP_FAILED,
                    {"check": "grasp_aperture", **asdict(grasp)})
        return grasp

    def verify_grasp_motion(self, before: GraspState, after: GraspState, stage: str) -> None:
        slip_m = math.dist(before.tcp_pose_object.position_m, after.tcp_pose_object.position_m)
        self.verify(
            after.arm, stage, slip_m <= self.config.grasp_slip_tolerance_m,
            FailureCode.GRASP_FAILED, {"check": "grasp_slip", "grasp_slip_m": slip_m},
        )

    def verify_placement(
        self, object_name: str, arm: Arm, target_object_pose_env: Pose,
        stage: str, code: FailureCode,
    ) -> None:
        """Geometric support/release check; final task evaluation checks stability.

        The requested object height encodes the supporting surface. This is a
        geometric observation, not a contact-force sensor measurement.
        """
        object_pose_env = self.context.snapshot().object(object_name).pose_env
        planar_error_m = math.dist(object_pose_env.position_m[:2], target_object_pose_env.position_m[:2])
        height_error_m = abs(object_pose_env.position_m[2] - target_object_pose_env.position_m[2])
        orientation_error_rad = quaternion_angular_distance_rad(
            object_pose_env.orientation_xyzw, target_object_pose_env.orientation_xyzw,
        )
        self.verify(
            arm, stage,
            planar_error_m <= self.config.placement_position_tolerance_m
            and height_error_m <= self.config.support_height_tolerance_m
            and orientation_error_rad <= self.config.tracking_orientation_tolerance_rad,
            code, {"check": "object_target", "object_pose_env": asdict(object_pose_env),
                   "planar_error_m": planar_error_m, "height_error_m": height_error_m,
                   "orientation_error_rad": orientation_error_rad},
        )

    def verify_open_gripper(self, arm: Arm) -> None:
        actual = self.context.snapshot().robot(arm).gripper_joint_positions
        error_m = max(
            abs(actual[name] - value)
            for name, value in self.settings.gripper_open_positions[arm].items()
        )
        self.verify(
            arm, "release", error_m <= self.config.release_joint_tolerance_m,
            FailureCode.RELEASE_FAILED, {"check": "gripper_open", "open_joint_error_m": error_m},
        )

    def verify(
        self, arm: Arm, stage: str, passed: bool, code: FailureCode,
        metrics: Mapping[str, object],
    ) -> None:
        LOGGER.info(
            "%s %s", stage, "verified" if passed else code,
            extra={"event": "MOTION-VERIFY", "event_fields": {
                "arm": arm, "stage": stage,
                "result": "SUCCESS" if passed else code, **metrics,
            }},
        )
        if not passed:
            raise SegmentError(arm, stage, code, str(dict(metrics)))

    def recovery(self, error: SegmentError, attempt: int) -> None:
        LOGGER.info(
            "%s recovery=%d %s", error.stage, attempt, error.code,
            extra={"event": "RECOVERY", "event_fields": {
                "arm": error.arm, "stage": error.stage, "result": error.code,
                "reason": error.reason, "recovery_attempt": attempt,
            }},
        )
