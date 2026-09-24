"""Collect complete task experts into one recorded dataset."""

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from scale_bench.config.models.recording import RecordingConfig
from scale_bench.runtime import EpisodeSpec, EpisodeState
from scale_bench.runtime.logging import record_skill_events
from scale_bench.runtime.scheduler import BenchmarkRunResult
from scale_bench.runtime.task_run import TaskRun
from scale_bench.skills import SkillRequest
from scale_bench.tasks.common.placement import PlacementContext

from .skill_runner import run_skill_episodes

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CollectionResult:
    dataset_path: Path
    benchmark: BenchmarkRunResult

    @property
    def segments_path(self) -> Path:
        return self.dataset_path.with_suffix(".segments.jsonl")

    @property
    def success_count(self) -> int:
        return sum(episode.success for episode in self.benchmark.episodes.values())


def collect_expert_data(
    run: TaskRun,
    specs: Sequence[EpisodeSpec],
    *,
    recording: RecordingConfig,
    num_envs: int,
) -> CollectionResult:
    """Execute task-owned experts and return after the dataset is closed."""
    target_layout = run.task.target_layout(
        PlacementContext.from_scene_config(run.scene)
    )

    def expert_factory(state: EpisodeState) -> Iterator[SkillRequest]:
        return run.task.expert(
            source_layout=state.spec.layout, target_layout=target_layout
        )

    with run.open_environment(specs, num_envs=num_envs, recording=recording) as env:
        LOGGER.info(
            "collecting task=%s episodes=%d num_envs=%d",
            run.task.task_id,
            len(specs),
            num_envs,
        )
        recorder_config = env.recorder_manager.cfg
        dataset_path = (
            Path(recorder_config.dataset_export_dir_path)
            / f"{recorder_config.dataset_filename}.hdf5"
        ).resolve()
        with record_skill_events(dataset_path.with_suffix(".segments.jsonl")):
            result = run_skill_episodes(
                env, run, specs, expert_factory=expert_factory, visualize_curobo=False,
            )
            for episode in result.episodes.values():
                LOGGER.log(
                    logging.INFO if episode.success else logging.WARNING,
                    "seed=%d steps=%d success=%s termination=%s",
                    episode.spec.seed,
                    episode.steps,
                    episode.success,
                    episode.termination.reason.value,
                    extra={
                        "event": "EPISODE",
                        "event_fields": {
                            "episode_id": episode.spec.episode_id,
                            "seed": episode.spec.seed,
                            "step_count": episode.steps,
                            "success": episode.success,
                            "progress": episode.evaluation.progress,
                            "metrics": dict(episode.evaluation.metrics),
                            "termination": episode.termination.reason.value,
                            "termination_message": episode.termination.message,
                        },
                    },
                )
    return CollectionResult(dataset_path=dataset_path, benchmark=result)
