"""Capture and report AnyGrasp evidence without executing a skill."""

import logging

from scale_bench.config.models.scene import SceneConfig
from scale_bench.runtime import EpisodeSpec
from scale_bench.runtime.task_run import TaskRun
from scale_bench.skills import Arm, ArmSelection

from .anygrasp_diagnostics import AnyGraspDiagnostics
from .skill_context import IsaacLabSkillContext

LOGGER = logging.getLogger(__name__)


def collect_grasp_diagnostics(
    run: TaskRun,
    spec: EpisodeSpec,
    object_name: str,
    arm_selection: ArmSelection,
) -> AnyGraspDiagnostics:
    arm = _resolve_grasp_arm(arm_selection, spec, object_name, run.scene)
    with run.open_environment((spec,), num_envs=1, recording=None) as env:
        env.reset(env_ids=(0,), task_layouts=(spec.layout,))
        env.step(env.hold_action())
        context = IsaacLabSkillContext(
            env,
            run.task,
            run.scene,
            {"left": run.robot, "right": run.robot},
            env_id=0,
        )
        diagnostics = context.analyze_anygrasp(object_name, arm)
        _log_anygrasp_diagnostics(diagnostics)
        return diagnostics


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
