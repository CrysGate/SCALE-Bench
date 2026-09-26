"""Translate task observation sources into Isaac Lab observation terms."""

from isaaclab.managers import ObservationTermCfg, SceneEntityCfg

from scale_bench.isaaclab.mdp.observations import (
    fixed_positions, rigid_object_root_pos, rigid_object_root_quat,
)
from scale_bench.tasks.common.evaluation import FixedPositions, ObjectOrientations, ObjectPositions
from scale_bench.tasks.common.placement import PlacementContext
from scale_bench.tasks.common.task import Task


def build_evaluator_terms(task: Task, context: PlacementContext) -> dict[str, ObservationTermCfg]:
    terms = {}
    for name, source in task.goal.observation_sources(context).items():
        match source:
            case ObjectPositions(object_names):
                term = ObservationTermCfg(
                    func=rigid_object_root_pos,
                    params={"asset_cfgs": tuple(SceneEntityCfg(name) for name in object_names)},
                )
            case ObjectOrientations(object_names):
                term = ObservationTermCfg(
                    func=rigid_object_root_quat,
                    params={"asset_cfgs": tuple(SceneEntityCfg(name) for name in object_names)},
                )
            case FixedPositions(positions_env_m):
                term = ObservationTermCfg(
                    func=fixed_positions, params={"positions_m": positions_env_m},
                )
            case _:
                raise TypeError(f"unsupported evaluator observation source: {source!r}")
        terms[name] = term
    return terms
