"""Assemble the real CuRobo/Isaac skill execution path."""

from collections.abc import Sequence

from scale_bench.runtime import (
    BenchmarkScheduler,
    DemoGenerationRunner,
    EpisodeSpec,
    EpisodeState,
)
from scale_bench.runtime.demo_generation import ExpertFactory
from scale_bench.runtime.scheduler import BenchmarkRunResult
from scale_bench.runtime.task_run import TaskRun
from scale_bench.skills import CommandExecutor, OperationSkillPlanner, SkillContext

from .command_adapter import build_command_action_layout
from .curobo_planner import build_curobo_motion_planners
from .environment import ScaleBenchEnv
from .skill_context import IsaacLabSkillContext


def run_skill_episodes(
    env: ScaleBenchEnv,
    run: TaskRun,
    specs: Sequence[EpisodeSpec],
    *,
    expert_factory: ExpertFactory,
    visualize_curobo: bool,
) -> BenchmarkRunResult:
    action_layout = build_command_action_layout(
        env,
        left_robot_config=run.robot,
        right_robot_config=run.robot,
    )
    arm_base_positions_env_m = {
        arm: (*mount.position_xy_m, run.scene.table_top_z_m)
        for arm, mount in (
            ("left", run.scene.robot_mounts.left),
            ("right", run.scene.robot_mounts.right),
        )
    }
    curobo_planners = build_curobo_motion_planners(
        left_robot_config=run.robot,
        right_robot_config=run.robot,
        scene_config=run.scene,
        device=env.device,
        dtype=env.hold_action().dtype,
        interpolation_dt_s=float(env.step_dt),
        visualize=visualize_curobo,
        env_origin_world_m=tuple(
            float(value) for value in env.scene.env_origins[0].tolist()
        ),
    )

    def planner_factory(state: EpisodeState) -> OperationSkillPlanner:
        return OperationSkillPlanner(
            curobo_planners,
            arm_base_positions_env_m,
            run.scene.manipulation.lift_height_m,
            gripper_open_positions={
                arm: run.robot.gripper.open_positions for arm in ("left", "right")
            },
        )

    def context_factory(state: EpisodeState) -> SkillContext:
        return IsaacLabSkillContext(
            env,
            run.task,
            run.scene,
            {"left": run.robot, "right": run.robot},
            env_id=state.env_id,
        )

    runner = DemoGenerationRunner(
        env,
        CommandExecutor(env, action_layout),
        expert_factory=expert_factory,
        planner_factory=planner_factory,
        context_factory=context_factory,
    )
    result = BenchmarkScheduler(specs).run(runner)
    if visualize_curobo:
        curobo_planners["left"].browse_captured_stages()
    return result
