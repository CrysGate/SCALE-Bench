"""Adapt GraspDataGen asset annotations to manipulation candidates."""

import math
from pathlib import Path

import yaml

from scale_bench.config.loader import load_config
from scale_bench.config.models.grasp import AssetGraspsConfig
from scale_bench.config.models.robot import RobotConfig
from scale_bench.skills.context import GraspCandidate
from scale_bench.skills.geometry import conjugate_quaternion_xyzw, rotate_vector_xyzw
from scale_bench.skills.models import Pose


def load_asset_grasps(
    object_usd_path: Path,
    robot_config: RobotConfig,
    *,
    grasp_file: Path | None = None,
) -> tuple[GraspCandidate, ...]:
    """Load candidates for one robot, retaining their order in grasps.yaml."""

    path = grasp_file or object_usd_path.with_name("grasps.yaml")
    if grasp_file is not None:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and "grasps" in document:
            return _load_successful_grasps(path, object_usd_path, robot_config)
    grasps = load_config(path, AssetGraspsConfig)
    if grasps.tcp != robot_config.kinematics.tcp:
        raise ValueError(f"grasp TCP does not match robot {robot_config.name!r}: {path}")
    candidates: list[GraspCandidate] = []
    for candidate in grasps.candidates:
        if candidate.robot != robot_config.name:
            continue
        if set(candidate.closed_joint_positions_m) != set(robot_config.gripper.joint_names):
            raise ValueError(f"grasp joints do not match robot {robot_config.name!r}: {path}")
        tcp_pose_object = Pose(
            candidate.pose_object_tcp_xyz_xyzw[:3],
            candidate.pose_object_tcp_xyz_xyzw[3:],
        )
        approach_axis_tcp = rotate_vector_xyzw(
            conjugate_quaternion_xyzw(tcp_pose_object.orientation_xyzw),
            candidate.approach_axis_object,
        )
        candidates.append(
            GraspCandidate(
                tcp_pose_object=tcp_pose_object,
                approach_axis_tcp=approach_axis_tcp,
                approach_distance_m=grasps.approach_distance_m,
                # Compact exports have no quality scores; equal scores preserve order.
                score=0.0,
                candidate_id=candidate.candidate_id,
                gripper_joint_positions=dict(candidate.closed_joint_positions_m),
            )
        )
    if not candidates:
        raise ValueError(f"no grasp candidates for robot {robot_config.name!r}: {path}")
    return tuple(candidates)


def _load_successful_grasps(
    path: Path, object_usd_path: Path, robot_config: RobotConfig,
) -> tuple[GraspCandidate, ...]:
    """Adapt the original validated-grasp export without rewriting asset files."""
    from grasp_data_gen.results import load_grasp_file, resolve_asset_path
    from scale_bench.skills.geometry import (
        compose_pose, inverse_pose, normalize_quaternion_xyzw,
    )

    data = load_grasp_file(path)
    if resolve_asset_path(data.object_usd, path, "object USD") != object_usd_path.resolve():
        raise ValueError(f"grasp object does not match task asset: {path}")
    if resolve_asset_path(data.robot_usd, path, "robot USD") != Path(robot_config.usd_path).resolve():
        raise ValueError(f"grasp robot does not match robot profile: {path}")
    tcp = robot_config.kinematics.tcp
    definition = data.tcp_definition
    if definition.parent_frame != tcp.parent_frame:
        raise ValueError(f"grasp TCP parent frame does not match robot profile: {path}")
    # The merged Piper profile moved the TCP by 2 cm. Express the same physical
    # gripper pose in the new TCP frame, rather than shifting the actual grasp.
    old_tcp_pose_parent = Pose(
        definition.offset_in_parent_m,
        normalize_quaternion_xyzw(definition.tcp_orientation_parent_xyzw),
    )
    new_tcp_pose_old = compose_pose(
        inverse_pose(old_tcp_pose_parent), Pose(tcp.position_m, tcp.orientation_xyzw),
    )
    approach_distance = float(data.tabletop_filter.get("approach_distance_m", 0.1))
    if not math.isfinite(approach_distance) or approach_distance <= 0:
        raise ValueError(f"grasp approach distance must be positive: {path}")
    candidates = []
    for grasp in data.grasps:
        positions = grasp.evaluation.joint_positions
        if set(positions) != set(robot_config.gripper.joint_names):
            raise ValueError(f"grasp joints do not match robot profile: {path}")
        candidates.append(GraspCandidate(
            tcp_pose_object=compose_pose(
                Pose(grasp.position_object_m,
                     normalize_quaternion_xyzw(grasp.orientation_object_xyzw)),
                new_tcp_pose_old,
            ),
            approach_axis_tcp=rotate_vector_xyzw(
                conjugate_quaternion_xyzw(new_tcp_pose_old.orientation_xyzw),
                grasp.approach_axis_tcp,
            ),
            approach_distance_m=approach_distance,
            score=float(grasp.score),
            candidate_id=grasp.candidate_id,
            gripper_joint_positions=dict(positions),
        ))
    if not candidates:
        raise ValueError(f"no successful grasp candidates: {path}")
    return tuple(candidates)
