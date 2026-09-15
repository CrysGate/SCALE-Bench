"""Task and configuration inputs shared by collection and diagnostics."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scale_bench.api import create_env
from scale_bench.config.models.environment import EnvironmentConfig
from scale_bench.config.models.recording import RecordingConfig
from scale_bench.config.models.robot import RobotConfig
from scale_bench.config.models.scene import SceneConfig
from scale_bench.config.models.simulation import SimulationConfig
from scale_bench.tasks.common.fixed_target import FixedTargetRigidObjectTask
from scale_bench.tasks.common.placement import PlacementContext

from .episodes import EpisodeSpec

if TYPE_CHECKING:
    from scale_bench.isaaclab.runtime.environment import ScaleBenchEnv


@dataclass(frozen=True, slots=True)
class TaskRun:
    """Resolved inputs for one task, independent of command-line arguments."""

    task: FixedTargetRigidObjectTask
    scene: SceneConfig
    robot: RobotConfig
    simulation: SimulationConfig
    environment: EnvironmentConfig

    def episode_specs(
        self, *, base_seed: int, episodes: int, max_steps: int
    ) -> tuple[EpisodeSpec, ...]:
        context = PlacementContext.from_scene_config(self.scene)
        return tuple(
            EpisodeSpec(
                episode_id=f"demo-seed-{seed}",
                task_id=self.task.task_id,
                seed=seed,
                layout=self.task.generate_layout(context, seed),
                max_steps=max_steps,
            )
            for seed in range(base_seed, base_seed + episodes)
        )

    @contextmanager
    def open_environment(
        self,
        specs: Sequence[EpisodeSpec],
        *,
        num_envs: int,
        recording: RecordingConfig | None,
    ) -> Iterator[ScaleBenchEnv]:
        """Own the environment lifetime, including planner/setup failures.

        Collection supplies recording settings; skill and camera diagnostics
        pass None because they do not produce demonstration datasets.
        """
        layouts = tuple(spec.layout for spec in specs[:num_envs])
        env = create_env(
            left_robot_config=self.robot,
            right_robot_config=self.robot,
            scene_config=self.scene,
            simulation_config=self.simulation,
            environment_config=self.environment,
            recording_config=recording,
            task=self.task,
            layouts=layouts if len(layouts) == num_envs else (layouts[0],),
            device=self.simulation.device,
            num_envs=num_envs,
        )
        try:
            yield env
        finally:
            env.close()
