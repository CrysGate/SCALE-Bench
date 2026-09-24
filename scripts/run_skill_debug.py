"""Run one manipulation skill, optionally inspecting CuRobo planning stages."""

import argparse
import os
import sys
from collections.abc import Iterator
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scale_bench.cli.simulation import (
    add_simulation_arguments,
    nonnegative_int,
    positive_int,
    run_simulation,
)
from scale_bench.runtime import EpisodeState, TerminationReason
from scale_bench.runtime.task_run import TaskRun
from scale_bench.skills import Pick, PickAndPlace, Pose, SkillRequest
from scale_bench.tasks.common.placement import PlacementContext


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_simulation_arguments(parser, PROJECT_ROOT)
    parser.add_argument(
        "--program", choices=("pick", "pick-and-place"), default="pick-and-place"
    )
    parser.add_argument("--seed", type=nonnegative_int, default=100)
    parser.add_argument("--max-steps", type=positive_int, default=1200)
    parser.add_argument(
        "--object-name", help="Omit to use the task's first target object."
    )
    parser.add_argument("--visualize-curobo", action="store_true")
    args = parser.parse_args()
    if args.visualize_curobo:
        if args.headless:
            parser.error("--visualize-curobo requires the Kit GUI")
        if args.visualizer_explicit and "kit" not in (args.visualizer or ()):
            parser.error("--visualize-curobo requires --viz kit")
        args.visualizer = ["kit"]
        args.visualizer_explicit = True
        os.environ["HEADLESS"] = "0"

    def execute(run: TaskRun) -> int:
        from scale_bench.isaaclab.runtime.skill_runner import run_skill_episodes

        object_name = args.object_name or run.task.target_object_order[0]
        if object_name not in run.task.metadata:
            raise ValueError(f"unknown --object-name: {object_name!r}")
        specs = run.episode_specs(
            base_seed=args.seed, episodes=1, max_steps=args.max_steps
        )
        target_layout = run.task.target_layout(
            PlacementContext.from_scene_config(run.scene)
        )

        def expert_factory(state: EpisodeState) -> Iterator[SkillRequest]:
            if args.program == "pick":
                return iter((Pick(object_name, "auto"),))
            object_pose_env = Pose(
                target_layout.assets[object_name].position_m,
                state.spec.layout.assets[object_name].orientation_xyzw,
            )
            return iter((PickAndPlace(object_name, "auto", object_pose_env),))

        with run.open_environment(specs, num_envs=1, recording=None) as env:
            result = run_skill_episodes(
                env,
                run,
                specs,
                expert_factory=expert_factory,
                visualize_curobo=args.visualize_curobo,
            )
        episode = result.episodes[specs[0].episode_id]
        print(
            f"steps={episode.steps} success={episode.success} termination={episode.termination.reason.value}"
        )
        if episode.termination.message:
            print(episode.termination.message, file=sys.stderr)
        completed = episode.termination.reason in {
            TerminationReason.CONTROLLER_FINISHED,
            TerminationReason.GOAL_REACHED,
        }
        return 0 if completed and episode.steps > 0 else 1

    return run_simulation(args, PROJECT_ROOT, execute)


if __name__ == "__main__":
    raise SystemExit(main())
