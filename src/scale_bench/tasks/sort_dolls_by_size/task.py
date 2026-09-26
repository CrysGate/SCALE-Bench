"""Order an object collection by height while retaining the public task ID."""

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
        raise ValueError("size ordering requires at least two objects")
    heights_m = {name: metadata.size[2] for name, metadata in objects.metadata.items()}
    if len(set(heights_m.values())) != len(heights_m):
        raise ValueError("size ordering requires distinct object heights")
    target_positions_env_y_m = tuple(p[1] for p in config.target_positions_env_xy_m)
    if any(
        first >= second
        for first, second in zip(target_positions_env_y_m, target_positions_env_y_m[1:])
    ):
        raise ValueError("sorting destinations must be ordered in the positive Y direction")
    return make_placement_task(
        instruction=(
            f"Arrange the {len(objects.assets)} {objects.config.plural} in the target slots, "
            "ordered from smallest to largest in the positive Y direction."
        ),
        config=config,
        objects=objects,
        object_order=tuple(sorted(heights_m, key=heights_m.__getitem__)),
    )
