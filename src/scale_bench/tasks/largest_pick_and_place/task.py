"""Select the unique tallest candidate and bind it to a placement goal."""

from collections.abc import Iterator

from scale_bench.config.models.scene import SceneConfig
from scale_bench.skills.models import PickAndPlace, Pose, SkillRequest
from scale_bench.tasks.common.fixed_target import (
    PlacementTaskConfig,
    make_placement_goal,
)
from scale_bench.tasks.common.layout import TaskLayout
from scale_bench.tasks.common.placement import PlacementContext
from scale_bench.tasks.common.rigid_object import RigidObjects
from scale_bench.tasks.common.task import Task


class LargestPickAndPlaceTask(Task):
    """Select the tallest object and place it upright at its destination."""

    def __init__(self, config: PlacementTaskConfig, objects: RigidObjects) -> None:
        heights_m = {name: metadata.size[2] for name, metadata in objects.metadata.items()}
        maximum_height_m = max(heights_m.values())
        target_names = tuple(
            name for name, height_m in heights_m.items() if height_m == maximum_height_m
        )
        super().__init__(
            task_id=config.task,
            instruction=config.instruction,
            config=config,
            objects=objects,
            goal=make_placement_goal(
                config=config,
                objects=objects,
                object_order=target_names,
            ),
        )

    def expert(self, scene: SceneConfig, layout: TaskLayout) -> Iterator[SkillRequest]:
        object_name, = self.goal.object_names
        target_placements_env = self.goal.target_placements(PlacementContext.from_scene_config(scene))
        yield PickAndPlace(
            object_name=object_name,
            arm="auto",
            target_object_pose_env=Pose(
                position_m=target_placements_env[object_name].position_m,
                orientation_xyzw=layout.assets[object_name].orientation_xyzw,
            ),
        )
