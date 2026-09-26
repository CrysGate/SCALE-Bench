"""Select the unique tallest candidate and bind it to a placement goal."""

from scale_bench.tasks.common.fixed_target import (
    HeightPlacementTaskConfig,
    make_placement_task,
)
from scale_bench.tasks.common.rigid_object import RigidObjects
from scale_bench.tasks.common.task import Task


def build_task(
    config: HeightPlacementTaskConfig,
    objects: RigidObjects,
) -> Task:
    if len(objects.assets) < 2:
        raise ValueError("largest-object selection requires at least two candidates")
    heights_m = {name: metadata.size[2] for name, metadata in objects.metadata.items()}
    maximum_height_m = max(heights_m.values())
    target_names = tuple(
        name for name, height_m in heights_m.items() if height_m == maximum_height_m
    )
    if len(target_names) != 1:
        raise ValueError("largest-object selection requires a unique tallest candidate")
    return make_placement_task(
        config=config,
        objects=objects,
        object_order=target_names,
    )
