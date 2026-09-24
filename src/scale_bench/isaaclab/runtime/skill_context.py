"""Live Isaac Lab state and the skill-facing grasp service facade."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict

from scale_bench.config.models.robot import RobotConfig
from scale_bench.config.models.scene import SceneConfig
from scale_bench.skills.context import (
    GraspCandidate,
    GraspState,
    JointState,
    RobotState,
    SceneObject,
    SceneSnapshot,
)
from scale_bench.skills.errors import FailureCode, SegmentError
from scale_bench.skills.geometry import compose_pose, inverse_pose, relative_pose
from scale_bench.skills.models import Arm, Pose
from scale_bench.tasks.common.rigid_object import RigidObjectTask

from .environment import ScaleBenchEnv
from .grasp_candidates import IsaacLabGraspCandidates
from .robot_geometry import (
    camera_position_tcp_m,
    camera_stand_collision_objects_env,
    fixed_urdf_frame_pose,
)

LOGGER = logging.getLogger(__name__)


class IsaacLabSkillContext:
    """Read robot/object state and delegate candidate acquisition to its service."""

    def __init__(
        self,
        env: ScaleBenchEnv,
        task: RigidObjectTask,
        scene_config: SceneConfig,
        robot_configs: Mapping[Arm, RobotConfig],
        *,
        env_id: int,
    ) -> None:
        if env_id < 0 or env_id >= env.num_envs:
            raise ValueError(f"env_id must be in [0, {env.num_envs})")
        self._env = env
        self._env_id = env_id
        self._object_sizes_m = {
            name: metadata.size for name, metadata in task.metadata.items()
        }
        self._table = SceneObject(
            "table",
            Pose(scene_config.table.position_m, (0.0, 0.0, 0.0, 1.0)),
            scene_config.table.size_m,
        )
        self._camera_stand = camera_stand_collision_objects_env(scene_config)
        self._tcp_body_indices = {}
        self._arm_joint_indices = {}
        self._gripper_joint_indices = {}
        self._gripper_configs = {
            arm: robot_config.gripper for arm, robot_config in robot_configs.items()
        }
        self._tcp_poses_ee_body = {}
        self._camera_positions_tcp_m = {}
        for arm in ("left", "right"):
            robot_config = robot_configs[arm]
            kinematics = robot_config.kinematics
            tcp = kinematics.tcp
            robot = env.scene[f"{arm}_robot"]
            body_indices, body_names = robot.find_bodies(kinematics.ee_body)
            if len(body_indices) != 1 or body_names != [kinematics.ee_body]:
                raise ValueError(
                    f"{arm} robot EE body {kinematics.ee_body!r} did not "
                    "resolve to exactly one articulation body"
                )
            tcp_parent_pose_ee_body = fixed_urdf_frame_pose(
                robot_config.urdf_path,
                kinematics.ee_body,
                tcp.parent_frame,
            )
            self._tcp_body_indices[arm] = body_indices[0]
            joint_indices, joint_names = robot.find_joints(
                kinematics.arm_joint_names,
                preserve_order=True,
            )
            if tuple(joint_names) != kinematics.arm_joint_names:
                raise ValueError(f"{arm} robot arm joints do not match its profile")
            self._arm_joint_indices[arm] = joint_indices
            gripper = robot_config.gripper
            gripper_indices, gripper_names = robot.find_joints(
                gripper.joint_names,
                preserve_order=True,
            )
            if tuple(gripper_names) != gripper.joint_names:
                raise ValueError(f"{arm} robot gripper joints do not match its profile")
            self._gripper_joint_indices[arm] = gripper_indices
            self._tcp_poses_ee_body[arm] = compose_pose(
                tcp_parent_pose_ee_body,
                Pose(tcp.position_m, tcp.orientation_xyzw),
            )
            self._camera_positions_tcp_m[arm] = camera_position_tcp_m(
                robot_config,
                inverse_pose(self._tcp_poses_ee_body[arm]),
            )
        self._grasps = IsaacLabGraspCandidates(task, robot_configs)

    def snapshot(self) -> SceneSnapshot:
        """Read current robot, static-scene, and task-object geometry."""

        return SceneSnapshot(
            left_robot=self._robot_state("left"),
            right_robot=self._robot_state("right"),
            table=self._table,
            camera_stand=self._camera_stand,
            objects=tuple(
                SceneObject(object_name, self._object_pose_env(object_name), size_m)
                for object_name, size_m in self._object_sizes_m.items()
            ),
        )

    def grasp_candidates(
        self,
        object_name: str,
        arm: Arm,
    ) -> tuple[GraspCandidate, ...]:
        """Return score-ordered object-frame TCP candidates for one arm."""

        return self._grasps.candidates(object_name, arm)

    def measure_grasp(self, object_name: str, arm: Arm) -> GraspState:
        """Measure the live object-to-TCP relation after gripper settling."""

        aperture_m = self._gripper_aperture_m(arm)
        minimum_aperture_m = self._gripper_configs[arm].minimum_grasp_aperture_m
        if aperture_m < minimum_aperture_m:
            raise SegmentError(
                arm, "measure_grasp", FailureCode.GRASP_FAILED,
                f"{arm} gripper does not hold {object_name!r}: "
                f"aperture={aperture_m:.6g} m, "
                f"minimum={minimum_aperture_m:.6g} m"
            )
        object_pose_env = self._object_pose_env(object_name)
        tcp_pose_env = self._tcp_pose_env(arm)
        tcp_pose_object = relative_pose(object_pose_env, tcp_pose_env)
        grasp = GraspState(
            object_name,
            arm,
            aperture_m,
            object_pose_env,
            tcp_pose_env,
            tcp_pose_object,
        )
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                "%s measured grasp aperture=%.4f m", arm, aperture_m,
                extra={"event": "GRASP-STATE", "event_fields": {
                    "object": object_name, "arm": arm, "grasp": asdict(grasp),
                }},
            )
        return grasp

    def _gripper_aperture_m(self, arm: Arm) -> float:
        robot = self._env.scene[f"{arm}_robot"]
        positions = robot.data.joint_pos.torch[
            self._env_id,
            self._gripper_joint_indices[arm],
        ]
        joint_positions = dict(
            zip(
                self._gripper_configs[arm].joint_names,
                positions.detach().cpu().tolist(),
                strict=True,
            )
        )
        return self._gripper_configs[arm].aperture_m(joint_positions)

    def _robot_state(self, arm: Arm) -> RobotState:
        robot = self._env.scene[f"{arm}_robot"]
        joints = (
            robot.data.joint_pos.torch[
                self._env_id,
                self._arm_joint_indices[arm],
            ]
            .detach()
            .clone()
        )
        return RobotState(
            JointState(joints),
            self._tcp_pose_env(arm),
            self._camera_positions_tcp_m[arm],
            dict(
                zip(
                    self._gripper_configs[arm].joint_names,
                    robot.data.joint_pos.torch[
                        self._env_id, self._gripper_joint_indices[arm]
                    ].detach().cpu().tolist(),
                    strict=True,
                )
            ),
        )

    def _tcp_pose_env(self, arm: Arm) -> Pose:
        robot = self._env.scene[f"{arm}_robot"]
        body_index = self._tcp_body_indices[arm]
        env_origin = self._env.scene.env_origins[self._env_id]
        ee_body_position_env_m = (
            robot.data.body_pos_w.torch[self._env_id, body_index] - env_origin
        )
        ee_body_orientation_env_xyzw = robot.data.body_quat_w.torch[
            self._env_id, body_index
        ]
        ee_body_pose_env = Pose(
            tuple(ee_body_position_env_m.detach().cpu().tolist()),
            tuple(ee_body_orientation_env_xyzw.detach().cpu().tolist()),
        )
        return compose_pose(ee_body_pose_env, self._tcp_poses_ee_body[arm])

    def _object_pose_env(self, object_name: str) -> Pose:
        if object_name not in self._object_sizes_m:
            raise ValueError(f"unknown task object: {object_name!r}")
        object_position_env_m = (
            self._env.scene[object_name].data.root_pos_w.torch[self._env_id]
            - self._env.scene.env_origins[self._env_id]
        )
        object_orientation_env_xyzw = self._env.scene[
            object_name
        ].data.root_quat_w.torch[self._env_id]
        return Pose(
            tuple(object_position_env_m.detach().cpu().tolist()),
            tuple(object_orientation_env_xyzw.detach().cpu().tolist()),
        )


__all__ = ["IsaacLabSkillContext"]
