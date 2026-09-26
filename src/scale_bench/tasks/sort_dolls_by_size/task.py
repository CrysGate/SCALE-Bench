"""Order an object collection by height while retaining the public task ID."""

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


class SortDollsBySizeTask(Task):
    """Place objects in slots ordered by increasing height."""

    def __init__(self, config: PlacementTaskConfig, objects: RigidObjects) -> None:
        heights_m = {name: metadata.size[2] for name, metadata in objects.metadata.items()}
        target_positions_env_y_m = tuple(p[1] for p in config.target_positions_env_xy_m)
        super().__init__(
            task_id=config.task,
            instruction=config.instruction,
            config=config,
            objects=objects,
            goal=make_placement_goal(
                config=config,
                objects=objects,
                object_order=tuple(sorted(heights_m, key=heights_m.__getitem__)),
            ),
        )

    def expert(self, scene: SceneConfig, layout: TaskLayout) -> Iterator[SkillRequest]:
        target_placements_env = self.goal.target_placements(PlacementContext.from_scene_config(scene))
        for object_name in self.goal.object_names:
            yield PickAndPlace(
                object_name=object_name,
                arm="auto",
                target_object_pose_env=Pose(
                    position_m=target_placements_env[object_name].position_m,
                    orientation_xyzw=layout.assets[object_name].orientation_xyzw,
                ),
            )
