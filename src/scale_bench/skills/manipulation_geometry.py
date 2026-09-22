"""Pure grasp and placement geometry; no motion planning or simulator access."""

import math
from typing import cast

from .context import GraspCandidate
from .geometry import (
    compose_pose,
    multiply_quaternions_xyzw,
    normalize_quaternion_xyzw,
    offset_z_env,
    quaternion_xyzw_from_axis_angle,
    quaternion_xyzw_from_rpy,
    rotate_vector_xyzw,
)
from .models import Pose


def raised_tcp_pose_env(tcp_pose_env: Pose, height_m: float) -> Pose:
    return Pose(offset_z_env(tcp_pose_env.position_m, height_m), tcp_pose_env.orientation_xyzw)


def placement_tcp_pose_env(target_object_pose_env: Pose, tcp_pose_object: Pose) -> Pose:
    return compose_pose(target_object_pose_env, tcp_pose_object)


def grasp_geometry_cost(
    candidate: GraspCandidate,
    object_pose_env: Pose,
    base_position_env_m: tuple[float, float, float],
) -> float:
    return tcp_geometry_cost(
        compose_pose(object_pose_env, candidate.tcp_pose_object),
        object_pose_env.position_m, candidate.approach_axis_tcp, base_position_env_m,
    )


def tcp_geometry_cost(
    tcp_pose_env: Pose,
    object_position_env_m: tuple[float, float, float],
    approach_axis_tcp: tuple[float, float, float],
    base_position_env_m: tuple[float, float, float],
) -> float:
    """Prefer transverse finger opening and penalize approach from the far side.

    The two squared penalties have equal weight. Vertical approaches incur no
    approach penalty. With no horizontal base-to-object offset, all costs are
    zero so the existing score and source order decide the ranking.
    """
    base_to_object_displacement_env_m = (
        object_position_env_m[0] - base_position_env_m[0],
        object_position_env_m[1] - base_position_env_m[1],
        0.0,
    )
    horizontal_distance_m = math.hypot(*base_to_object_displacement_env_m)
    if horizontal_distance_m <= 1.0e-9:
        return 0.0
    base_to_object_direction_env = tuple(
        component_m / horizontal_distance_m
        for component_m in base_to_object_displacement_env_m
    )
    gripper_open_axis_env = rotate_vector_xyzw(
        tcp_pose_env.orientation_xyzw, (0.0, 1.0, 0.0)
    )
    approach_axis_env = rotate_vector_xyzw(
        tcp_pose_env.orientation_xyzw, approach_axis_tcp
    )
    open_dot = sum(
        component * direction
        for component, direction in zip(
            gripper_open_axis_env, base_to_object_direction_env, strict=True
        )
    )
    approach_dot = sum(
        component * direction
        for component, direction in zip(
            approach_axis_env, base_to_object_direction_env, strict=True
        )
    )
    return open_dot**2 + min(0.0, approach_dot)**2


def camera_side_up_dot(
    tcp_pose_env: Pose,
    camera_position_tcp_m: tuple[float, float, float],
    approach_axis_tcp: tuple[float, float, float],
) -> float:
    """Measure the camera mounting side, excluding its axial TCP offset."""
    camera_axial_offset_m = sum(
        component_m * axis_component
        for component_m, axis_component in zip(
            camera_position_tcp_m, approach_axis_tcp, strict=True
        )
    )
    camera_side_tcp_m = tuple(
        component_m - camera_axial_offset_m * axis_component
        for component_m, axis_component in zip(
            camera_position_tcp_m, approach_axis_tcp, strict=True
        )
    )
    camera_side_length_m = math.hypot(*camera_side_tcp_m)
    if camera_side_length_m <= 1.0e-9:
        return 1.0
    camera_side_axis_tcp = cast(
        tuple[float, float, float],
        tuple(component_m / camera_side_length_m for component_m in camera_side_tcp_m),
    )
    camera_side_axis_env = rotate_vector_xyzw(
        tcp_pose_env.orientation_xyzw,
        camera_side_axis_tcp,
    )
    return camera_side_axis_env[2]


