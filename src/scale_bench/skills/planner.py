"""Task-independent adapters for one immediately executable motion segment."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, TypeAlias

from .context import JointState, JointTrajectory, PlanningScene
from .errors import PlanningError
from .models import Arm, Pose

if TYPE_CHECKING:
    from scale_bench.isaaclab.runtime.curobo_parallel import QueuedCuroboMotionPlanner

LOGGER = logging.getLogger(__name__)
PlanningStage: TypeAlias = str


class SkillMotionPlanner:
    """Consume explicit state, target, scene and constraint, without task logic."""

    def __init__(
        self, backends: Mapping[Arm, QueuedCuroboMotionPlanner], max_attempts: int,
    ) -> None:
        self._backends = dict(backends)
        self._max_attempts = max_attempts

    async def solve_ik(
        self, *, arm: Arm, start: JointState, target: Pose,
        scene: PlanningScene, stage: str,
    ) -> None:
        """Feasibility query for candidate selection; never produces a trajectory."""
        await self._backends[arm].solve_ik(start, target, scene, stage)

    async def plan_free(
        self, *, arm: Arm, start: JointState, target: Pose | JointState,
        scene: PlanningScene, stage: str,
    ) -> JointTrajectory:
        """Pose targets serve approach, transport and place; joints serve safe return."""
        return await self._plan(arm, start, target, scene, stage, None)

    async def plan_linear(
        self, *, arm: Arm, start: JointState, target: Pose,
        scene: PlanningScene, axis_env: tuple[float, float, float], stage: str,
    ) -> JointTrajectory:
        return await self._plan(arm, start, target, scene, stage, axis_env)

    async def _plan(
        self, arm: Arm, start: JointState, target: Pose | JointState,
        scene: PlanningScene, stage: str,
        axis_env: tuple[float, float, float] | None,
    ) -> JointTrajectory:
        """None is the free-motion constraint; joint targets are always free."""
        backend = self._backends[arm]
        fields = {
            "arm": arm, "stage": stage,
            "motion_type": "free" if axis_env is None else "linear",
            "start_joint_state": start.positions.tolist(),
            "target_type": "tcp_pose_env" if isinstance(target, Pose) else "joint_state",
            "target": asdict(target) if isinstance(target, Pose) else target.positions.tolist(),
            "axis_env": axis_env,
            "scene": {
                "table": asdict(scene.table),
                "camera_stand": [asdict(item) for item in scene.camera_stand],
                "objects": [asdict(item) for item in scene.objects],
                "tool": asdict(scene.tool),
                "gripper_joint_positions": dict(scene.gripper_joint_positions),
                "check_finger_collision": scene.check_finger_collision,
                "other_arm": scene.other_arm,
                "other_joint_state": scene.other_robot.joints.positions.tolist(),
            },
        }
        for attempt in range(self._max_attempts):
            try:
                if isinstance(target, JointState):
                    trajectory = await backend.plan_joints(start, target, scene, stage)
                else:
                    trajectory = await backend.plan_pose(start, target, scene, stage, axis_env)
            except PlanningError as error:
                LOGGER.info(
                    "%s attempt=%d %s", stage, attempt + 1, error.code,
                    extra={"event": "MOTION-PLAN", "event_fields": {
                        **fields, "result": error.code, "retry_count": attempt,
                        "retryable": error.retryable, "reason": error.reason,
                    }},
                )
                if not error.retryable or attempt + 1 == self._max_attempts:
                    raise
            else:
                backend.commit_inspection_stages((stage,))
                LOGGER.info(
                    "%s planned waypoints=%d retries=%d", stage,
                    len(trajectory.positions), attempt,
                    extra={"event": "MOTION-PLAN", "event_fields": {
                        **fields, "result": "SUCCESS", "retry_count": attempt,
                        "waypoints": len(trajectory.positions),
                    }},
                )
                return trajectory
        raise RuntimeError("unreachable planning attempt")


__all__ = ["PlanningStage", "SkillMotionPlanner"]
