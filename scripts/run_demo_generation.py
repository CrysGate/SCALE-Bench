"""Generate one scripted bubble-tea pick-and-place demonstration.

The task expert is expanded through the project's Hold/Move/Gripper atomic
commands, planned by the Isaac Lab adapter, and exported through the native
episode recorder.  Use ``--record-cameras`` to include RGB-D observations.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROCESS_STARTED_AT = time.perf_counter()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from isaaclab.app import AppLauncher

from scale_bench.api import create_env
from scale_bench.config.loader import load_config
from scale_bench.config.models.environment import EnvironmentConfig
from scale_bench.config.models.recording import RecordingConfig
from scale_bench.config.models.robot import RobotConfig
from scale_bench.config.models.scene import SceneConfig
from scale_bench.config.models.simulation import SimulationConfig
from scale_bench.isaaclab.runtime.skill_adapter import (
    IsaacLabSkillContext,
    PinocchioMotionPlanner,
)
from scale_bench.runtime.demo_generation import DemoGenerationRunner
from scale_bench.runtime.episodes import EpisodeSpec, EpisodeState
from scale_bench.skills.executor import CommandActionLayout, CommandExecutor
from scale_bench.skills.planner import OperationSkillPlanner
from scale_bench.skills.models import Pose
from scale_bench.tasks.common.placement import PlacementContext
from scale_bench.tasks.bubble_tea_cup_800g_pick_and_place.config import (
    BubbleTeaCupPickAndPlaceConfig,
)
from scale_bench.tasks.bubble_tea_cup_800g_pick_and_place.task import (
    BubbleTeaCup800gPickAndPlace,
)


def _cuda_available() -> bool:
    result = subprocess.run(
        [sys.executable, "-c", "import torch; raise SystemExit(not torch.cuda.is_available())"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


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
    help="Number of successful consecutive seed attempts to collect.",
)
parser.add_argument(
    "--max-attempts",
    type=int,
    help="Maximum seed attempts (default: three times --success-count).",
)
parser.add_argument("--max-steps", type=int, default=600)
AppLauncher.add_app_launcher_args(parser)
parser.set_defaults(enable_cameras=True, device=None)
args = parser.parse_args()
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

sim_config = load_config(args.sim_config, SimulationConfig)
if args.device is None:
    args.device = sim_config.device
if args.device.startswith("cuda") and not _cuda_available():
    print(f"CUDA device {args.device!r} is unavailable; falling back to CPU", file=sys.stderr)
    args.device = "cpu"
if args.visualizer == ["none"]:
    args.headless = True

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def _action_layout(env, left_profile: RobotConfig, right_profile: RobotConfig) -> CommandActionLayout:
    descriptors = {item["name"]: item for item in env.get_IO_descriptors["actions"]}

    def action_range(name: str) -> tuple[int, int]:
        return tuple(descriptors[name]["slice"])

    left_gripper = left_profile.gripper
    right_gripper = right_profile.gripper
    return CommandActionLayout(
        action_dim=env.action_manager.total_action_dim,
        left_arm=action_range("left_arm"),
        left_gripper=action_range("left_gripper"),
        right_arm=action_range("right_arm"),
        right_gripper=action_range("right_gripper"),
        left_gripper_open=tuple(left_gripper.open_positions[name] for name in descriptors["left_gripper"]["joint_names"]),
        left_gripper_closed=tuple(left_gripper.closed_positions[name] for name in descriptors["left_gripper"]["joint_names"]),
        right_gripper_open=tuple(right_gripper.open_positions[name] for name in descriptors["right_gripper"]["joint_names"]),
        right_gripper_closed=tuple(right_gripper.closed_positions[name] for name in descriptors["right_gripper"]["joint_names"]),
    )


def main() -> None:
    print("[demo] loading configs", flush=True)
    scene_config = load_config(args.config, SceneConfig, asset_root=args.asset_root)
    runtime_config = load_config(args.env_config, EnvironmentConfig)
    left_profile = load_config(args.left_robot_config, RobotConfig, asset_root=args.asset_root)
    right_profile = load_config(args.right_robot_config, RobotConfig, asset_root=args.asset_root)
    task = BubbleTeaCup800gPickAndPlace(
        load_config(
            PROJECT_ROOT / "configs/tasks/bubble_tea_cup_800g_pick_and_place.yml",
            BubbleTeaCupPickAndPlaceConfig,
            asset_root=args.asset_root,
        )
    )
    placement_context = PlacementContext.from_scene_config(scene_config)
    initial_seed = args.seeds[0] if args.seeds else args.seed
    source_layout = task.resolve_layout(placement_context, seed=initial_seed)
    target_layout = task.target_layout(placement_context)
    recording = RecordingConfig(
        output_dir=args.record_dir,
        dataset_name=args.dataset_name,
        record_camera_observations=args.record_cameras,
    )
    env = create_env(
        left_robot_config=left_profile,
        right_robot_config=right_profile,
        scene_config=scene_config,
        simulation_config=sim_config,
        environment_config=runtime_config,
        recording_config=recording,
        task=task,
        layouts=(source_layout,),
        device=args.device,
    )
    try:
        print("[demo] environment created", flush=True)
        env.reset()
        print("[demo] environment reset", flush=True)
        action_layout = _action_layout(env, left_profile, right_profile)
        print("[demo] action layout ready", flush=True)
        executor = CommandExecutor(env, action_layout)
        tcp_from_ee = IsaacLabSkillContext(
            env,
            task,
            left_profile,
            right_profile,
            args.grasp_file,
        ).tcp_from_ee
        mounts = scene_config.robot_mounts

        def make_context(state: EpisodeState) -> IsaacLabSkillContext:
            return IsaacLabSkillContext(
                env,
                task,
                left_profile,
                right_profile,
                args.grasp_file,
                env_id=state.env_id,
                tcp_from_ee=tcp_from_ee,
            )

        def make_planner(state: EpisodeState) -> OperationSkillPlanner:
            context = make_context(state)
            motion_planners = {
                "left": PinocchioMotionPlanner(
                    env, "left", left_profile,
                    tuple(mounts.left.position_xy_m) + (scene_config.table_top_z_m,),
                    mounts.left.orientation_xyzw,
                    context.tcp_from_ee,
                    env_id=state.env_id,
                ),
                "right": PinocchioMotionPlanner(
                    env, "right", right_profile,
                    tuple(mounts.right.position_xy_m) + (scene_config.table_top_z_m,),
                    mounts.right.orientation_xyzw,
                    context.tcp_from_ee,
                    env_id=state.env_id,
                ),
            }
            return OperationSkillPlanner(
                motion_planners,
                {
                    "left": tuple(mounts.left.position_xy_m) + (scene_config.table_top_z_m,),
                    "right": tuple(mounts.right.position_xy_m) + (scene_config.table_top_z_m,),
                },
                lift_height_m=0.18,
            )

        runner = DemoGenerationRunner(
            env,
            executor,
            expert_factory=lambda state: task.expert(
                source_layout=state.spec.layout,
                target_layout=target_layout,
            ),
            context_factory=make_context,
            planner_factory=make_planner,
        )
        requested_seeds = (
            args.seeds
            if args.seeds is not None
            else list(
                range(
                    args.seed,
                    args.seed + (args.max_attempts or args.success_count * 3),
                )
            )
        )
        max_attempts = args.max_attempts or len(requested_seeds)
        requested_seeds = requested_seeds[:max_attempts]
        if len(requested_seeds) < args.success_count:
            raise ValueError(
                "the seed attempt list is shorter than --success-count"
            )
        successful_seeds: list[int] = []
        episode_elapsed_s: list[float] = []
        batch_started_at = time.perf_counter()
        for seed in requested_seeds:
            if len(successful_seeds) >= args.success_count:
                break
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
            final_snapshot = make_context(state).snapshot()
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
        total_elapsed_s = time.perf_counter() - PROCESS_STARTED_AT
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
                f"after {max_attempts} attempts"
            )
    finally:
        env.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        simulation_app.close()
