"""Pure construction of collision scenes for manipulation primitives."""

from .context import EmptyTool, HeldObject, PlanningScene, SceneSnapshot, ToolState
from .models import Arm, Pose


def _scene(
    snapshot: SceneSnapshot, arm: Arm, excluded_objects: tuple[str, ...], tool: ToolState,
    *, check_finger_collision: bool,
) -> PlanningScene:
    other_arm: Arm = "right" if arm == "left" else "left"
    return PlanningScene(
        table=snapshot.table,
        camera_stand=snapshot.camera_stand,
        objects=tuple(item for item in snapshot.objects if item.name not in excluded_objects),
        other_arm=other_arm,
        other_robot=snapshot.robot(other_arm),
        tool=tool,
        gripper_joint_positions=snapshot.robot(arm).gripper_joint_positions,
        check_finger_collision=check_finger_collision,
    )


def world_scene(snapshot: SceneSnapshot, arm: Arm) -> PlanningScene:
    """Empty tool; all objects, including actually released objects, collide."""
    return _scene(snapshot, arm, (), EmptyTool(), check_finger_collision=True)


def held_object_scene(
    snapshot: SceneSnapshot, arm: Arm, object_name: str, tcp_pose_object: Pose,
) -> PlanningScene:
    return _scene(
        snapshot, arm, (object_name,), HeldObject(snapshot.object(object_name), tcp_pose_object),
        check_finger_collision=True,
    )


def contact_scene(
    snapshot: SceneSnapshot, arm: Arm, object_name: str, *, check_finger_collision: bool,
) -> PlanningScene:
    """Permit contact with the manipulated object; retain every other obstacle.

    The held body is omitted during the final support approach, since intentional
    object/support contact is not a collision-free motion. Grasp approach and
    retreat disable finger checks; placement and vertical recovery retain them.
    """
    return _scene(
        snapshot, arm, (object_name,), EmptyTool(), check_finger_collision=check_finger_collision,
    )
