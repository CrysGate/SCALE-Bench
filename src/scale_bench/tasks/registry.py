"""One loading boundary for preview, collection, evaluation, and replay."""

from pathlib import Path

from scale_bench.config.loader import load_config

from .common.fixed_target import PlacementTaskConfig
from .common.rigid_object import ObjectSetConfig, RigidObjects
from .common.task import Task
from .largest_pick_and_place.task import LargestPickAndPlaceTask
from .single_object_pick_and_place.task import SingleObjectPickAndPlaceTask
from .sort_dolls_by_size.task import SortDollsBySizeTask


TASKS = {
    "single_object_pick_and_place": (
        PlacementTaskConfig, SingleObjectPickAndPlaceTask,
    ),
    "largest_pick_and_place": (
        PlacementTaskConfig, LargestPickAndPlaceTask,
    ),
    "sort_dolls_by_size": (
        PlacementTaskConfig, SortDollsBySizeTask,
    ),
}


def load_task(
    task_id: str,
    *,
    project_root: Path,
    asset_root: Path,
    config_path: Path | None = None,
    object_set_path: Path | None = None,
) -> Task:
    """Load one task variant and validate its object collection.

    Omit config_path to use configs/tasks/<task_id>/default.yml. Omit
    object_set_path to use the variant's collection; supply it to swap objects.
    """
    try:
        config_type, task_type = TASKS[task_id]
    except KeyError as error:
        raise ValueError(f"unknown task: {task_id!r}") from error
    config = load_config(
        config_path if config_path is not None
        else project_root / "configs/tasks" / task_id / "default.yml",
        config_type,
    )
    if config.task != task_id:
        raise ValueError(f"config task {config.task!r} does not match {task_id!r}")
    if object_set_path is not None:
        config = config.model_copy(update={"object_set": str(object_set_path.resolve())})
    objects = RigidObjects(load_config(config.object_set, ObjectSetConfig, asset_root=asset_root))
    return task_type(config, objects)
