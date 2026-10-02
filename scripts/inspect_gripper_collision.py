"""Inspect live CuRobo spheres while actuating grippers and executing plans."""

import argparse
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scale_bench.cli.simulation import add_simulation_arguments, run_simulation
from scale_bench.runtime.task_run import TaskRun
from scale_bench.skills.models import Arm


def inspect(run: TaskRun, validate: bool) -> int:
    import numpy as np
    import torch
    from scipy.spatial.transform import Rotation

    from scale_bench.isaaclab.runtime.command_adapter import build_command_action_layout
    from scale_bench.isaaclab.runtime.curobo_planner import TCP_FRAME, build_curobo_motion_planners
    from scale_bench.isaaclab.runtime.skill_context import IsaacLabSkillContext
    from scale_bench.skills.context import JointState
    from scale_bench.skills.errors import PlanningError
    from scale_bench.skills.geometry import compose_pose
    from scale_bench.skills.models import Pose
    from scale_bench.skills.scene import world_scene

    specs = run.episode_specs(base_seed=100, episodes=1, max_steps=1000000)
    with run.open_environment(specs, num_envs=1, recording=None) as env:
        env.reset()
        env.sim.set_camera_view((1.35, 1.25, 1.55), (0.0, -0.05, 0.78))
        context = IsaacLabSkillContext(env, run.task, run.scene, run.robot, env_id=0)
        snapshot = context.snapshot()
        layout = build_command_action_layout(env, robot_config=run.robot)
        action = env.hold_action().clone()
        planners = build_curobo_motion_planners(
            robot_config=run.robot, scene_config=run.scene,
            scene_cuboid_count=1 + len(snapshot.camera_stand) + len(snapshot.objects),
            device=env.device, dtype=action.dtype, interpolation_dt_s=float(env.step_dt),
            visualize=False, env_origin_world_m=tuple(env.scene.env_origins[0].tolist()),
        )
        initial_joint_states = {
            arm: snapshot.robot(arm).joints.positions.clone() for arm in ("left", "right")
        }
        pending_plans: list[Arm] = []
        if not validate:
            import omni.kit.app
            import omni.ui as ui
            import isaaclab.sim as sim_utils
            from isaaclab.markers import VisualizationMarkers, VisualizationMarkersCfg

            app = omni.kit.app.get_app()
            markers = VisualizationMarkers(VisualizationMarkersCfg(
                prim_path="/Visuals/GripperInspection",
                markers={
                    "robot": sim_utils.SphereCfg(
                        radius=1.0,
                        visual_material=sim_utils.PreviewSurfaceCfg(
                            diffuse_color=(0.1, 0.65, 1.0), opacity=0.35,
                        ),
                    ),
                    "fingers": sim_utils.SphereCfg(
                        radius=1.0,
                        visual_material=sim_utils.PreviewSurfaceCfg(
                            diffuse_color=(1.0, 0.4, 0.05), opacity=0.55,
                        ),
                    ),
                },
            ))
            window = ui.Window(f"{run.robot.name}: CuRobo gripper inspection", width=440, height=265)
            with window.frame:
                with ui.VStack(spacing=6):
                    ui.Label("Blue: robot spheres. Orange: finger spheres.", height=22)
                    with ui.VStack(spacing=6) as controls:
                        ui.Label("Closure: 0 = open, 1 = closed (both arms)", height=22)
                        closure_model = ui.SimpleFloatModel(0.0)
                        ui.FloatSlider(model=closure_model, min=0.0, max=1.0, height=22)
                        with ui.HStack(height=26):
                            for text, fraction in (("Open", 0.0), ("Half", 0.5), ("Closed", 1.0)):
                                ui.Button(text, clicked_fn=lambda value=fraction: closure_model.set_value(value))
                        with ui.HStack(height=26):
                            ui.Button("Plan + move left", clicked_fn=lambda: pending_plans.append("left"))
                            ui.Button("Plan + move right", clicked_fn=lambda: pending_plans.append("right"))
                        with ui.HStack(height=22):
                            visible_model = ui.SimpleBoolModel(True)
                            ui.CheckBox(model=visible_model, width=24)
                            ui.Label("Show collision spheres")
                    status = ui.Label("Ready", height=40, word_wrap=True)
                    result_label = ui.Label("", height=40, word_wrap=True)

        def set_closure(fraction: float) -> None:
            targets = [
                run.robot.gripper.open_positions[name] * (1.0 - fraction)
                + run.robot.gripper.closed_positions[name] * fraction
                for name in run.robot.gripper.command_joint_names
            ]
            for start, stop in (layout.left_gripper, layout.right_gripper):
                action[:, start:stop] = action.new_tensor(targets)

        def update_spheres() -> str:
            snapshot = context.snapshot()
            positions_world_m = []
            radii_m = []
            colors = []
            labels = []
            for arm in ("left", "right"):
                robot_state = snapshot.robot(arm)
                planner = planners[arm]
                # Use the planning backend and its measured-state synchronization,
                # including all mimic joints; do not build a separate display model.
                planner._sync_gripper(robot_state.gripper_joint_positions)
                fk = planner._planner.compute_kinematics(planner._joint_state(robot_state.joints.positions))
                spheres_base_m = fk.robot_spheres.reshape(-1, 4)
                valid = spheres_base_m[:, 3] > 0.0
                finger_indices = torch.cat([
                    planner._planner.kinematics.config.kinematics_config.get_sphere_index_from_link_name(name)
                    for name in run.robot.gripper.finger_body_names
                ]).long()
                marker_indices = torch.zeros(len(spheres_base_m), device=env.device, dtype=torch.int32)
                marker_indices[finger_indices] = 1
                sphere_positions_env_m = planner._curobo_pose(planner._arm_base_pose_env).transform_points(
                    spheres_base_m[:, :3].contiguous()
                ).reshape(-1, 3)
                positions_world_m.append((sphere_positions_env_m + env.scene.env_origins[0])[valid])
                radii_m.append(spheres_base_m[valid, 3:4].expand(-1, 3))
                colors.append(marker_indices[valid])
                tcp_pose_base = fk.tool_poses.get_link_pose(TCP_FRAME)
                tcp_orientation_base_wxyz = tcp_pose_base.quaternion.reshape(-1).tolist()
                tcp_pose_env = compose_pose(planner._arm_base_pose_env, Pose(
                    tuple(tcp_pose_base.position.reshape(-1).tolist()),
                    tuple(tcp_orientation_base_wxyz[1:] + tcp_orientation_base_wxyz[:1]),
                ))
                position_error_m = np.linalg.norm(np.array(tcp_pose_env.position_m) - robot_state.tcp_pose_env.position_m)
                orientation_error_rad = (
                    Rotation.from_quat(tcp_pose_env.orientation_xyzw).inv()
                    * Rotation.from_quat(robot_state.tcp_pose_env.orientation_xyzw)
                ).magnitude()
                if position_error_m > 0.001 or orientation_error_rad > 0.001:
                    raise RuntimeError(f"{arm} TCP mismatch: {position_error_m:g} m, {orientation_error_rad:g} rad")
                aperture_mm = run.robot.gripper.aperture_m(robot_state.gripper_joint_positions) * 1000
                labels.append(f"{arm}: {aperture_mm:.2f} mm")
            if not validate:
                markers.set_visibility(visible_model.as_bool)
                markers.visualize(
                    translations=torch.cat(positions_world_m), scales=torch.cat(radii_m),
                    marker_indices=torch.cat(colors),
                )
            return " | ".join(labels)

        def step() -> str:
            started = time.monotonic()
            env.step(action)
            label = update_spheres()
            if not validate:
                time.sleep(max(0.0, float(env.step_dt) - (time.monotonic() - started)))
            return label

        def plan_and_move(arm: Arm) -> None:
            for _ in range(round(2.0 / float(env.step_dt))):
                step()
            snapshot = context.snapshot()
            robot_state = snapshot.robot(arm)
            target_joint_state = initial_joint_states[arm].clone()
            if abs(float(robot_state.joints.positions[-1] - target_joint_state[-1])) < 0.05:
                target_joint_state[-1] += 0.1
            # CuRobo may capture CUDA graphs here; PhysX/Fabric rendering must
            # finish before planning and resume only after the solve returns.
            trajectory = planners[arm].plan_joints(
                robot_state.joints, JointState(target_joint_state),
                world_scene(snapshot, arm), f"inspect_{arm}",
            )
            start, stop = layout.left_arm if arm == "left" else layout.right_arm
            for joint_state in trajectory.positions:
                action[:, start:stop] = joint_state
                step()
            for _ in range(round(1.0 / float(env.step_dt))):
                label = step()
            error_rad = float((context.snapshot().robot(arm).joints.positions - target_joint_state).abs().max())
            if error_rad > 0.02:
                raise RuntimeError(f"{arm} trajectory execution error: {error_rad:g} rad")
            print(f"{run.robot.name} {arm}: {len(trajectory.positions)} waypoints, "
                  f"joint error {error_rad:.6g} rad; {label}", flush=True)

        failures: list[str] = []
        if validate:
            for fraction in (0.0, 0.5, 1.0):
                set_closure(fraction)
                for arm in ("left", "right"):
                    try:
                        plan_and_move(arm)
                    except PlanningError as error:
                        message = f"{run.robot.name} {arm} closure={fraction}: {error}"
                        failures.append(message)
                        print(message, flush=True)
            outcome = "FAILED" if failures else "PASSED"
            print(f"{run.robot.name}: GRIPPER_COLLISION_INSPECTION_{outcome}", flush=True)
        else:
            print(f"{run.robot.name}: interactive collision viewer ready", flush=True)
            while app.is_running() and window.visible:
                set_closure(closure_model.as_float)
                status.text = step()
                if pending_plans:
                    arm = pending_plans.pop(0)
                    controls.enabled = False
                    status.text = f"Planning and executing {arm} arm..."
                    try:
                        plan_and_move(arm)
                        result_label.text = f"{arm}: planning and execution passed"
                    except PlanningError as error:
                        print(f"Planning failed: {error}", flush=True)
                        result_label.text = f"Planning failed: {error}"
                        pending_plans.clear()
                    finally:
                        controls.enabled = True
            markers.set_visibility(False)
            window.visible = False
    return int(bool(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_simulation_arguments(parser, PROJECT_ROOT)
    parser.add_argument("--validate", action="store_true", help="Check open/half/closed states and both arms headlessly, then exit.")
    parser.set_defaults(enable_cameras=False, log_level="INFO")
    args = parser.parse_args()
    if args.validate:
        args.headless = True
        args.visualizer = ["none"]
    else:
        if args.headless or (args.visualizer_explicit and "kit" not in (args.visualizer or ())):
            parser.error("Interactive inspection requires --viz kit; use --validate for headless checks.")
        args.visualizer = ["kit"]
        os.environ["HEADLESS"] = "0"
    args.visualizer_explicit = True
    return run_simulation(args, PROJECT_ROOT, lambda run: inspect(run, args.validate))


if __name__ == "__main__":
    raise SystemExit(main())
