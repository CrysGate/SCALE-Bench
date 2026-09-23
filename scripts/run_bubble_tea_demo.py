"""Collect bubble-tea demonstrations using the asynchronous CuRobo skill runtime.

Use --record-cameras for RGB-D, or --check-config to validate inputs without
starting Isaac. Existing seed, success-count and grasp-file options are retained.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scale_bench.api import create_env
from scale_bench.config.loader import load_config
from scale_bench.config.models.environment import EnvironmentConfig
from scale_bench.config.models.recording import RecordingConfig
from scale_bench.config.models.robot import RobotConfig
from scale_bench.config.models.scene import SceneConfig
from scale_bench.config.models.simulation import SimulationConfig
from scale_bench.runtime.asset_grasps import load_asset_grasps
from scale_bench.runtime.episodes import EpisodeSpec, EpisodeState
from scale_bench.runtime.logging import configure_logging, record_skill_events
from scale_bench.runtime.task_run import TaskRun
from scale_bench.tasks.common.placement import PlacementContext
from scale_bench.tasks.bubble_tea_cup_800g_pick_and_place.config import BubbleTeaCupPickAndPlaceConfig
from scale_bench.tasks.bubble_tea_cup_800g_pick_and_place.task import BubbleTeaCup800gPickAndPlace


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from isaaclab.app import AppLauncher

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path, default=Path("."))
    parser.add_argument(
        "--task",
        choices=("bubble_tea_cup_800g_pick_and_place",),
        default="bubble_tea_cup_800g_pick_and_place",
    )
    parser.add_argument("--config", type=Path, default=Path("configs/scene/default.yml"))
    parser.add_argument("--sim-config", type=Path, default=Path("configs/sim/default.yml"))
    parser.add_argument("--env-config", type=Path, default=Path("configs/envs/default.yml"))
    parser.add_argument("--left-robot-config", type=Path, default=Path("configs/robots/piper.yml"))
    parser.add_argument("--right-robot-config", type=Path, default=Path("configs/robots/piper.yml"))
    parser.add_argument("--grasp-file", type=Path, default=Path("outputs/grasp_data/piper/bubble_tea_cup_800g_target/successful_grasps.yaml"))
    parser.add_argument("--record-dir", type=Path, default=Path("outputs/demos/bubble_tea_cup_800g"))
    parser.add_argument("--dataset-name", default="bubble_tea_cup_800g_expert")
    parser.add_argument("--record-cameras", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        help="Explicit seed attempts; overrides the sequence starting at --seed.",
    )
    parser.add_argument(
        "--success-count",
        type=int,
        default=1,
        help="Number of successful episodes to collect across seed attempts.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        help="Maximum seed attempts (default: three times --success-count).",
    )
    parser.add_argument("--max-steps", type=int, default=600)
    AppLauncher.add_app_launcher_args(parser)
    parser.add_argument("--check-config", action="store_true", help="Validate configs, layouts and grasp candidates without launching Isaac.")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    parser.set_defaults(enable_cameras=False, device=None)
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    if args.seeds is not None and (
        any(seed < 0 for seed in args.seeds) or len(args.seeds) != len(set(args.seeds))
    ):
        parser.error("--seeds must contain unique non-negative integers")
    if args.max_steps <= 0:
        parser.error("--max-steps must be positive")
    if args.success_count <= 0:
        parser.error("--success-count must be positive")
    if args.max_attempts is not None and args.max_attempts < args.success_count:
        parser.error("--max-attempts must be at least --success-count")
    if not args.grasp_file.is_file():
        parser.error(f"grasp file does not exist: {args.grasp_file}")

    args.enable_cameras = args.enable_cameras or args.record_cameras
    requested_seeds = (
        args.seeds if args.seeds is not None
        else list(range(args.seed, args.seed + (args.max_attempts or args.success_count * 3)))
    )
    args.requested_seeds = requested_seeds[:args.max_attempts]
    if len(args.requested_seeds) < args.success_count:
        parser.error("the seed attempt list is shorter than --success-count")
    return args

def main(argv: list[str] | None = None) -> int:
    from isaaclab.app import AppLauncher

    process_started_at = time.perf_counter()
    args = parse_args(argv)
    configure_logging(console_level=args.log_level, console_format="pretty", jsonl_path=None)
    scene = load_config(args.config, SceneConfig, asset_root=args.asset_root)
    simulation = load_config(args.sim_config, SimulationConfig)
    args.device = args.device or simulation.device
    if args.rendering_mode is None:
        args.rendering_mode = simulation.render.rendering_mode
    simulation = simulation.model_copy(update={"device": args.device})
    environment = load_config(args.env_config, EnvironmentConfig).model_copy(
        update={"enable_cameras": args.enable_cameras}
    )
    profiles = {
        "left": load_config(args.left_robot_config, RobotConfig, asset_root=args.asset_root),
        "right": load_config(args.right_robot_config, RobotConfig, asset_root=args.asset_root),
    }
    task = BubbleTeaCup800gPickAndPlace(load_config(
        PROJECT_ROOT / "configs/tasks/bubble_tea_cup_800g_pick_and_place.yml",
        BubbleTeaCupPickAndPlaceConfig, asset_root=args.asset_root,
    ))
    placement_context = PlacementContext.from_scene_config(scene)
    source_layout = task.resolve_layout(placement_context, seed=args.requested_seeds[0])
    target_layout = task.target_layout(placement_context)
    # The task explicitly uses the right arm. Distractor cups need no grasp files.
    candidates = load_asset_grasps(
        Path(task.assets[task.target_name].usd_path), profiles["right"],
        grasp_file=args.grasp_file,
    )
    recording = RecordingConfig(
        output_dir=args.record_dir.resolve(), dataset_name=args.dataset_name,
        record_camera_observations=args.record_cameras,
    )
    run = TaskRun(task, scene, profiles["left"], simulation, environment)
    if args.check_config:
        for seed in args.requested_seeds:
            layout = task.resolve_layout(placement_context, seed=seed)
            tuple(task.expert(source_layout=layout, target_layout=target_layout))
        print(f"[demo] config OK: seeds={args.requested_seeds} grasps={len(candidates)} "
              f"device={args.device} cameras={args.enable_cameras}")
        return 0

    import torch

    if not str(args.device).startswith("cuda") or not torch.cuda.is_available():
        raise RuntimeError("The CuRobo skill runtime requires CUDA. Check the NVIDIA driver "
                           "and select --device cuda:0; CPU fallback is not supported.")
    if args.visualizer == ["none"]:
        args.headless = True
    app = AppLauncher(args).app
    exit_code = 1
    try:
        # Import simulator-dependent modules only after the application starts.
        from scale_bench.isaaclab.runtime.skill_runner import open_skill_runner

        with ExitStack() as resources:
            env = create_env(
                left_robot_config=profiles["left"], right_robot_config=profiles["right"],
                scene_config=scene, simulation_config=simulation,
                environment_config=environment, recording_config=recording,
                task=task, layouts=(source_layout,), device=args.device, num_envs=1,
            )
            resources.callback(env.close)
            env.reset()
            recorder_config = env.recorder_manager.cfg
            dataset_path = (Path(recorder_config.dataset_export_dir_path)
                            / f"{recorder_config.dataset_filename}.hdf5").resolve()
            resources.enter_context(record_skill_events(dataset_path.with_suffix(".segments.jsonl")))
            runner = resources.enter_context(open_skill_runner(
                env, run, robot_configs=profiles,
                grasp_files={task.target_name: args.grasp_file},
                expert_factory=lambda state: task.expert(
                    source_layout=state.spec.layout, target_layout=target_layout,
                ),
            ))
            print(f"dataset={dataset_path}")
            print(f"segments={dataset_path.with_suffix('.segments.jsonl')}")
            _collect(args, env, runner, task, scene, profiles, process_started_at)
        exit_code = 0
        return exit_code
    finally:
        app.close(exit_code=exit_code)


def _collect(args, env, runner, task, scene_config, profiles, process_started_at) -> None:
    from scale_bench.isaaclab.runtime.skill_context import IsaacLabSkillContext

    placement_context = PlacementContext.from_scene_config(scene_config)
    successful_seeds: list[int] = []
    episode_elapsed_s: list[float] = []
    batch_started_at = time.perf_counter()
    attempt_count = 0
    for seed in args.requested_seeds:
        if len(successful_seeds) >= args.success_count:
            break
        attempt_count += 1
        layout = task.resolve_layout(placement_context, seed=seed)
        state = EpisodeState(
            env_id=0,
            spec=EpisodeSpec(
                episode_id=f"bubble_tea_cup_800g_{seed:06d}",
                task_id=task.task_id,
                seed=seed,
                layout=layout,
                max_steps=args.max_steps,
            ),
        )
        print(
            f"[demo] runner starting seed={seed} "
            f"successes={len(successful_seeds)}/{args.success_count}",
            flush=True,
        )
        episode_started_at = time.perf_counter()
        results = runner.run_batch((state,))
        elapsed_s = time.perf_counter() - episode_started_at
        result = results[state.spec.episode_id]
        print(
            f"[demo] runner finished seed={seed} elapsed_s={elapsed_s:.3f}",
            flush=True,
        )
        final_snapshot = IsaacLabSkillContext(
            env, task, scene_config, profiles, env_id=0,
            grasp_files={task.target_name: args.grasp_file},
        ).snapshot()
        for object_state in final_snapshot.objects:
            print(
                "[demo] final_object="
                f"{object_state.name} "
                f"position={tuple(round(value, 5) for value in object_state.pose_env.position_m)} "
                f"orientation={tuple(round(value, 5) for value in object_state.pose_env.orientation_xyzw)}",
                flush=True,
            )
        print(
            f"episode={state.spec.episode_id} success={result.success} "
            f"termination={result.termination.reason} steps={result.steps}"
        )
        if result.evaluation.metrics:
            print(f"metrics={dict(result.evaluation.metrics)}")
        if result.success:
            successful_seeds.append(seed)
            episode_elapsed_s.append(elapsed_s)

    batch_elapsed_s = time.perf_counter() - batch_started_at
    total_elapsed_s = time.perf_counter() - process_started_at
    print(
        f"[demo] successful_seeds={successful_seeds} "
        f"successes={len(successful_seeds)}/{args.success_count} "
        f"episode_elapsed_s={[round(value, 3) for value in episode_elapsed_s]} "
        f"batch_elapsed_s={batch_elapsed_s:.3f} "
        f"total_elapsed_s={total_elapsed_s:.3f}",
        flush=True,
    )
    print(f"recording_dir={args.record_dir.resolve()}")
    if len(successful_seeds) < args.success_count:
        raise RuntimeError(
            f"collected only {len(successful_seeds)} successful seeds "
            f"after {attempt_count} attempts"
        )


if __name__ == "__main__":
    raise SystemExit(main())
