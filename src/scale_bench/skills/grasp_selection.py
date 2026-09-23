"""Candidate ranking and IK-only feasibility, independent of trajectory planning."""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

from .context import GraspCandidate
from .errors import FailureCode, PlanningError
from .geometry import compose_pose, relative_pose
from .manipulation_geometry import (
    camera_side_up_dot,
    grasp_geometry_cost,
    parallel_jaw_grasp_poses,
    placement_tcp_pose_env,
    raised_tcp_pose_env,
    target_object_orientations_env_xyzw,
)
from .models import Arm, ArmSelection, Pose
from .scene import contact_scene, held_object_scene
from .session import SkillSession

LOGGER = logging.getLogger(__name__)


def log_candidate(selected: "SelectedGrasp", result: str, stage: str, reason: str) -> None:
    LOGGER.log(
        logging.INFO if result == "SELECTED" else logging.DEBUG,
        "candidate=%d %s at %s", selected.candidate.candidate_id, result, stage,
        extra={"event": "GRASP-CANDIDATE", "event_fields": {
            "object": selected.object_name, "arm": selected.arm,
            "candidate_id": selected.candidate.candidate_id,
            "score": selected.candidate.score, "result": result,
            "stage": stage, "reason": reason,
        }},
    )


@dataclass(frozen=True, slots=True)
class SelectedGrasp:
    object_name: str
    arm: Arm
    candidate: GraspCandidate


def select_arm(session: SkillSession, object_name: str, selection: ArmSelection) -> Arm:
    if selection != "auto":
        return selection
    object_position_env_m = session.context.snapshot().object(object_name).pose_env.position_m
    return min(
        session.settings.arm_base_positions_env_m,
        key=lambda arm: sum(
            (a - b) ** 2 for a, b in zip(
                object_position_env_m, session.settings.arm_base_positions_env_m[arm], strict=True,
            )
        ),
    )


async def feasible_grasps(
    session: SkillSession, object_name: str, arm: Arm,
    candidates: tuple[GraspCandidate, ...], target_object_pose_env: Pose | None,
    excluded: set[tuple[int, int]],
) -> AsyncIterator[tuple[tuple[int, int], SelectedGrasp]]:
    """Pick-only passes None; pick-and-place supplies its destination for IK screening.

    Only IK configurations are discarded. Every trajectory is planned by the
    executing skill after selection, from the current measured state.
    """
    snapshot = session.context.snapshot()
    source_object = snapshot.object(object_name)
    robot = snapshot.robot(arm)
    base_position_env_m = session.settings.arm_base_positions_env_m[arm]
    for candidate in sorted(candidates, key=lambda item: (
        grasp_geometry_cost(item, source_object.pose_env, base_position_env_m), -item.score,
    )):
        for variant, grasp_tcp_pose_env in enumerate(
            parallel_jaw_grasp_poses(source_object.pose_env, candidate),
        ):
            key = (candidate.candidate_id, variant)
            if key in excluded or camera_side_up_dot(
                grasp_tcp_pose_env, robot.camera_position_tcp_m, candidate.approach_axis_tcp,
            ) <= 0.0:
                continue
            tcp_pose_object = relative_pose(source_object.pose_env, grasp_tcp_pose_env)
            selected = SelectedGrasp(object_name, arm, replace(candidate, tcp_pose_object=tcp_pose_object))
            contact = contact_scene(snapshot, arm, object_name)
            held = replace(
                held_object_scene(snapshot, arm, object_name, tcp_pose_object),
                gripper_joint_positions=candidate.gripper_joint_positions,
            )
            try:
                await session.planner.solve_ik(
                    arm=arm, start=robot.joints, target=grasp_tcp_pose_env,
                    scene=contact, stage="select_grasp",
                )
                await session.planner.solve_ik(
                    arm=arm, start=robot.joints,
                    target=raised_tcp_pose_env(grasp_tcp_pose_env, session.config.lift_height_m),
                    scene=held, stage="select_lift",
                )
                if target_object_pose_env is not None:
                    for target_object_orientation_env_xyzw in target_object_orientations_env_xyzw(
                        target_object_pose_env, tcp_pose_object,
                        grasp_tcp_pose_env.orientation_xyzw, candidate.approach_axis_tcp,
                        base_position_env_m,
                    ):
                        place_tcp_pose_env = placement_tcp_pose_env(
                            Pose(target_object_pose_env.position_m, target_object_orientation_env_xyzw),
                            tcp_pose_object,
                        )
                        try:
                            await session.planner.solve_ik(
                                arm=arm, start=robot.joints, target=place_tcp_pose_env,
                                scene=replace(
                                    contact, gripper_joint_positions=candidate.gripper_joint_positions,
                                ),
                                stage="select_placement",
                            )
                        except PlanningError as error:
                            if error.code != FailureCode.IK_FAILED:
                                raise
                        else:
                            break
                    else:
                        raise PlanningError(arm, "select_placement", FailureCode.IK_FAILED,
                                            "no reachable placement orientation for candidate")
            except PlanningError as error:
                if error.code != FailureCode.IK_FAILED:
                    raise
                log_candidate(selected, error.code, error.stage, error.reason)
                continue
            yield key, selected


def grasp_tcp_pose_env(session: SkillSession, selected: SelectedGrasp) -> Pose:
    return compose_pose(
        session.context.snapshot().object(selected.object_name).pose_env,
        selected.candidate.tcp_pose_object,
    )
