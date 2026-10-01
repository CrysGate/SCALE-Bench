"""Load object-local grasp candidates for skill consumers."""

from pathlib import Path

from scale_bench.config.models.robot import RobotConfig
from scale_bench.runtime.asset_grasps import load_asset_grasps
from scale_bench.skills.context import GraspCandidate
from scale_bench.skills.errors import SkillError
from scale_bench.skills.models import Arm
from scale_bench.tasks.common.task import Task


class IsaacLabGraspCandidates:
    """Resolve object-frame candidates from each object's asset directory."""

    def __init__(
        self,
        task: Task,
        robot_config: RobotConfig,
    ) -> None:
        self._task = task
        self._robot_config = robot_config
        self._asset_grasps: dict[str, tuple[GraspCandidate, ...]] = {}

    def candidates(
        self, object_name: str, arm: Arm,
    ) -> tuple[GraspCandidate, ...]:
        if object_name not in self._asset_grasps:
            self._asset_grasps[object_name] = load_asset_grasps(
                Path(self._task.assets[object_name].usd_path),
                self._robot_config,
            )
        candidates = self._asset_grasps[object_name]
        if not candidates:
            raise SkillError(
                f"no valid {object_name!r} grasp for {arm} arm "
                f"(asset candidates={len(candidates)})"
            )
        return tuple(sorted(candidates, key=lambda item: item.score, reverse=True))


__all__ = ["IsaacLabGraspCandidates"]
