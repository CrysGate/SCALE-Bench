"""Reference programs for supported goals; model evaluation does not use them."""

from collections.abc import Iterator

from scale_bench.skills.models import PickAndPlace, Pose, SkillRequest

from .common.fixed_target import FixedPlacementGoal
from .common.layout import TaskLayout
from .common.placement import PlacementContext
from .common.task import Task


def placement_goal(task: Task) -> FixedPlacementGoal:
    """Placement-only diagnostics and experts require a placement goal."""
    if not isinstance(task.goal, FixedPlacementGoal):
        raise ValueError(f"{task.task_id} has no fixed-placement expert")
    return task.goal


def pick_and_place_expert(
    task: Task, context: PlacementContext, source_layout: TaskLayout,
) -> Iterator[SkillRequest]:
    task.validate_asset_layout(source_layout)
    goal = placement_goal(task)
    target_placements_env = goal.target_placements(context)
    for object_name in goal.object_names:
        yield PickAndPlace(
            object_name=object_name,
            arm="auto",
            target_object_pose_env=Pose(
                position_m=target_placements_env[object_name].position_m,
                orientation_xyzw=source_layout.assets[object_name].orientation_xyzw,
            ),
        )
