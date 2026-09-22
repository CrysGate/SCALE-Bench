"""Static robot and scene geometry read offline from USD and URDF assets.

Only ``pxr`` and the standard library are imported here, so callers can
resolve collision bounds and mounted-camera offsets without launching Kit.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

from pxr import Gf, Usd, UsdGeom, UsdPhysics

from scale_bench.config.models.robot import RobotConfig
from scale_bench.config.models.scene import SceneConfig
from scale_bench.skills.context import SceneObject
from scale_bench.skills.geometry import (
    compose_pose,
    inverse_pose,
    quaternion_xyzw_from_rpy,
    rotate_vector_xyzw,
)
from scale_bench.skills.models import Pose


def camera_position_tcp_m(
    robot_config: RobotConfig,
    ee_body_pose_tcp: Pose,
) -> tuple[float, float, float]:
    """Read the mounted sensor's fixed position for upright grasp filtering."""
    camera = robot_config.camera
    robot_stage = Usd.Stage.Open(robot_config.usd_path)
    robot_prim = robot_stage.GetDefaultPrim()
    camera_mount_prim = robot_stage.GetPrimAtPath(
        robot_prim.GetPath().AppendPath(camera.parent_prim_path)
    )
    ee_body_prim = robot_prim.GetChild(robot_config.kinematics.ee_body)
    camera_offset_tcp_m = rotate_vector_xyzw(
        ee_body_pose_tcp.orientation_xyzw,
        tuple(
            UsdGeom.XformCache().ComputeRelativeTransform(
                camera_mount_prim, ee_body_prim
            )[0].Transform(Gf.Vec3d(*camera.position_m))
        ),
    )
    return tuple(
        coordinate_tcp_m + offset_tcp_m
        for coordinate_tcp_m, offset_tcp_m in zip(
            ee_body_pose_tcp.position_m, camera_offset_tcp_m, strict=True
        )
    )


def camera_stand_collision_objects_env(
    scene_config: SceneConfig,
) -> tuple[SceneObject, ...]:
    camera_stand_usd_path = scene_config.camera.stand_usd_path
    camera_stand_stage = Usd.Stage.Open(camera_stand_usd_path)
    if camera_stand_stage is None:
        raise ValueError(f"could not open camera stand USD: {camera_stand_usd_path}")

    camera_stand_prim = camera_stand_stage.GetDefaultPrim()
    if not camera_stand_prim.IsValid():
        raise ValueError(
            f"camera stand USD has no default prim: {camera_stand_usd_path}"
        )

    camera_stand_pose_env = Pose(
        (
            *scene_config.camera.stand_position_xy_m,
            scene_config.table_top_z_m,
        ),
        scene_config.camera.stand_orientation_xyzw,
    )
    bounds_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [
            UsdGeom.Tokens.default_,
            UsdGeom.Tokens.render,
            UsdGeom.Tokens.proxy,
        ],
    )
    collision_objects_env = []
    for collision_prim in camera_stand_stage.Traverse():
        if not collision_prim.HasAPI(UsdPhysics.CollisionAPI):
            continue
        if (
            UsdPhysics.CollisionAPI(collision_prim)
            .GetCollisionEnabledAttr()
            .Get()
            is False
        ):
            continue

        collision_bounds_object_m = bounds_cache.ComputeRelativeBound(
            collision_prim,
            camera_stand_prim,
        ).ComputeAlignedRange()
        if collision_bounds_object_m.IsEmpty():
            continue
        minimum_object_m = collision_bounds_object_m.GetMin()
        maximum_object_m = collision_bounds_object_m.GetMax()
        collision_prim_position_object_m = tuple(
            float((minimum_object_m[axis] + maximum_object_m[axis]) / 2.0)
            for axis in range(3)
        )
        collision_prim_size_m = tuple(
            float(maximum_object_m[axis] - minimum_object_m[axis])
            for axis in range(3)
        )
        collision_prim_pose_env = compose_pose(
            camera_stand_pose_env,
            Pose(
                collision_prim_position_object_m,
                (0.0, 0.0, 0.0, 1.0),
            ),
        )
        collision_objects_env.append(
            SceneObject(
                name=f"camera_stand/{len(collision_objects_env):03d}",
                pose_env=collision_prim_pose_env,
                size_m=collision_prim_size_m,
            )
        )

    if not collision_objects_env:
        raise ValueError(
            "camera stand USD has no enabled collision geometry: "
            f"{camera_stand_usd_path}"
        )
    return tuple(collision_objects_env)


def fixed_urdf_frame_pose(
    urdf_path: str | None,
    source_frame: str,
    target_frame: str,
) -> Pose:
    """Resolve a fixed-frame transform without depending on merged USD links."""

    identity_pose = Pose((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    if source_frame == target_frame:
        return identity_pose
    if urdf_path is None:
        raise ValueError(
            f"cannot resolve {source_frame!r} to {target_frame!r} without a URDF"
        )
    try:
        root = ET.parse(Path(urdf_path)).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"could not parse robot URDF {urdf_path}: {error}") from error

    graph: dict[str, list[tuple[str, Pose]]] = {}
    for joint in root.findall("joint"):
        if joint.get("type") != "fixed":
            continue
        parent_node = joint.find("parent")
        child_node = joint.find("child")
        if parent_node is None or child_node is None:
            raise ValueError("URDF fixed joint is missing parent or child")
        parent = parent_node.get("link")
        child = child_node.get("link")
        if not parent or not child:
            raise ValueError("URDF fixed joint has an empty parent or child")
        origin = joint.find("origin")
        child_position_parent_m = _urdf_vector(origin, "xyz")
        rpy = _urdf_vector(origin, "rpy")
        child_pose_parent = Pose(
            child_position_parent_m,
            quaternion_xyzw_from_rpy(*rpy),
        )
        graph.setdefault(parent, []).append((child, child_pose_parent))
        graph.setdefault(child, []).append((parent, inverse_pose(child_pose_parent)))

    pending = deque([(source_frame, identity_pose)])
    visited = {source_frame}
    while pending:
        frame, frame_pose_source = pending.popleft()
        for neighbor, neighbor_pose_frame in graph.get(frame, ()):
            if neighbor in visited:
                continue
            neighbor_pose_source = compose_pose(frame_pose_source, neighbor_pose_frame)
            if neighbor == target_frame:
                return neighbor_pose_source
            visited.add(neighbor)
            pending.append((neighbor, neighbor_pose_source))
    raise ValueError(
        f"URDF has no fixed-frame path from {source_frame!r} to {target_frame!r}"
    )

def _urdf_vector(
    origin: ET.Element | None,
    attribute: str,
) -> tuple[float, float, float]:
    text = None if origin is None else origin.get(attribute)
    values = (0.0, 0.0, 0.0) if text is None else tuple(map(float, text.split()))
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError(f"URDF origin {attribute} must contain three finite values")
    return values


__all__ = [
    "camera_position_tcp_m",
    "camera_stand_collision_objects_env",
    "fixed_urdf_frame_pose",
]
