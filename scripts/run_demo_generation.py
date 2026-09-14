"""Run the expert/skill runtime against a real ScaleBenchEnv."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

SUPPORTED_TASK_IDS = (
    "sort_dolls_by_size",
    "single_object_pick_and_place",
)
LOGGER = logging.getLogger("scale_bench.cli.demo_generation")


@dataclass(frozen=True, slots=True)
class GuiReplayRequest:
    """Concrete recording and launch inputs passed between clean processes."""

    dataset_path: Path
    episode_ids: tuple[str, ...]
    task_id: str
    scene_config: Path
    robot_config: Path
    camera_config: Path
    sim_config: Path
    env_config: Path
    device: str
    rendering_mode: str
    deterministic: bool

    def write(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "dataset_path": str(self.dataset_path),
                    "episode_ids": self.episode_ids,
                    "task_id": self.task_id,
                    "scene_config": str(self.scene_config),
                    "robot_config": str(self.robot_config),
                    "camera_config": str(self.camera_config),
                    "sim_config": str(self.sim_config),
                    "env_config": str(self.env_config),
                    "device": self.device,
                    "rendering_mode": self.rendering_mode,
                    "deterministic": self.deterministic,
                }
            ),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: Path) -> GuiReplayRequest:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            dataset_path=Path(payload["dataset_path"]),
            episode_ids=tuple(payload["episode_ids"]),
            task_id=payload["task_id"],
            scene_config=Path(payload["scene_config"]),
            robot_config=Path(payload["robot_config"]),
            camera_config=Path(payload["camera_config"]),
            sim_config=Path(payload["sim_config"]),
            env_config=Path(payload["env_config"]),
            device=payload["device"],
            rendering_mode=payload["rendering_mode"],
            deterministic=payload["deterministic"],
        )


def _run_gui_replays(request: GuiReplayRequest) -> int:
    """Launch exact-state GUI replay in a clean Isaac process."""

    if not request.dataset_path.is_file():
        raise FileNotFoundError(
            f"recorded dataset does not exist: {request.dataset_path}"
        )

    replay_environment = os.environ.copy()
    replay_environment["HEADLESS"] = "0"
    replay_environment["LIVESTREAM"] = "0"
    for episode_id in request.episode_ids:
        command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts/replay_episode.py"),
            str(request.dataset_path),
            "--episode-name",
            episode_id,
            "--task",
            request.task_id,
            "--scene-config",
            str(request.scene_config),
            "--robot-config",
            str(request.robot_config),
            "--camera-config",
            str(request.camera_config),
            "--sim-config",
            str(request.sim_config),
            "--env-config",
            str(request.env_config),
            "--device",
            request.device,
            "--rendering_mode",
            request.rendering_mode,
            "--viz",
            "kit",
            "--wait-for-close",
        ]
        if request.deterministic:
            command.append("--deterministic")
        print(
            f"[gui-replay] dataset={request.dataset_path} episode={episode_id}",
            flush=True,
        )
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=replay_environment,
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
    return 0


def _run_generation_then_replay() -> int:
    """Supervise isolated headless generation and GUI replay processes."""

    generation_arguments = [
        argument
        for argument in sys.argv[1:]
        if argument not in {"--replay", "--replay-after-generation"}
    ]
    with tempfile.TemporaryDirectory(prefix="scale-bench-replay-") as temp_dir:
        manifest_path = Path(temp_dir) / "replay.json"
        generation_command = [
            sys.executable,
            str(Path(__file__).resolve()),
            *generation_arguments,
            "--replay-manifest",
            str(manifest_path),
        ]
        print(
            "[gui-replay] starting isolated generation process",
            flush=True,
        )
        generation = subprocess.run(generation_command, check=False)
        if not manifest_path.is_file():
            print(
                "[gui-replay] generation did not produce a replay manifest",
                file=sys.stderr,
                flush=True,
            )
            return generation.returncode or 1

        replay_exit_code = _run_gui_replays(GuiReplayRequest.read(manifest_path))
        return 0 if generation.returncode == 0 and replay_exit_code == 0 else 1


def _run_open3d_diagnostics() -> int:
    """Collect with Isaac, then view in a clean Open3D process."""

    collection_arguments = [
        argument for argument in sys.argv[1:] if argument != "--open3d"
    ]
    with tempfile.TemporaryDirectory(prefix="scale-bench-anygrasp-") as temp_dir:
        bundle_path = Path(temp_dir) / "anygrasp_open3d.npz"
        collection_command = [
            sys.executable,
            str(Path(__file__).resolve()),
            *collection_arguments,
            "--open3d-bundle",
            str(bundle_path),
        ]
        print(
            "[anygrasp-open3d] collecting RGB-D in an isolated Isaac process",
            flush=True,
        )
        collection = subprocess.run(collection_command, check=False)
        if collection.returncode != 0 or not bundle_path.is_file():
            return collection.returncode or 1
        print(
            "[anygrasp-open3d] Isaac closed; launching clean Open3D viewer",
            flush=True,
        )
        viewer_environment = os.environ.copy()
        viewer_environment.pop("WAYLAND_DISPLAY", None)
        viewer_environment["XDG_SESSION_TYPE"] = "x11"
        viewer_environment["GDK_BACKEND"] = "x11"
        viewer = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts/view_anygrasp_open3d.py"),
                str(bundle_path),
            ],
            cwd=PROJECT_ROOT,
            env=viewer_environment,
            check=False,
        )
        return viewer.returncode


from isaaclab.app import AppLauncher

from scale_bench.config.loader import load_config
from scale_bench.config.models.simulation import SimulationConfig

parser = argparse.ArgumentParser()
parser.add_argument(
    "--task",
    choices=SUPPORTED_TASK_IDS,
    default="sort_dolls_by_size",
    help="Task whose layouts, expert, and success evaluator are executed.",
)
parser.add_argument("--num-envs", type=int, default=1)
parser.add_argument(
    "--episodes",
    type=int,
    default=1,
    help="Episode count.",
)
parser.add_argument("--base-seed", type=int, default=100)
parser.add_argument("--max-steps", type=int, default=128)
parser.add_argument(
    "--log-level",
    choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    default="DEBUG",
    help="Minimum console log level; use DEBUG for per-candidate details.",
)
parser.add_argument(
    "--log-format",
    choices=("pretty", "json"),
    default="pretty",
    help="Human-readable terminal events or one JSON object per console line.",
)
parser.add_argument(
    "--log-file",
    type=Path,
    default=None,
    help="Append all events, including DEBUG details, to this JSONL file.",
)
parser.add_argument(
    "--program",
    choices=(
        "pick",
        "pick-and-place",
        "expert",
        "grasp-diagnostics",
    ),
    default="pick",
    help=(
        "Run one pick, one complete pick-and-place, the full expert, or "
        "inspect/physically validate every AnyGrasp candidate."
    ),
)
parser.add_argument(
    "--object-name",
    default=None,
    help=(
        "Object used by pick and pick-and-place (defaults to the task's "
        "benchmark object); expert always runs the full task."
    ),
)
parser.add_argument("--record-output", type=Path, default=None)
parser.add_argument("--dataset-name", default="demo_generation")
parser.add_argument(
    "--record-camera-observations",
    action="store_true",
    help=(
        "Record RGB-D observations from the left wrist, right wrist, and "
        "overhead cameras. Omit to reduce recording size and runtime cost. "
        "Requires --record-output."
    ),
)
parser.add_argument(
    "--replay-after-generation",
    "--replay",
    action="store_true",
    help=(
        "After generation, replay every recorded episode in the Kit GUI. "
        "Requires --record-output."
    ),
)
parser.add_argument(
    "--replay-manifest",
    type=Path,
    default=None,
    help=argparse.SUPPRESS,
)
parser.add_argument(
    "--scene-config",
    type=Path,
    default=Path("configs/scene/default.yml"),
    help="Scene profile.",
)
parser.add_argument(
    "--grasp-source",
    choices=("asset", "anygrasp"),
    default="asset",
    help="Load asset grasps.yaml (default), or request candidates from AnyGrasp.",
)
parser.add_argument(
    "--grasp-arm",
    choices=("auto", "left", "right"),
    default="auto",
    help=(
        "Arm used by grasp diagnostics; auto "
        "selects the arm nearest the object."
    ),
)
parser.add_argument(
    "--diagnostics-output",
    type=Path,
    default=None,
    help=(
        "Write grasp-diagnostics evidence as JSON; omit for console or "
        "Open3D inspection."
    ),
)
parser.add_argument(
    "--open3d",
    action="store_true",
    help=(
        "Open the exact request RGB-D images, then the official-style RGB "
        "point-cloud and raw gripper viewer. Used only with --program "
        "grasp-diagnostics."
    ),
)
parser.add_argument(
    "--open3d-bundle",
    type=Path,
    default=None,
    help=argparse.SUPPRESS,
)
parser.add_argument(
    "--camera-config",
    type=Path,
    default=Path("configs/cameras/d435.yml"),
    help="Camera profile used for AnyGrasp RGB-D inference.",
)
parser.add_argument(
    "--robot-config",
    type=Path,
    default=Path("configs/robots/x5.yml"),
    help="Robot profile used by both arms and by recorded-episode replay.",
)
parser.add_argument(
    "--sim-config",
    type=Path,
    default=Path("configs/sim/default.yml"),
)
parser.add_argument(
    "--env-config",
    type=Path,
    default=Path("configs/envs/default.yml"),
)
parser.add_argument(
    "--visualize-curobo",
    action="store_true",
    help=(
        "Collect exact CuRobo robot spheres and collision-world cuboids, then "
        "browse attempted planning stages in Kit after the episode. Requires "
        "one environment."
    ),
)
AppLauncher.add_app_launcher_args(parser)
parser.set_defaults(enable_cameras=True, device=None)
args = parser.parse_args()
if args.num_envs <= 0:
    parser.error("--num-envs must be positive")
if args.episodes <= 0:
    parser.error("--episodes must be positive")
if args.base_seed < 0:
    parser.error("--base-seed must be non-negative")
if args.max_steps <= 0:
    parser.error("--max-steps must be positive")
if args.visualize_curobo:
    if args.num_envs != 1:
        parser.error("--visualize-curobo requires --num-envs 1")
    if args.headless:
        parser.error("--visualize-curobo cannot be combined with --headless")
    if not getattr(args, "visualizer_explicit", False):
        args.visualizer = ["kit"]
        args.visualizer_explicit = True
    elif args.visualizer is None or "kit" not in args.visualizer:
        parser.error("--visualize-curobo requires --viz kit")
    os.environ["HEADLESS"] = "0"
if args.record_camera_observations and args.record_output is None:
    parser.error("--record-camera-observations requires --record-output")
if args.replay_after_generation and args.record_output is None:
    parser.error("--replay-after-generation requires --record-output")
if args.replay_manifest is not None and args.record_output is None:
    parser.error("--replay-manifest requires --record-output")
if args.program == "grasp-diagnostics":
    if args.num_envs != 1 or args.episodes != 1:
        parser.error("grasp-diagnostics requires --num-envs 1 --episodes 1")
    if args.grasp_source != "anygrasp":
        parser.error("grasp-diagnostics requires --grasp-source anygrasp")
    if args.record_output is not None:
        parser.error("grasp-diagnostics does not record an episode")
if args.program != "grasp-diagnostics":
    if args.diagnostics_output is not None:
        parser.error("--diagnostics-output requires --program grasp-diagnostics")
    if args.open3d:
        parser.error("--open3d requires --program grasp-diagnostics")
    if args.open3d_bundle is not None:
        parser.error("--open3d-bundle requires --program grasp-diagnostics")
if args.replay_after_generation and args.replay_manifest is None:
    raise SystemExit(_run_generation_then_replay())
if args.open3d and args.open3d_bundle is None:
    raise SystemExit(_run_open3d_diagnostics())

sim_config = load_config(args.sim_config, SimulationConfig)
if args.device is None:
    args.device = sim_config.device
if args.rendering_mode is None:
    args.rendering_mode = sim_config.render.rendering_mode

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


from scale_bench.api import create_env
from scale_bench.config.models.environment import EnvironmentConfig
from scale_bench.config.models.recording import RecordingConfig
from scale_bench.config.models.robot import RobotConfig
from scale_bench.config.models.scene import SceneConfig
from scale_bench.isaaclab.runtime.anygrasp_diagnostics import (
    AnyGraspDiagnostics,
    AnyGraspOpen3DFrame,
)
from scale_bench.isaaclab.runtime.command_adapter import build_command_action_layout
from scale_bench.isaaclab.runtime.curobo_planner import (
    build_curobo_motion_planners,
)
from scale_bench.isaaclab.runtime.environment import ScaleBenchEnv
from scale_bench.isaaclab.runtime.skill_context import IsaacLabSkillContext
from scale_bench.runtime import (
    BenchmarkScheduler,
    DemoGenerationRunner,
    EpisodeSpec,
    EpisodeState,
    TerminationReason,
)
from scale_bench.runtime.logging import configure_logging
from scale_bench.skills import (
    Arm,
    ArmSelection,
    CommandExecutor,
    OperationSkillPlanner,
    Pick,
    PickAndPlace,
    Pose,
    SkillContext,
    SkillRequest,
)
from scale_bench.tasks.common.placement import PlacementContext
from scale_bench.tasks.common.rigid_object import RigidObjectTask
from scale_bench.tasks.single_object_pick_and_place.config import (
    SingleObjectPickAndPlaceConfig,
)
from scale_bench.tasks.single_object_pick_and_place.task import (
    SingleObjectPickAndPlace,
)
from scale_bench.tasks.sort_dolls_by_size.config import SortDollsBySizeConfig
from scale_bench.tasks.sort_dolls_by_size.task import SortDollsBySize


def _resolve_grasp_arm(
    arm_selection: ArmSelection,
    spec: EpisodeSpec,
    object_name: str,
    scene_config: SceneConfig,
) -> Arm:
    """Resolve auto with the same nearest-base rule used by the planner."""

    if arm_selection != "auto":
        return arm_selection
    object_position_env_m = spec.layout.assets[object_name].position_m
    arm_base_positions_env_m = {
        "left": (
            *scene_config.robot_mounts.left.position_xy_m,
            scene_config.table_top_z_m,
        ),
        "right": (
            *scene_config.robot_mounts.right.position_xy_m,
            scene_config.table_top_z_m,
        ),
    }
    arms: tuple[Arm, Arm] = ("left", "right")
    return min(
        arms,
        key=lambda arm: sum(
            (object_coordinate_env_m - base_coordinate_env_m) ** 2
            for object_coordinate_env_m, base_coordinate_env_m in zip(
                object_position_env_m,
                arm_base_positions_env_m[arm],
                strict=True,
            )
        ),
    )


def _recording_dataset_path(env: ScaleBenchEnv) -> Path:
    """Return the concrete recorder path, including any collision suffix."""

    recorder_manager = getattr(env, "recorder_manager", None)
    recorder_config = getattr(recorder_manager, "cfg", None)
    output_dir = getattr(recorder_config, "dataset_export_dir_path", None)
    dataset_filename = getattr(recorder_config, "dataset_filename", None)
    if not isinstance(output_dir, str) or not isinstance(dataset_filename, str):
        raise RuntimeError("could not resolve the active recording dataset path")
    if not dataset_filename.endswith(".hdf5"):
        dataset_filename = f"{dataset_filename}.hdf5"
    return (Path(output_dir) / dataset_filename).resolve()


def _collect_anygrasp_diagnostics(
    env: ScaleBenchEnv,
    task: RigidObjectTask,
    scene_config: SceneConfig,
    robot_config: RobotConfig,
    spec: EpisodeSpec,
    object_name: str,
    arm: Arm,
) -> AnyGraspDiagnostics:
    """Render one real camera frame and classify all returned grasp poses."""

    env.reset(env_ids=(0,), task_layouts=(spec.layout,))
    env.step(env.hold_action())
    context = IsaacLabSkillContext(
        env,
        task,
        scene_config,
        {"left": robot_config, "right": robot_config},
        env_id=0,
    )
    return context.analyze_anygrasp(object_name, arm)


def _log_anygrasp_diagnostics(
    diagnostics: AnyGraspDiagnostics,
) -> None:
    LOGGER.info(
        "points=%d detections=%d valid=%d",
        len(diagnostics.target_points_env_m),
        len(diagnostics.detections),
        len(diagnostics.candidates),
        extra={
            "event": "DIAG",
            "event_fields": {
                "env_id": diagnostics.env_id,
                "object": diagnostics.object_name,
                "arm": diagnostics.arm,
                "target_point_count": len(diagnostics.target_points_env_m),
                "detection_count": len(diagnostics.detections),
                "valid_candidate_count": len(diagnostics.candidates),
            },
        },
    )
    for detection in diagnostics.detections:
        if detection.status.value == "rejected_target_box":
            continue
        LOGGER.info(
            "detection=%d status=%s score=%.4f width_m=%.4f "
            "open_axis_vertical_dot=%.4f table_clearance_m=%.4f",
            detection.detection_index,
            detection.status.value,
            detection.score,
            detection.width_m,
            detection.open_axis_vertical_dot,
            detection.table_clearance_m,
            extra={
                "event": "CANDIDATE",
                "event_fields": {
                    "env_id": diagnostics.env_id,
                    "object": diagnostics.object_name,
                    "arm": diagnostics.arm,
                    "detection_index": detection.detection_index,
                    "status": detection.status.value,
                    "score": detection.score,
                    "width_m": detection.width_m,
                    "approach_axis_env": detection.approach_axis_env,
                    "open_axis_vertical_dot": (detection.open_axis_vertical_dot),
                    "table_clearance_m": detection.table_clearance_m,
                    "anygrasp_tip_position_object_m": (
                        detection.anygrasp_tip_position_object_m
                    ),
                    "tcp_position_object_m": detection.tcp_position_object_m,
                },
            },
        )
    target_box_rejections = sum(
        detection.status.value == "rejected_target_box"
        for detection in diagnostics.detections
    )
    if target_box_rejections:
        LOGGER.info(
            "%d off-target detections omitted from console",
            target_box_rejections,
            extra={
                "event": "DIAG",
                "event_fields": {
                    "env_id": diagnostics.env_id,
                    "object": diagnostics.object_name,
                    "arm": diagnostics.arm,
                    "omitted_target_box_rejection_count": target_box_rejections,
                },
            },
        )


def main() -> int:
    configure_logging(
        console_level=args.log_level,
        console_format=args.log_format,
        jsonl_path=args.log_file,
    )
    if args.log_file is not None:
        LOGGER.info(
            "writing complete DEBUG event stream to %s",
            args.log_file.resolve(),
            extra={
                "event": "OUTPUT",
                "event_fields": {"path": str(args.log_file.resolve())},
            },
        )

    asset_root = PROJECT_ROOT
    scene_config = load_config(
        PROJECT_ROOT / args.scene_config,
        SceneConfig,
        asset_root=asset_root,
    )
    scene_config = SceneConfig.model_validate(
        {**scene_config.model_dump(), "grasp_source": args.grasp_source}
    )
    robot_config = load_config(
        PROJECT_ROOT / args.robot_config,
        RobotConfig,
        asset_root=asset_root,
    )
    camera_profile_path = str((PROJECT_ROOT / args.camera_config).resolve())
    scene_config = scene_config.model_copy(
        update={
            "camera": scene_config.camera.model_copy(
                update={"profile_path": camera_profile_path}
            )
        }
    )
    if robot_config.camera is None:
        raise RuntimeError("demo generation requires mounted robot cameras")
    robot_config = robot_config.model_copy(
        update={
            "camera": robot_config.camera.model_copy(
                update={"profile_path": camera_profile_path}
            )
        }
    )
    environment_config = load_config(args.env_config, EnvironmentConfig)
    if args.task == "single_object_pick_and_place":
        task = SingleObjectPickAndPlace(
            load_config(
                PROJECT_ROOT / "configs/tasks/single_object_pick_and_place.yml",
                SingleObjectPickAndPlaceConfig,
                asset_root=asset_root,
            )
        )
    else:
        task = SortDollsBySize(
            load_config(
                PROJECT_ROOT / "configs/tasks/sort_dolls_by_size.yml",
                SortDollsBySizeConfig,
                asset_root=asset_root,
            )
        )
    placement_context = PlacementContext.from_scene_config(scene_config)
    specs = tuple(
        EpisodeSpec(
            episode_id=f"demo-seed-{seed}",
            task_id=task.task_id,
            seed=seed,
            layout=task.generate_layout(placement_context, seed),
            max_steps=args.max_steps,
        )
        for seed in range(args.base_seed, args.base_seed + args.episodes)
    )
    initial_layouts = (
        tuple(spec.layout for spec in specs[: args.num_envs])
        if len(specs) >= args.num_envs
        else (specs[0].layout,)
    )
    recording_config = (
        None
        if args.record_output is None
        else RecordingConfig(
            output_dir=args.record_output,
            dataset_name=args.dataset_name,
            record_camera_observations=args.record_camera_observations,
        )
    )
    LOGGER.info(
        "creating environment task=%s program=%s num_envs=%d episodes=%d",
        task.task_id,
        args.program,
        args.num_envs,
        args.episodes,
        extra={
            "event": "START",
            "event_fields": {
                "task": task.task_id,
                "program": args.program,
                "grasp_source": scene_config.grasp_source,
                "num_envs": args.num_envs,
                "episode_count": args.episodes,
                "device": str(args.device),
            },
        },
    )
    env = create_env(
        left_robot_config=robot_config,
        right_robot_config=robot_config,
        scene_config=scene_config,
        simulation_config=sim_config,
        environment_config=environment_config,
        recording_config=recording_config,
        task=task,
        layouts=initial_layouts,
        device=args.device,
        num_envs=args.num_envs,
    )
    LOGGER.info(
        "environment ready device=%s recording=%s",
        env.device,
        env.recording_enabled,
        extra={
            "event": "READY",
            "event_fields": {
                "device": str(env.device),
                "recording": env.recording_enabled,
            },
        },
    )

    target_layout = task.target_layout(placement_context)

    default_object_name = (
        task.object_name
        if isinstance(task, SingleObjectPickAndPlace)
        else task.target_object_order[0]
    )
    selected_object_name = args.object_name or default_object_name
    if selected_object_name not in task.metadata:
        raise ValueError(f"unknown --object-name: {selected_object_name!r}")
    if args.program == "expert" and args.object_name is not None:
        raise ValueError("--object-name is not supported with --program expert")

    if args.program == "grasp-diagnostics":
        try:
            diagnostic_arm = _resolve_grasp_arm(
                args.grasp_arm,
                specs[0],
                selected_object_name,
                scene_config,
            )
            diagnostics = _collect_anygrasp_diagnostics(
                env,
                task,
                scene_config,
                robot_config,
                specs[0],
                selected_object_name,
                diagnostic_arm,
            )
            _log_anygrasp_diagnostics(diagnostics)
            if args.diagnostics_output is not None:
                diagnostics_output = args.diagnostics_output.resolve()
                diagnostics.write_json(diagnostics_output)
                LOGGER.info(
                    "wrote diagnostics to %s",
                    diagnostics_output,
                    extra={
                        "event": "OUTPUT",
                        "event_fields": {
                            "output_kind": "anygrasp_diagnostics",
                            "path": str(diagnostics_output),
                        },
                    },
                )
            if args.open3d_bundle is not None:
                AnyGraspOpen3DFrame.from_diagnostics(diagnostics).write(
                    args.open3d_bundle
                )
                LOGGER.info(
                    "wrote Open3D bundle to %s",
                    args.open3d_bundle,
                    extra={
                        "event": "OUTPUT",
                        "event_fields": {
                            "output_kind": "anygrasp_open3d",
                            "path": str(args.open3d_bundle.resolve()),
                        },
                    },
                )
            return 0
        finally:
            env.close()

    def expert_factory(state: EpisodeState) -> Iterator[SkillRequest]:
        if args.program == "expert":
            return task.expert(
                source_layout=state.spec.layout,
                target_layout=target_layout,
            )
        object_name = selected_object_name
        source = state.spec.layout.assets[object_name]
        if args.program == "pick":
            return iter((Pick(object_name, "auto"),))
        target = target_layout.assets[object_name]
        target_object_pose_env = Pose(
            target.position_m,
            source.orientation_xyzw,
        )
        return iter(
            (
                PickAndPlace(
                    object_name,
                    "auto",
                    target_object_pose_env,
                ),
            )
        )

    action_layout = build_command_action_layout(
        env,
        left_robot_config=robot_config,
        right_robot_config=robot_config,
    )
    arm_base_positions_env_m = {
        "left": (
            *scene_config.robot_mounts.left.position_xy_m,
            scene_config.table_top_z_m,
        ),
        "right": (
            *scene_config.robot_mounts.right.position_xy_m,
            scene_config.table_top_z_m,
        ),
    }
    curobo_planners = build_curobo_motion_planners(
        left_robot_config=robot_config,
        right_robot_config=robot_config,
        scene_config=scene_config,
        device=env.device,
        dtype=env.hold_action().dtype,
        interpolation_dt_s=float(env.step_dt),
        visualize=args.visualize_curobo,
        env_origin_world_m=tuple(
            float(value) for value in env.scene.env_origins[0].tolist()
        ),
    )

    def planner_factory(state: EpisodeState) -> OperationSkillPlanner:
        del state
        return OperationSkillPlanner(
            curobo_planners,
            arm_base_positions_env_m,
            scene_config.manipulation.lift_height_m,
            gripper_open_positions={
                arm: robot_config.gripper.open_positions for arm in ("left", "right")
            },
        )

    executor = CommandExecutor(env, action_layout)

    def context_factory(state: EpisodeState) -> SkillContext:
        return IsaacLabSkillContext(
            env,
            task,
            scene_config,
            {"left": robot_config, "right": robot_config},
            env_id=state.env_id,
        )

    runner = DemoGenerationRunner(
        env,
        executor,
        expert_factory=expert_factory,
        planner_factory=planner_factory,
        context_factory=context_factory,
    )

    valid = True
    replay_request = None
    try:
        result = BenchmarkScheduler(specs).run(runner)
        expected_batches = (len(specs) + args.num_envs - 1) // args.num_envs
        valid &= result.batch_count == expected_batches
        for index, episode in enumerate(result.episodes.values()):
            slot = index % args.num_envs
            episode_valid = (
                episode.termination.reason
                in {
                    TerminationReason.CONTROLLER_FINISHED,
                    TerminationReason.GOAL_REACHED,
                }
                and episode.steps > 0
                and (args.program != "expert" or episode.success)
            )
            valid &= episode_valid
            episode_fields: dict[str, object] = {
                "episode_id": episode.spec.episode_id,
                "env_id": slot,
                "seed": episode.spec.seed,
                "step_count": episode.steps,
                "success": episode.success,
                "progress": episode.evaluation.progress,
                "termination": episode.termination.reason.value,
            }
            if episode.termination.message is not None:
                episode_fields["termination_message"] = episode.termination.message
            LOGGER.log(
                logging.INFO if episode_valid else logging.WARNING,
                "seed=%d steps=%d %s",
                episode.spec.seed,
                episode.steps,
                episode.termination.reason.value,
                extra={
                    "event": "EPISODE",
                    "event_fields": episode_fields,
                },
            )
            for status in getattr(episode.evaluation, "statuses", ()):
                LOGGER.debug(
                    "placed=%s xy_error_m=%.4f z_error_m=%.4f upright_error_rad=%.4f",
                    status.placed,
                    status.position_error_m,
                    status.height_error_m,
                    status.upright_error_rad,
                    extra={
                        "event": "OBJECT",
                        "event_fields": {
                            "episode_id": episode.spec.episode_id,
                            "env_id": slot,
                            "object": status.object_name,
                            "placed": status.placed,
                            "object_position_env_m": status.position_m,
                            "target_position_env_m": status.target_position_m,
                            "xy_error_m": status.position_error_m,
                            "z_error_m": status.height_error_m,
                            "upright_error_rad": status.upright_error_rad,
                        },
                    },
                )
        success_count = sum(episode.success for episode in result.episodes.values())
        success_rate = success_count / len(result.episodes)
        LOGGER.log(
            logging.INFO if valid else logging.WARNING,
            "%s/%s success=%d/%d rate=%.3f",
            task.task_id,
            args.program,
            success_count,
            len(result.episodes),
            success_rate,
            extra={
                "event": "SUMMARY",
                "event_fields": {
                    "task": task.task_id,
                    "program": args.program,
                    "episode_count": len(result.episodes),
                    "success_count": success_count,
                    "success_rate": success_rate,
                    "batch_count": result.batch_count,
                    "expected_batch_count": expected_batches,
                    "recording": env.recording_enabled,
                    "valid": valid,
                },
            },
        )
        if args.visualize_curobo:
            curobo_planners["left"].browse_captured_stages()
        replay_request = (
            GuiReplayRequest(
                dataset_path=_recording_dataset_path(env),
                episode_ids=tuple(spec.episode_id for spec in specs),
                task_id=task.task_id,
                scene_config=(PROJECT_ROOT / args.scene_config).resolve(),
                robot_config=(PROJECT_ROOT / args.robot_config).resolve(),
                camera_config=(PROJECT_ROOT / args.camera_config).resolve(),
                sim_config=args.sim_config.resolve(),
                env_config=args.env_config.resolve(),
                device=str(args.device),
                rendering_mode=args.rendering_mode,
                deterministic=args.deterministic,
            )
            if args.replay_manifest is not None
            else None
        )
    finally:
        env.close()
    if replay_request is not None:
        replay_request.write(args.replay_manifest)
    return 0 if valid else 1


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except BaseException:
        LOGGER.exception(
            "demo generation failed",
            extra={"event": "ERROR", "event_fields": {}},
        )
        exit_code = 1
    finally:
        try:
            simulation_app.close(exit_code=exit_code)
        except SystemExit:
            # Older Isaac Sim builds may use SystemExit during shutdown.
            pass
    raise SystemExit(exit_code)
