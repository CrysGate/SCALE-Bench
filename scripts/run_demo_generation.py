"""Collect complete task experts into an HDF5 demonstration dataset."""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scale_bench.cli.simulation import (
    add_simulation_arguments,
    nonnegative_int,
    positive_int,
    run_simulation,
)
from scale_bench.config.models.recording import RecordingConfig
from scale_bench.runtime.task_run import TaskRun

LOGGER = logging.getLogger("scale_bench.cli.demo_generation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_simulation_arguments(parser, PROJECT_ROOT)
    parser.add_argument("--num-envs", type=positive_int, default=1)
    parser.add_argument("--episodes", type=positive_int, default=1)
    parser.add_argument("--base-seed", type=nonnegative_int, default=100)
    parser.add_argument("--max-steps", type=positive_int, default=1200)
    parser.add_argument(
        "--record-output", type=Path, default=Path("outputs/demonstrations")
    )
    parser.add_argument("--dataset-name", default="demo_generation")
    parser.add_argument(
        "--record-camera-observations",
        action="store_true",
        help="Include wrist and overhead RGB-D; omit for joint/action data only.",
    )
    args = parser.parse_args()
    recording = RecordingConfig(
        output_dir=args.record_output.resolve(),
        dataset_name=args.dataset_name,
        record_camera_observations=args.record_camera_observations,
    )

    def execute(run: TaskRun) -> int:
        # Isaac runtime modules require an initialized application.
        from scale_bench.isaaclab.runtime.expert_collection import collect_expert_data

        specs = run.episode_specs(
            base_seed=args.base_seed,
            episodes=args.episodes,
            max_steps=args.max_steps,
        )
        result = collect_expert_data(
            run, specs, recording=recording, num_envs=args.num_envs
        )
        episode_count = len(result.benchmark.episodes)
        LOGGER.log(
            logging.INFO if result.success_count == episode_count else logging.WARNING,
            "success=%d/%d dataset=%s",
            result.success_count,
            episode_count,
            result.dataset_path,
            extra={
                "event": "SUMMARY",
                "event_fields": {
                    "task": run.task.task_id,
                    "episode_count": episode_count,
                    "success_count": result.success_count,
                    "success_rate": result.success_count / episode_count,
                    "batch_count": result.benchmark.batch_count,
                    "dataset_path": str(result.dataset_path),
                },
            },
        )
        return 0 if result.success_count == episode_count else 1

    return run_simulation(args, PROJECT_ROOT, execute)


if __name__ == "__main__":
    raise SystemExit(main())
