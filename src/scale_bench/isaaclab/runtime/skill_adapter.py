"""Isaac Lab adapters for the simulator-independent skill programs.

The skill package deliberately knows nothing about Isaac Lab.  This module is
the small runtime bridge used by the demo-generation entry point: it reads
live articulation/object state, loads the physically validated grasp catalog,
and plans Piper arm motion with a URDF-backed numerical IK solver.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pinocchio as pin
import torch

from grasp_data_gen.results import load_grasp_file
from scale_bench.config.models.robot import RobotConfig
from scale_bench.skills.context import (
    EmptyTool,
    GraspCandidate,
    GraspState,
    JointState,
    JointTrajectory,
    PlanningScene,
    RobotState,
    SceneObject,
    SceneSnapshot,
    SkillContext,
)
from scale_bench.skills.errors import PlanningError, SkillError
from scale_bench.skills.geometry import (
    compose_pose,
    inverse_pose,
    multiply_quaternions_xyzw,
    normalize_quaternion_xyzw,
    relative_pose,
    rotate_vector_xyzw,
)
from scale_bench.skills.models import Arm, Pose
from scale_bench.tasks.common.rigid_object import RigidObjectTask


def _tensor(value: Any) -> torch.Tensor:
    """Unwrap Isaac Lab's tensor proxy without copying unnecessarily."""

    return value.torch if hasattr(value, "torch") else value


def _pose_from_xyzw(position: Any, orientation: Any) -> Pose:
    position_values = tuple(float(value) for value in _tensor(position).detach().cpu())
    orientation_values = tuple(
        float(value) for value in _tensor(orientation).detach().cpu()
    )
    return Pose(position_values, normalize_quaternion_xyzw(orientation_values))


def _env_position(position_world: Any, env_origin: Any) -> tuple[float, float, float]:
    position = _tensor(position_world).detach().cpu()
    origin = _tensor(env_origin).detach().cpu()
    return tuple(float(value) for value in position - origin)


class IsaacLabSkillContext(SkillContext):
    """Read one environment slot from a live :class:`ScaleBenchEnv`."""

    def __init__(
        self,
        env: Any,
        task: RigidObjectTask,
        left_robot_config: RobotConfig,
        right_robot_config: RobotConfig,
        grasp_file: Path,
        *,
        env_id: int = 0,
        tcp_from_ee: Pose | None = None,
    ) -> None:
        self.env = env
        self.task = task
        self.robot_configs = {"left": left_robot_config, "right": right_robot_config}
        self.env_id = env_id
        self._grasp_file = grasp_file
        self._grasp_data = load_grasp_file(grasp_file)
        self._tcp_from_ee = tcp_from_ee or self._load_tcp_transform()

    @property
    def tcp_from_ee(self) -> Pose:
        return self._tcp_from_ee

    def _load_tcp_transform(self) -> Pose:
        base_to_tcp = self._grasp_data.tcp_definition.base_to_tcp
        return Pose(base_to_tcp.position_m, base_to_tcp.orientation_xyzw)

    def snapshot(self) -> SceneSnapshot:
        origin = self.env.scene.env_origins[self.env_id]
        left = self._robot_state("left", origin)
        right = self._robot_state("right", origin)
        table_cfg = self.env.scene.cfg.table
        table_size = tuple(float(value) for value in table_cfg.spawn.size)
        table = SceneObject(
            "table",
            Pose(tuple(float(value) for value in table_cfg.init_state.pos), (0.0, 0.0, 0.0, 1.0)),
            table_size,
        )
        objects = tuple(
            self._object_state(name, origin)
            for name in self.task.assets
        )
        return SceneSnapshot(left, right, table, objects)

    def _object_state(self, name: str, origin: Any) -> SceneObject:
        asset = self.env.scene[name]
        position = _env_position(asset.data.root_pos_w[self.env_id], origin)
        orientation = tuple(
            float(value)
            for value in _tensor(asset.data.root_quat_w[self.env_id]).detach().cpu()
        )
        metadata = self.task.metadata[name]
        return SceneObject(
            name,
            Pose(position, normalize_quaternion_xyzw(orientation)),
            tuple(float(value) for value in metadata.size),
        )

    def _robot_state(self, arm: Arm, origin: Any) -> RobotState:
        config = self.robot_configs[arm]
        asset = self.env.scene[f"{arm}_robot"]
        joint_ids, _ = asset.find_joints(
            list(config.kinematics.arm_joint_names),
            preserve_order=True,
        )
        joints = JointState(
            asset.data.joint_pos.torch[self.env_id, joint_ids].detach().clone()
        )
        body_ids, _ = asset.find_bodies(config.kinematics.ee_body)
        if len(body_ids) != 1:
            raise SkillError(f"could not resolve {config.kinematics.ee_body!r} on {arm} robot")
        body_id = body_ids[0]
        body_position = _env_position(asset.data.body_pos_w[self.env_id, body_id], origin)
        body_orientation = tuple(
            float(value)
            for value in _tensor(asset.data.body_quat_w[self.env_id, body_id]).detach().cpu()
        )
        body_pose = Pose(body_position, normalize_quaternion_xyzw(body_orientation))
        tcp_pose = compose_pose(body_pose, self._tcp_from_ee)
        return RobotState(joints, tcp_pose)

    def grasp_candidates(self, object_name: str, arm: Arm) -> tuple[GraspCandidate, ...]:
        if object_name not in self.task.assets:
            raise SkillError(f"unknown task object {object_name!r}")
        approach_distance = float(
            self._grasp_data.tabletop_filter.get("approach_distance_m", 0.1)
        )
        return tuple(
            GraspCandidate(
                tcp_pose_object=Pose(
                    grasp.position_object_m,
                    grasp.orientation_object_xyzw,
                ),
                approach_axis_tcp=grasp.approach_axis_tcp,
                approach_distance_m=approach_distance,
                score=float(grasp.score),
            )
            for grasp in self._grasp_data.grasps
        )

    def measure_grasp(self, object_name: str, arm: Arm) -> GraspState:
        snapshot = self.snapshot()
        object_pose = snapshot.object(object_name).pose_env
        tcp_pose = snapshot.robot(arm).tcp_pose_env
        config = self.robot_configs[arm]
        asset = self.env.scene[f"{arm}_robot"]
        gripper_ids, _ = asset.find_joints(
            list(config.gripper.command_joint_names),
            preserve_order=True,
        )
        command_joint = float(asset.data.joint_pos.torch[self.env_id, gripper_ids[0]].item())
        open_position = config.gripper.open_positions[config.gripper.command_joint_names[0]]
        aperture = config.gripper.max_aperture_m * command_joint / open_position
        return GraspState(
            object_name,
            arm,
            float(max(config.gripper.min_aperture_m, min(config.gripper.max_aperture_m, aperture))),
            object_pose,
            tcp_pose,
            relative_pose(object_pose, tcp_pose),
        )


