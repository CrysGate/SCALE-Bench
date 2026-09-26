"""Reference programs for supported goals; model evaluation does not use them."""

from collections.abc import Iterator

from scale_bench.skills.models import PickAndPlace, Pose, SkillRequest

from .common.fixed_target import FixedPlacementGoal
from .common.layout import TaskLayout
from .common.placement import PlacementContext


def pick_and_place_expert(
    goal: FixedPlacementGoal, context: PlacementContext, source_layout: TaskLayout,
) -> Iterator[SkillRequest]:
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
