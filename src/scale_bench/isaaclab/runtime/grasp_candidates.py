"""Candidate source selection and task eligibility shared by skill consumers."""

from collections.abc import Mapping
from functools import partial
from pathlib import Path

from scale_bench.config.models.robot import RobotConfig
from scale_bench.config.models.scene import SceneConfig
from scale_bench.runtime.asset_grasps import load_asset_grasps
from scale_bench.skills.context import GraspCandidate
from scale_bench.skills.errors import SkillError
from scale_bench.skills.models import Arm, Pose
from scale_bench.tasks.common.rigid_object import RigidObjectTask

from .anygrasp_diagnostics import AnyGraspDiagnostics
from .anygrasp_source import AnyGraspSource
from .environment import ScaleBenchEnv


class IsaacLabGraspCandidates:
    """Apply the task's object-frame rule to either configured candidate source."""

    def __init__(
        self,
        env: ScaleBenchEnv,
        task: RigidObjectTask,
        scene_config: SceneConfig,
        robot_configs: Mapping[Arm, RobotConfig],
        *,
        env_id: int,
    ) -> None:
        self._task = task
        # Asset runs have no online source and need neither cameras nor a service.
        self._anygrasp: AnyGraspSource | None = None
        self._asset_grasps: dict[tuple[Arm, str], tuple[GraspCandidate, ...]] = {}
        if scene_config.grasp_source == "anygrasp":
            self._anygrasp = AnyGraspSource(
                env,
                {name: metadata.size for name, metadata in task.metadata.items()},
                scene_config,
                robot_configs,
                env_id=env_id,
            )
        else:
            self._asset_grasps = {
                (arm, object_name): load_asset_grasps(Path(asset.usd_path), robot_configs[arm])
                for arm in ("left", "right")
                for object_name, asset in task.assets.items()
            }

    def candidates(
        self, object_name: str, arm: Arm, object_pose_env: Pose,
    ) -> tuple[GraspCandidate, ...]:
        if self._anygrasp is not None:
            diagnostics = self.analyze_anygrasp(object_name, arm, object_pose_env)
            candidates = diagnostics.candidates
            source_summary = (
                f"AnyGrasp detections={len(diagnostics.detections)}, "
                f"target_points={len(diagnostics.target_points_env_m)}"
            )
        else:
            candidates = tuple(
                candidate for candidate in self._asset_grasps[arm, object_name]
                if self._task.allows_grasp(object_name, candidate.tcp_pose_object)
            )
            source_summary = f"asset candidates={len(self._asset_grasps[arm, object_name])}"
        if not candidates:
            raise SkillError(
                f"no valid task-eligible {object_name!r} grasp for {arm} arm ({source_summary})"
            )
        return tuple(sorted(candidates, key=lambda item: item.score, reverse=True))

    def analyze_anygrasp(
        self, object_name: str, arm: Arm, object_pose_env: Pose,
    ) -> AnyGraspDiagnostics:
        if self._anygrasp is None:
            raise ValueError("AnyGrasp diagnostics require an AnyGrasp scene source")
        return self._anygrasp.analyze(
            object_name, arm, object_pose_env, partial(self._task.allows_grasp, object_name),
        )


__all__ = ["IsaacLabGraspCandidates"]