class PinocchioMotionPlanner:
    """Numerical, collision-aware-enough joint planner for one mounted Piper."""

    def __init__(
        self,
        env: Any,
        arm: Arm,
        robot_config: RobotConfig,
        mount_position_env_m: tuple[float, float, float],
        mount_orientation_env_xyzw: tuple[float, float, float, float],
        tcp_from_ee: Pose,
        *,
        env_id: int = 0,
        waypoints: int = 24,
        max_iterations: int = 80,
        ik_restarts: int = 8,
    ) -> None:
        self.env = env
        self._arm = arm
        self.config = robot_config
        self.mount_position = mount_position_env_m
        self.mount_orientation = mount_orientation_env_xyzw
        self.tcp_from_ee = tcp_from_ee
        self.env_id = env_id
        self.waypoints = max(2, waypoints)
        self.max_iterations = max_iterations
        self.ik_restarts = max(1, ik_restarts)
        urdf_path = robot_config.urdf_path
        if urdf_path is None:
            raise ValueError("PinocchioMotionPlanner requires robot.urdf_path")
        self._model = pin.buildModelFromUrdf(str(urdf_path))
        self._data = self._model.createData()
        # ``base_to_tcp`` in the grasp catalog is authored from the configured
        # robot base link (Piper ``link6``) to the benchmark TCP.  Starting FK
        # at the already-offset ``gripper_center`` frame would apply that
        # transform twice and makes otherwise reachable grasps fail IK.
        self._tcp_frame_id = self._model.getFrameId(robot_config.kinematics.ee_body)
        self._limits_low = torch.tensor(self._model.lowerPositionLimit[:6], dtype=torch.float32)
        self._limits_high = torch.tensor(self._model.upperPositionLimit[:6], dtype=torch.float32)

    @property
    def arm(self) -> Arm:
        return self._arm

    def plan_joints(
        self,
        start: JointState,
        target_joint_state: JointState,
        scene: PlanningScene,
    ) -> JointTrajectory:
        target = target_joint_state.positions.to(device=start.positions.device, dtype=start.positions.dtype)
        if target.shape != start.positions.shape:
            raise PlanningError(self.arm, "joints", "joint dimension mismatch")
        positions = self._plan_joint_path(start.positions, target, scene)
        return JointTrajectory(positions)

    def plan_pose(
        self,
        start: JointState,
        target_tcp_pose_env: Pose,
        scene: PlanningScene,
    ) -> JointTrajectory:
        q0 = start.positions.detach().cpu().double().numpy()
        q = self._solve_ik(q0, target_tcp_pose_env)
        if q is None:
            raise PlanningError(self.arm, "ik", "target pose did not converge")
        target = start.positions.new_tensor(q)
        positions = self._plan_joint_path(start.positions, target, scene)
        return JointTrajectory(positions)

    def plan_upright(
        self,
        start: JointState,
        target_tcp_pose_env: Pose,
        tcp_pose_object: Pose,
        scene: PlanningScene,
    ) -> JointTrajectory:
        """Plan a placement pose while leaving the object's yaw unconstrained.

        A fixed TCP quaternion can be unreachable at the low tabletop height
        even though the cup can be placed upright.  The grasp relation gives
        the object's up axis in TCP coordinates; constraining that axis and
        the TCP position preserves the task invariant while freeing wrist yaw.
        """

        import numpy as np

        grasp_rotation = pin.Quaternion(
            tcp_pose_object.orientation_xyzw[3],
            tcp_pose_object.orientation_xyzw[0],
            tcp_pose_object.orientation_xyzw[1],
            tcp_pose_object.orientation_xyzw[2],
        ).toRotationMatrix()
        object_up_in_tcp = grasp_rotation.T @ np.asarray((0.0, 0.0, 1.0))
        q0 = start.positions.detach().cpu().double().numpy()
        q = self._solve_upright_ik(
            q0,
            np.asarray(target_tcp_pose_env.position_m, dtype=float),
            object_up_in_tcp,
        )
        if q is None:
            raise PlanningError(self.arm, "ik", "upright target pose did not converge")
        target = start.positions.new_tensor(q)
        positions = self._plan_joint_path(start.positions, target, scene)
        return JointTrajectory(positions)

    def _plan_joint_path(
        self,
        start: torch.Tensor,
        target: torch.Tensor,
        scene: PlanningScene,
    ) -> torch.Tensor:
        """Interpolate directly, then retry through a high tabletop transit.

        The Piper arms often need to pass over cups before descending to a
        grasp.  A single joint-space interpolation cuts through those cups;
        the fallback keeps the elbow folded and raises the TCP above the
        conservative obstacle clearance used by ``_validate_workspace``.
        """

        direct = self._interpolate(start, target, self.waypoints)
        try:
            self._validate_workspace(direct, scene)
            return direct
        except PlanningError as direct_error:
            lower = self._limits_low.to(device=start.device, dtype=start.dtype)
            upper = self._limits_high.to(device=start.device, dtype=start.dtype)
            safe_candidates = []
            for elbow_pitch, elbow_roll in ((0.6, -0.6), (1.0, -1.5), (2.0, -1.5)):
                safe = start.clone()
                safe[0] = target[0]
                safe[1] = elbow_pitch
                safe[2] = elbow_roll
                safe[3:] = start[3:]
                safe_candidates.append(torch.maximum(lower, torch.minimum(upper, safe)))
            for safe in safe_candidates:
                first = self._interpolate(start, safe, max(2, self.waypoints // 2))
                second = self._interpolate(safe, target, max(2, self.waypoints // 2))
                routed = torch.cat((first[:-1], second), dim=0)
                try:
                    self._validate_workspace(routed, scene)
                    return routed
                except PlanningError:
                    continue
            raise direct_error

    @staticmethod
    def _interpolate(
        start: torch.Tensor,
        target: torch.Tensor,
        steps: int,
    ) -> torch.Tensor:
        fraction = torch.linspace(
            0.0,
            1.0,
            steps,
            device=start.device,
            dtype=start.dtype,
        ).unsqueeze(1)
        return start.unsqueeze(0) + fraction * (target - start).unsqueeze(0)

    def _fk_env(self, q_arm: Any) -> tuple[Any, Any]:
        import numpy as np

        # Pinocchio's Python bindings require an Eigen-compatible array.  A
        # plain list happened to work with older bindings but raises a
        # signature error with the version used by Isaac Lab 3.
        q = np.zeros(self._model.nq, dtype=float)
        q[:6] = np.asarray(q_arm, dtype=float)
        pin.forwardKinematics(self._model, self._data, q)
        pin.updateFramePlacements(self._model, self._data)
        frame = self._data.oMf[self._tcp_frame_id]
        tcp = frame * pin.SE3(
            pin.Quaternion(
                self.tcp_from_ee.orientation_xyzw[3],
                self.tcp_from_ee.orientation_xyzw[0],
                self.tcp_from_ee.orientation_xyzw[1],
                self.tcp_from_ee.orientation_xyzw[2],
            ).toRotationMatrix(),
            self._np_vector(self.tcp_from_ee.position_m),
        )
        mount_rotation = pin.Quaternion(
            self.mount_orientation[3],
            self.mount_orientation[0],
            self.mount_orientation[1],
            self.mount_orientation[2],
        ).toRotationMatrix()
        return (
            self.mount_position_np + mount_rotation @ tcp.translation,
            mount_rotation @ tcp.rotation,
        )

    @staticmethod
    def _np_vector(values: tuple[float, float, float]) -> Any:
        import numpy as np

        return np.asarray(values, dtype=float)

    @property
    def mount_position_np(self) -> Any:
        return self._np_vector(self.mount_position)

    def _solve_ik(self, q: Any, target: Pose) -> Any | None:
        import numpy as np

        target_rotation = pin.Quaternion(
            target.orientation_xyzw[3],
            target.orientation_xyzw[0],
            target.orientation_xyzw[1],
            target.orientation_xyzw[2],
        ).toRotationMatrix()
        target_position = np.asarray(target.position_m, dtype=float)
        q_initial = np.asarray(q, dtype=float)
        if q_initial.shape != (6,):
            return None

        # A zero Piper pose is close to a kinematic singularity for tabletop
        # targets.  Seed the elbow with a few folded configurations and aim the
        # shoulder toward the target in the mounted base frame.  This keeps IK
        # deterministic while covering the two common elbow branches.
        mount_rotation = pin.Quaternion(
            self.mount_orientation[3],
            self.mount_orientation[0],
            self.mount_orientation[1],
            self.mount_orientation[2],
        ).toRotationMatrix()
        target_local = mount_rotation.T @ (
            target_position - self.mount_position_np
        )
        shoulder_yaw = math.atan2(float(target_local[1]), float(target_local[0]))
        starts = [q_initial]
        for elbow_pitch, elbow_roll in (
            (0.5, -0.5),
            (1.0, -1.5),
            (1.5, -0.5),
            (2.0, -1.5),
        ):
            starts.append(
                np.asarray(
                    (shoulder_yaw, elbow_pitch, elbow_roll, 0.0, 0.0, 0.0),
                    dtype=float,
                )
            )
        starts.extend(
            np.asarray(
                (shoulder_yaw + offset, 1.0, -1.5, 0.0, 0.0, 0.0),
                dtype=float,
            )
            for offset in (-0.7, 0.7)
        )

        lower = self._limits_low.numpy()
        upper = self._limits_high.numpy()
        for start in starts[: self.ik_restarts]:
            q_candidate = np.clip(start, lower, upper)
            for _ in range(self.max_iterations):
                position, rotation = self._fk_env(q_candidate)
                position_error = target_position - position
                rotation_error = pin.log3(rotation.T @ target_rotation)
                error = np.concatenate((position_error, rotation_error))
                if (
                    # Pre-grasp and contact poses may sit a few millimetres
                    # inside the mesh-derived reach boundary.  Keep this
                    # tolerance modest; placement uses the stricter upright
                    # solver below.
                    np.linalg.norm(position_error) < 0.01
                    and np.linalg.norm(rotation_error) < 0.05
                ):
                    return np.asarray(q_candidate, dtype=float)
                jacobian = np.zeros((6, 6), dtype=float)
                for index in range(6):
                    q_perturbed = q_candidate.copy()
                    q_perturbed[index] += 1.0e-5
                    p_next, r_next = self._fk_env(q_perturbed)
                    jacobian[:3, index] = (p_next - position) / 1.0e-5
                    jacobian[3:, index] = (
                        pin.log3(rotation.T @ r_next) / 1.0e-5
                    )
                damped = jacobian.T @ jacobian + 1.0e-4 * np.eye(6)
                try:
                    delta = np.linalg.solve(damped, jacobian.T @ error)
                except np.linalg.LinAlgError:
                    break
                q_candidate = np.clip(
                    q_candidate + 0.65 * delta,
                    lower,
                    upper,
                )
                if not np.isfinite(q_candidate).all():
                    break
        return None

    def _solve_upright_ik(
        self,
        q: Any,
        target_position: Any,
        object_up_in_tcp: Any,
    ) -> Any | None:
        """Solve TCP position plus the two tilt components of object up."""

        import numpy as np

        target_position = np.asarray(target_position, dtype=float)
        object_up_in_tcp = np.asarray(object_up_in_tcp, dtype=float)
        q_initial = np.asarray(q, dtype=float)
        if q_initial.shape != (6,):
            return None
        lower = self._limits_low.numpy()
        upper = self._limits_high.numpy()
        for start in self._ik_starts(target_position, q_initial):
            q_candidate = np.clip(start, lower, upper)
            for _ in range(self.max_iterations):
                position, rotation = self._fk_env(q_candidate)
                object_up_env = rotation @ object_up_in_tcp
                position_error = target_position - position
                tilt_error = -object_up_env[:2]
                error = np.concatenate((position_error, tilt_error))
                if (
                    np.linalg.norm(position_error) < 0.003
                    and np.linalg.norm(tilt_error) < math.sin(0.12)
                    and object_up_env[2] > math.cos(0.12)
                ):
                    return np.asarray(q_candidate, dtype=float)
                jacobian = np.zeros((5, 6), dtype=float)
                for index in range(6):
                    q_perturbed = q_candidate.copy()
                    q_perturbed[index] += 1.0e-5
                    p_next, r_next = self._fk_env(q_perturbed)
                    up_next = r_next @ object_up_in_tcp
                    jacobian[:3, index] = (p_next - position) / 1.0e-5
                    jacobian[3:, index] = (up_next[:2] - object_up_env[:2]) / 1.0e-5
                damped = jacobian.T @ jacobian + 1.0e-4 * np.eye(6)
                try:
                    delta = np.linalg.solve(damped, jacobian.T @ error)
                except np.linalg.LinAlgError:
                    break
                q_candidate = np.clip(
                    q_candidate + 0.65 * delta,
                    lower,
                    upper,
                )
                if not np.isfinite(q_candidate).all():
                    break
        return None

    def _ik_starts(self, target_position: Any, q_initial: Any) -> list[Any]:
        """Return deterministic elbow seeds aimed at one target position."""

        import numpy as np

        mount_rotation = pin.Quaternion(
            self.mount_orientation[3],
            self.mount_orientation[0],
            self.mount_orientation[1],
            self.mount_orientation[2],
        ).toRotationMatrix()
        target_local = mount_rotation.T @ (
            np.asarray(target_position, dtype=float) - self.mount_position_np
        )
        shoulder_yaw = math.atan2(float(target_local[1]), float(target_local[0]))
        starts = [np.asarray(q_initial, dtype=float)]
        for elbow_pitch, elbow_roll in (
            (0.5, -0.5),
            (1.0, -1.5),
            (1.5, -0.5),
            (2.0, -1.5),
        ):
            starts.append(
                np.asarray(
                    (shoulder_yaw, elbow_pitch, elbow_roll, 0.0, 0.0, 0.0),
                    dtype=float,
                )
            )
        starts.extend(
            np.asarray(
                (shoulder_yaw + offset, 1.0, -1.5, 0.0, 0.0, 0.0),
                dtype=float,
            )
            for offset in (-0.7, 0.7)
        )
        return starts[: self.ik_restarts]

    def _validate_workspace(self, positions: torch.Tensor, scene: PlanningScene) -> None:
        """Reject obvious tabletop/inter-object collisions before execution."""

        if not torch.isfinite(positions).all().item():
            raise PlanningError(self.arm, "collision", "trajectory contains non-finite joints")
        # The TCP must stay above the table.  Object collision geometry is kept
        # in the PlanningScene and checked with a conservative XY clearance.
        for row in positions.detach().cpu().double().numpy():
            point, _ = self._fk_env(row)
            if point[2] < scene.table.pose_env.position_m[2] + scene.table.size_m[2] / 2.0 - 0.01:
                raise PlanningError(self.arm, "collision", "TCP trajectory intersects the table")
            for obstacle in scene.objects:
                radius = math.hypot(obstacle.size_m[0], obstacle.size_m[1]) / 2.0 + 0.035
                distance_xy = math.hypot(point[0] - obstacle.pose_env.position_m[0], point[1] - obstacle.pose_env.position_m[1])
                vertical = abs(point[2] - obstacle.pose_env.position_m[2]) <= obstacle.size_m[2] / 2.0 + 0.09
                if distance_xy < radius and vertical:
                    raise PlanningError(
                        self.arm,
                        "collision",
                        f"TCP trajectory intersects {obstacle.name}",
                    )


__all__ = ["IsaacLabSkillContext", "PinocchioMotionPlanner"]
