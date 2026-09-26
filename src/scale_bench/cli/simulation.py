"""Configure task clients and own the Isaac application lifecycle."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path

from isaaclab.app import AppLauncher

from scale_bench.cli.tasks import add_task_overrides
from scale_bench.config.loader import load_config
from scale_bench.config.models.environment import EnvironmentConfig
from scale_bench.config.models.robot import RobotConfig
from scale_bench.config.models.scene import SceneConfig
from scale_bench.config.models.simulation import SimulationConfig
from scale_bench.runtime.logging import configure_logging
from scale_bench.runtime.task_run import TaskRun
from scale_bench.tasks.registry import TASKS, load_task


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def add_simulation_arguments(
    parser: argparse.ArgumentParser, project_root: Path
) -> None:
    parser.add_argument(
        "--task", choices=TASKS, default="single_object_pick_and_place"
    )
    add_task_overrides(parser)
    for name, relative_path in (
        ("scene", "scene/default.yml"),
        ("robot", "robots/piper.yml"),
        ("camera", "cameras/d435.yml"),
        ("sim", "sim/default.yml"),
        ("env", "envs/default.yml"),
    ):
        parser.add_argument(
            f"--{name}-config",
            type=Path,
            default=project_root / "configs" / relative_path,
        )
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="DEBUG"
    )
    parser.add_argument("--log-format", choices=("pretty", "json"), default="pretty")
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Append DEBUG events to JSONL; omit for console-only logging.",
    )
    AppLauncher.add_app_launcher_args(parser)
    parser.set_defaults(enable_cameras=True, device=None, visualizer_explicit=False)


def run_simulation(
    args: argparse.Namespace, project_root: Path, action: Callable[[TaskRun], int]
) -> int:
    """Load profiles before launch, then close Isaac after all environments close."""
    configure_logging(
        console_level=args.log_level,
        console_format=args.log_format,
        jsonl_path=args.log_file,
    )
    simulation = load_config(args.sim_config, SimulationConfig)
    if args.device is None:  # An omitted CLI override uses the simulation profile.
        args.device = simulation.device
    if args.rendering_mode is None:
        args.rendering_mode = simulation.render.rendering_mode
    simulation = simulation.model_copy(update={"device": args.device})
    scene = load_config(args.scene_config, SceneConfig, asset_root=project_root)
    robot = load_config(args.robot_config, RobotConfig, asset_root=project_root)
    camera_profile_path = str(args.camera_config.resolve())
    scene = scene.model_copy(
        update={
            "camera": scene.camera.model_copy(
                update={"profile_path": camera_profile_path}
            )
        }
    )
    if robot.camera is None:
        raise ValueError("task clients require mounted robot cameras")
    robot = robot.model_copy(
        update={
            "camera": robot.camera.model_copy(
                update={"profile_path": camera_profile_path}
            )
        }
    )
    task = load_task(
        args.task, project_root=project_root, asset_root=project_root,
        config_path=args.task_config, object_set_path=args.object_set,
    )
    run = TaskRun(
        task=task,
        scene=scene,
        robot=robot,
        simulation=simulation,
        environment=load_config(args.env_config, EnvironmentConfig).model_copy(
            update={"enable_cameras": args.enable_cameras}
        ),
    )
    app = AppLauncher(args).app
    exit_code = 1
    try:
        exit_code = action(run)
    except Exception:
        logging.getLogger("scale_bench.cli").exception("task client failed")
    finally:
        app.close(exit_code=exit_code)
    return exit_code
