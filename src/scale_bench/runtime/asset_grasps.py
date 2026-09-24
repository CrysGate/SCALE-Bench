"""Adapt GraspDataGen asset annotations to manipulation candidates."""

from pathlib import Path

from scale_bench.config.loader import load_config
from scale_bench.config.models.grasp import AssetGraspsConfig
from scale_bench.config.models.robot import RobotConfig
from scale_bench.skills.context import GraspCandidate
from scale_bench.skills.geometry import conjugate_quaternion_xyzw, rotate_vector_xyzw
from scale_bench.skills.models import Pose


def load_asset_grasps(
    object_usd_path: Path,
    robot_config: RobotConfig,
) -> tuple[GraspCandidate, ...]:
    """Load the asset's grasps-<robot name>.yaml, retaining candidate order."""

    path = object_usd_path.with_name(f"grasps-{robot_config.name}.yaml")
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
