"""Bind one object to an upright-placement goal."""

from scale_bench.tasks.common.fixed_target import PlacementTaskConfig, make_placement_task
from scale_bench.tasks.common.rigid_object import RigidObjects
from scale_bench.tasks.common.task import Task


def build_task(
    config: PlacementTaskConfig,
    objects: RigidObjects,
) -> Task:
    if len(objects.assets) != 1:
        raise ValueError("single-object pick-and-place requires exactly one object")
    return make_placement_task(
        config=config,
        objects=objects,
        object_order=tuple(objects.assets),
    )
