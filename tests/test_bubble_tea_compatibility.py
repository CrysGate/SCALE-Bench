"""Regression checks that do not start Isaac or require a GPU."""

import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

from scale_bench.config.models.robot import TcpConfig
from scale_bench.isaaclab.runtime.grasp_candidates import IsaacLabGraspCandidates
from scale_bench.runtime.asset_grasps import load_asset_grasps
from scale_bench.skills.geometry import compose_pose, inverse_pose, rotate_vector_xyzw
from scale_bench.skills.models import Pose
from scale_bench.tasks.common.fixed_target import FixedTargetRigidObjectTask
from scale_bench.tasks.common.layout import AssetPlacement, TaskLayout
from scale_bench.tasks.bubble_tea_cup_800g_pick_and_place.task import BubbleTeaCup800gPickAndPlace


@pytest.fixture
def legacy_grasps(tmp_path, monkeypatch):
    from grasp_data_gen import results

    object_path = tmp_path / "cup.usd"
    robot_path = tmp_path / "robot.usd"
    object_path.touch()
    robot_path.touch()
    path = tmp_path / "successful_grasps.yaml"
    path.write_text("grasps: []\n")
    old_tcp = Pose((-0.02, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    grasp_pose = Pose((0.1, 0.2, 0.3), (0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5)))
    grasp = SimpleNamespace(
        position_object_m=grasp_pose.position_m,
        orientation_object_xyzw=grasp_pose.orientation_xyzw,
        approach_axis_tcp=(1.0, 0.0, 0.0), score=0.9, candidate_id=51,
        evaluation=SimpleNamespace(joint_positions={"finger": 0.04}),
    )
    data = SimpleNamespace(
        object_usd=object_path, robot_usd=robot_path,
        tcp_definition=SimpleNamespace(
            parent_frame="gripper_center", offset_in_parent_m=old_tcp.position_m,
            tcp_orientation_parent_xyzw=old_tcp.orientation_xyzw,
        ),
        tabletop_filter={"approach_distance_m": 0.1}, grasps=[grasp],
    )
    monkeypatch.setattr(results, "load_grasp_file", lambda _: data)
    robot = SimpleNamespace(
        name="piper", usd_path=robot_path,
        kinematics=SimpleNamespace(tcp=TcpConfig(
            parent_frame="gripper_center", position_m=(-0.04, 0, 0),
            orientation_xyzw=(0, 0, 0, 1),
        )),
        gripper=SimpleNamespace(joint_names=("finger",)),
    )
    return path, object_path, robot, data, old_tcp, grasp_pose


@pytest.mark.parametrize("rotate_tcp", [False, True])
def test_legacy_tcp_conversion_preserves_physical_gripper_pose(legacy_grasps, rotate_tcp):
    path, asset, robot, data, old_tcp, original = legacy_grasps
    if rotate_tcp:
        robot.kinematics.tcp = robot.kinematics.tcp.model_copy(update={
            "orientation_xyzw": (0, 0, math.sqrt(0.5), math.sqrt(0.5)),
        })
    candidate, = load_asset_grasps(asset, robot, grasp_file=path)
    new_tcp = Pose(robot.kinematics.tcp.position_m, robot.kinematics.tcp.orientation_xyzw)
    old_parent = compose_pose(original, inverse_pose(old_tcp))
    new_parent = compose_pose(candidate.tcp_pose_object, inverse_pose(new_tcp))
    assert new_parent.position_m == pytest.approx(old_parent.position_m)
    assert new_parent.orientation_xyzw == pytest.approx(old_parent.orientation_xyzw)
    assert rotate_vector_xyzw(candidate.tcp_pose_object.orientation_xyzw,
                              candidate.approach_axis_tcp) == pytest.approx(
        rotate_vector_xyzw(original.orientation_xyzw, data.grasps[0].approach_axis_tcp)
    )
    assert candidate.candidate_id == 51
    assert candidate.gripper_joint_positions == {"finger": 0.04}
    assert candidate.score == 0.9


@pytest.mark.parametrize("failure", ["object", "robot", "parent", "joints", "empty", "distance"])
def test_incompatible_grasp_export_is_rejected(legacy_grasps, failure, tmp_path):
    path, asset, robot, data, *_ = legacy_grasps
    other = tmp_path / "other.usd"
    other.touch()
    if failure == "object":
        data.object_usd = other
    elif failure == "robot":
        data.robot_usd = other
    elif failure == "parent":
        data.tcp_definition.parent_frame = "different_frame"
    elif failure == "joints":
        data.grasps[0].evaluation.joint_positions = {"wrong": 0.04}
    elif failure == "empty":
        data.grasps = []
    else:
        data.tabletop_filter["approach_distance_m"] = -0.1
    with pytest.raises(ValueError):
        load_asset_grasps(asset, robot, grasp_file=path)


def test_compact_grasps_and_distractors_without_annotations(legacy_grasps):
    _, asset, robot, *_ = legacy_grasps
    document = {
        "object": "cup", "position_unit": "m",
        "pose_layout": ["x", "y", "z", "qx", "qy", "qz", "qw"],
        "tcp": robot.kinematics.tcp.model_dump(), "approach_distance_m": 0.1,
        "candidates": [{
            "candidate_id": 3, "robot": "piper",
            "pose_object_tcp_xyz_xyzw": [0, 0, 0, 0, 0, 0, 1],
            "approach_axis_object": [1, 0, 0], "closed_joint_positions_m": {"finger": 0.04},
        }],
    }
    asset.with_name("grasps.yaml").write_text(yaml.safe_dump(document))
    task = SimpleNamespace(assets={
        "cup": SimpleNamespace(usd_path=asset),
        "distractor": SimpleNamespace(usd_path=asset.parent / "missing" / "cup.usd"),
    })
    service = IsaacLabGraspCandidates(task, {"left": robot, "right": robot})
    assert service.candidates("cup", "right")[0].candidate_id == 3
    # Repeated observations use the cached candidates.
    asset.with_name("grasps.yaml").unlink()
    assert service.candidates("cup", "right")[0].candidate_id == 3


def test_explicit_legacy_file_is_used_for_target(legacy_grasps):
    path, asset, robot, *_ = legacy_grasps
    task = SimpleNamespace(assets={"cup": SimpleNamespace(usd_path=asset)})
    service = IsaacLabGraspCandidates(
        task, {"left": robot, "right": robot}, grasp_files={"cup": path},
    )
    assert service.candidates("cup", "right")[0].candidate_id == 51


def test_layout_sampling_retry_keeps_requested_seed(monkeypatch):
    task = object.__new__(BubbleTeaCup800gPickAndPlace)
    task._config = SimpleNamespace(target_source_y_max_m=0.04)
    task._target_name = "cup"
    attempts = []

    def sample(self, context, seed):
        attempts.append(seed)
        if len(attempts) == 1:
            raise RuntimeError("sampling exhausted")
        return TaskLayout(task_id=task.TASK_ID, seed=seed, assets={
            "cup": AssetPlacement(position_m=(0, 0, 1), orientation_xyzw=(0, 0, 0, 1)),
        })

    monkeypatch.setattr(FixedTargetRigidObjectTask, "generate_layout", sample)
    layout = task.generate_layout(None, 7)
    assert attempts == [7, 8]
    assert layout.seed == 7


@pytest.fixture
def script():
    path = Path(__file__).resolve().parents[1] / "scripts/run_bubble_tea_demo.py"
    spec = importlib.util.spec_from_file_location("bubble_demo_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_seed_limit_and_camera_flag(script, tmp_path):
    grasps = tmp_path / "grasps.yaml"
    grasps.touch()
    args = script.parse_args([
        "--grasp-file", str(grasps), "--seeds", "7", "9", "11",
        "--success-count", "2", "--max-attempts", "2", "--record-cameras",
    ])
    assert args.requested_seeds == [7, 9]
    assert args.enable_cameras
    with pytest.raises(SystemExit) as error:
        script.parse_args(["--grasp-file", str(grasps), "--seeds", "7", "7"])
    assert error.value.code == 2


@pytest.mark.parametrize("successes, expected, fails", [
    ([False, True, True, True], [0, 1, 2], False),
    ([False, False, False, False], [0, 1, 2, 3], True),
])
def test_collection_retries_and_stops_at_success_goal(script, monkeypatch, successes, expected, fails):
    import time

    context = SimpleNamespace(snapshot=lambda: SimpleNamespace(objects=()))
    monkeypatch.setitem(sys.modules, "scale_bench.isaaclab.runtime.skill_context",
                        SimpleNamespace(IsaacLabSkillContext=lambda *a, **kw: context))
    monkeypatch.setattr(script.PlacementContext, "from_scene_config", lambda _: None)
    task = SimpleNamespace(task_id="cup_task", target_name="cup")
    task.resolve_layout = lambda _, seed: TaskLayout(
        task_id="cup_task", seed=seed, assets={
            "cup": AssetPlacement(position_m=(0, 0, 1), orientation_xyzw=(0, 0, 0, 1)),
        },
    )
    attempts = []

    def run_batch(states):
        state, = states
        seed = state.spec.seed
        attempts.append(seed)
        return {state.spec.episode_id: SimpleNamespace(
            success=successes[seed], steps=1,
            termination=SimpleNamespace(reason="finished"),
            evaluation=SimpleNamespace(metrics={}),
        )}

    args = SimpleNamespace(requested_seeds=[0, 1, 2, 3], success_count=2,
                           max_steps=10, grasp_file=Path("grasps.yaml"), record_dir=Path("outputs"))
    call = lambda: script._collect(args, None, SimpleNamespace(run_batch=run_batch),
                                   task, None, {}, time.perf_counter())
    if fails:
        with pytest.raises(RuntimeError, match="after 4 attempts"):
            call()
    else:
        call()
    assert attempts == expected


@pytest.mark.parametrize("raise_in_batch", [False, True])
def test_shared_runner_passes_new_interfaces_and_closes_pool(monkeypatch, raise_in_batch):
    """Exercise assembly and ownership while substituting GPU/Isaac backends."""
    from unittest.mock import Mock

    prefix = "scale_bench.isaaclab.runtime."
    pool = SimpleNamespace(planners=[{"left": object(), "right": object()}],
                           flush=Mock(), close=Mock())
    context_factory = Mock(return_value="context")
    monkeypatch.setitem(sys.modules, prefix + "command_adapter",
                        SimpleNamespace(build_command_action_layout=Mock(return_value="actions")))
    monkeypatch.setitem(sys.modules, prefix + "curobo_parallel", SimpleNamespace(
        CuroboPlanningPool=Mock(return_value=pool),
        QueuedCuroboMotionPlanner=lambda planner, pool, env_id: planner,
        QueuedSkillContext=lambda context, pool: context,
    ))
    monkeypatch.setitem(sys.modules, prefix + "curobo_planner", SimpleNamespace(
        CuroboMotionPlanner=object, build_curobo_motion_planners=Mock(),
    ))
    monkeypatch.setitem(sys.modules, prefix + "environment", SimpleNamespace(ScaleBenchEnv=object))
    monkeypatch.setitem(sys.modules, prefix + "skill_context",
                        SimpleNamespace(IsaacLabSkillContext=context_factory))
    path = Path(__file__).resolve().parents[1] / "src/scale_bench/isaaclab/runtime/skill_runner.py"
    spec = importlib.util.spec_from_file_location(prefix + "runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runner_factory = Mock()
    monkeypatch.setattr(module, "DemoGenerationRunner", runner_factory)
    monkeypatch.setattr(module, "CommandExecutor", Mock(return_value="executor"))
    profiles = {
        arm: SimpleNamespace(initial_joint_positions={"joint": position},
                             kinematics=SimpleNamespace(arm_joint_names=("joint",)),
                             gripper=SimpleNamespace(open_positions={"finger": 0.05}))
        for arm, position in [("left", 0.1), ("right", 0.2)]
    }
    scene = SimpleNamespace(
        table_top_z_m=0.75,
        robot_mounts=SimpleNamespace(left=SimpleNamespace(position_xy_m=(-0.3, 0)),
                                    right=SimpleNamespace(position_xy_m=(0.3, 0))),
        manipulation=SimpleNamespace(planner_attempts=3),
    )
    run = SimpleNamespace(scene=scene, task=object(), robot=profiles["left"])
    env = SimpleNamespace(num_envs=1, device="cuda:0")
    overrides = {"cup": Path("successful_grasps.yaml")}
    try:
        with module.open_skill_runner(env, run, expert_factory=Mock(),
                                      robot_configs=profiles, grasp_files=overrides) as runner:
            assert runner is runner_factory.return_value
            kwargs = runner_factory.call_args.kwargs
            assert kwargs["flush_planning"] == pool.flush
            assert kwargs["skill_settings"].safe_joint_positions == {"left": (0.1,), "right": (0.2,)}
            assert kwargs["context_factory"](SimpleNamespace(env_id=0)) == "context"
            assert context_factory.call_args.kwargs["grasp_files"] == overrides
            assert kwargs["planner_factory"](SimpleNamespace(env_id=0))._max_attempts == 3
            if raise_in_batch:
                raise RuntimeError("batch failed")
    except RuntimeError as error:
        assert raise_in_batch and str(error) == "batch failed"
    pool.close.assert_called_once()


@pytest.mark.parametrize("vertical", [False, True])
def test_release_retreat_keeps_default_and_supports_vertical_clearance(monkeypatch, vertical):
    import asyncio
    import importlib
    from scale_bench.skills.models import PickAndPlace

    module = importlib.import_module('scale_bench.skills.pick_and_place')
    tcp = Pose((0.1, 0.2, 0.8), (0, 0, 0, 1))
    snapshot = SimpleNamespace(robot=lambda arm: SimpleNamespace(tcp_pose_env=tcp))
    monkeypatch.setattr(module, 'contact_scene', lambda *args: 'scene')
    motions = []

    async def free(*args):
        motions.append(('free', args))
        yield 'command'

    async def linear(*args):
        motions.append(('linear', args))
        yield 'command'

    session = SimpleNamespace(
        context=SimpleNamespace(snapshot=lambda: snapshot),
        config=SimpleNamespace(retreat_distance_m=0.06),
        move_free=free, move_linear=linear,
    )
    request = PickAndPlace('cup', 'right', tcp,
                           retreat_axis_env=(0, 0, 1) if vertical else None,
                           retreat_distance_m=0.12 if vertical else None)

    async def run():
        return [command async for command in module._release_retreat(
            session, request, 'right', (1, 0, 0), 'retreat')]

    assert asyncio.run(run()) == ['command']
    kind, args = motions[0]
    assert kind == ('linear' if vertical else 'free')
    assert args[1].position_m == pytest.approx((0.1, 0.2, 0.92) if vertical else (0.04, 0.2, 0.8))
    assert args[1].orientation_xyzw == tcp.orientation_xyzw


@pytest.mark.parametrize('kwargs', [
    {'retreat_axis_env': (0, 0, 0)}, {'retreat_axis_env': (0, 0, 2)},
    {'retreat_distance_m': -0.1}, {'retreat_distance_m': float('nan')},
])
def test_invalid_retreat_request_rejected(kwargs):
    from scale_bench.skills.models import PickAndPlace
    with pytest.raises(ValueError):
        PickAndPlace('cup', 'right', Pose((0, 0, 0), (0, 0, 0, 1)), **kwargs)