def parallel_jaw_grasp_poses(
    object_pose_env: Pose,
    candidate: GraspCandidate,
) -> tuple[Pose, Pose]:
    """Return the original grasp and its half-turn equivalent for upright filtering."""

    canonical_tcp_pose_env = compose_pose(
        object_pose_env,
        candidate.tcp_pose_object,
    )
    half_turn_orientation_tcp_xyzw = quaternion_xyzw_from_axis_angle(
        candidate.approach_axis_tcp,
        math.pi,
    )
    alternate_tcp_pose_env = Pose(
        canonical_tcp_pose_env.position_m,
        normalize_quaternion_xyzw(
            multiply_quaternions_xyzw(
                canonical_tcp_pose_env.orientation_xyzw,
                half_turn_orientation_tcp_xyzw,
            )
        ),
    )
    return canonical_tcp_pose_env, alternate_tcp_pose_env


def target_object_orientations_env_xyzw(
    target_object_pose_env: Pose,
    tcp_pose_object: Pose,
    reference_tcp_orientation_env_xyzw: tuple[float, float, float, float],
    approach_axis_tcp: tuple[float, float, float],
    arm_base_position_env_m: tuple[float, float, float],
) -> tuple[tuple[float, float, float, float], ...]:
    """Rank a 5-degree yaw grid and radial alignment by grasp geometry cost."""
    target_tcp_pose_env = compose_pose(
        target_object_pose_env,
        tcp_pose_object,
    )
    target_finger_open_axis_env = rotate_vector_xyzw(
        target_tcp_pose_env.orientation_xyzw,
        (0.0, 1.0, 0.0),
    )
    reference_finger_open_axis_env = rotate_vector_xyzw(
        reference_tcp_orientation_env_xyzw,
        (0.0, 1.0, 0.0),
    )
    alignment_yaw_env_rad = math.atan2(
        reference_finger_open_axis_env[1],
        reference_finger_open_axis_env[0],
    ) - math.atan2(
        target_finger_open_axis_env[1],
        target_finger_open_axis_env[0],
    )
    aligned_object_orientation_env_xyzw = normalize_quaternion_xyzw(
        multiply_quaternions_xyzw(
            quaternion_xyzw_from_rpy(0.0, 0.0, alignment_yaw_env_rad),
            target_object_pose_env.orientation_xyzw,
        )
    )
    yaw_object_orientations_env_xyzw = tuple(
        normalize_quaternion_xyzw(
            multiply_quaternions_xyzw(
                quaternion_xyzw_from_rpy(0.0, 0.0, math.radians(yaw_offset_env_deg)),
                aligned_object_orientation_env_xyzw,
            )
        )
        for yaw_offset_env_deg in range(-180, 180, 5)
    )
    target_approach_axis_env = rotate_vector_xyzw(
        target_tcp_pose_env.orientation_xyzw, approach_axis_tcp
    )
    approach_xy_norm = math.hypot(
        target_approach_axis_env[0],
        target_approach_axis_env[1],
    )
    if approach_xy_norm >= 1e-5:
        radial_yaw_env_rad = math.atan2(
            target_object_pose_env.position_m[1] - arm_base_position_env_m[1],
            target_object_pose_env.position_m[0] - arm_base_position_env_m[0],
        ) - math.atan2(target_approach_axis_env[1], target_approach_axis_env[0])
        radial_object_orientation_env_xyzw = normalize_quaternion_xyzw(
            multiply_quaternions_xyzw(
                quaternion_xyzw_from_rpy(0.0, 0.0, radial_yaw_env_rad),
                target_object_pose_env.orientation_xyzw,
            )
        )
        yaw_object_orientations_env_xyzw = (
            radial_object_orientation_env_xyzw, *yaw_object_orientations_env_xyzw,
        )
    return tuple(sorted(
        yaw_object_orientations_env_xyzw,
        key=lambda object_orientation_env_xyzw: tcp_geometry_cost(
            placement_tcp_pose_env(
                Pose(target_object_pose_env.position_m, object_orientation_env_xyzw),
                tcp_pose_object,
            ),
            target_object_pose_env.position_m, approach_axis_tcp, arm_base_position_env_m,
        ),
    ))
