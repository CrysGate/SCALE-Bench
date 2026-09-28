"""Observe, approach, grasp and lift, replanning after every physical action."""

import math
from collections.abc import AsyncIterator

from .commands import Hold, SetGripper, SkillCommand
from .context import GraspState, SceneSnapshot
from .errors import FailureCode, PlanningError, SegmentError
from .evaluation import SkillEvaluation
from .geometry import (
    approach_start_pose,
    quaternion_angular_distance_rad,
    relative_pose,
    rotate_vector_xyzw,
)
from .grasp_selection import (
    SelectedGrasp,
    feasible_grasps,
    grasp_tcp_pose_env,
    log_candidate,
    select_arm,
)
from .manipulation_geometry import raised_tcp_pose_env
from .models import Pick, Pose
from .scene import contact_scene, held_object_scene, world_scene
from .session import SkillSession


class PickSkill:
    """Acquisition shared by pick and pick-and-place.

    Standalone pick passes no destination (None). Pick-and-place supplies the
    destination to screen grasp candidates for placement reachability.
    """

    def __init__(self, session: SkillSession, request: Pick, target_object_pose_env: Pose | None) -> None:
        self.session = session
        self.request = request
        self.target_object_pose_env = target_object_pose_env
        self.selected: SelectedGrasp

    def evaluate_success(
        self, before_lift: GraspState, snapshots: tuple[SceneSnapshot, ...],
    ) -> SkillEvaluation:
        """Check measured lift and grasp drift over the final observation window.

        before_lift is measured after closing, before lifting. Observations are
        consecutive control steps after lifting, rather than repeated reads of
        the same simulator state. Insufficient observations report failure.
        """
        config = self.session.config
        thresholds = {
            "lift_error_m": config.grasp_slip_tolerance_m,
            "grasp_translation_drift_m": config.grasp_slip_tolerance_m,
            "grasp_rotation_drift_rad": config.tracking_orientation_tolerance_rad,
            "holding_translation_drift_m": config.skill_stability_position_tolerance_m,
            "holding_rotation_drift_rad": config.skill_stability_orientation_tolerance_rad,
        }
        if len(snapshots) < config.skill_evaluation_steps:
            return SkillEvaluation({}, thresholds, ("insufficient_observations",))
        object_poses_env = tuple(snapshot.object(self.request.object_name).pose_env for snapshot in snapshots)
        tcp_poses_object = tuple(
            relative_pose(object_pose_env, snapshot.robot(before_lift.arm).tcp_pose_env)
            for object_pose_env, snapshot in zip(object_poses_env, snapshots, strict=True)
        )
        object_lifts_m = tuple(
            object_pose_env.position_m[2] - before_lift.object_pose_env.position_m[2]
            for object_pose_env in object_poses_env
        )
        metrics = {
            "minimum_object_lift_m": min(object_lifts_m),
            "lift_error_m": max(abs(height_m - config.lift_height_m) for height_m in object_lifts_m),
            "grasp_translation_drift_m": max(
                math.dist(before_lift.tcp_pose_object.position_m, tcp_pose_object.position_m)
                for tcp_pose_object in tcp_poses_object
            ),
            "grasp_rotation_drift_rad": max(
                quaternion_angular_distance_rad(
                    before_lift.tcp_pose_object.orientation_xyzw, tcp_pose_object.orientation_xyzw,
                ) for tcp_pose_object in tcp_poses_object
            ),
            "holding_translation_drift_m": max(
                math.dist(tcp_poses_object[0].position_m, tcp_pose_object.position_m)
                for tcp_pose_object in tcp_poses_object
            ),
            "holding_rotation_drift_rad": max(
                quaternion_angular_distance_rad(
                    tcp_poses_object[0].orientation_xyzw, tcp_pose_object.orientation_xyzw,
                ) for tcp_pose_object in tcp_poses_object
            ),
        }
        failed_checks = tuple(name for name, limit in thresholds.items() if not metrics[name] <= limit)
        if not metrics["minimum_object_lift_m"] > config.support_height_tolerance_m:
            failed_checks += ("object_not_lifted",)
        return SkillEvaluation(
            metrics, {**thresholds, "minimum_object_lift_m": config.support_height_tolerance_m}, failed_checks,
        )

    async def run(self) -> AsyncIterator[SkillCommand]:
        session, request = self.session, self.request
        yield Hold(steps=1, label="observe")
        arm = select_arm(session, request.object_name, request.arm)

        candidates = await session.context.grasp_candidates(request.object_name, arm)
        excluded: set[tuple[int, int]] = set()
        for attempt in range(session.config.grasp_attempts):
            selection_failure = PlanningError(
                arm, "select_grasp", FailureCode.IK_FAILED, "no remaining reachable grasp candidate",
            )
            async for key, selected in feasible_grasps(
                session, request.object_name, arm, candidates, self.target_object_pose_env, excluded,
            ):
                excluded.add(key)
                target_tcp_pose_env = grasp_tcp_pose_env(session, selected)
                pregrasp_tcp_pose_env = approach_start_pose(
                    target_tcp_pose_env, selected.candidate.approach_axis_tcp,
                    selected.candidate.approach_distance_m,
                )
                try:
                    async for command in session.move_free(
                        arm, pregrasp_tcp_pose_env, world_scene(session.context.snapshot(), arm), "pregrasp",
                    ):
                        yield command
                except PlanningError as error:
                    if error.code == FailureCode.START_STATE_INFEASIBLE:
                        raise
                    session.recovery(error, attempt + 1)
                    log_candidate(selected, error.code, error.stage, error.reason)
                    selection_failure = error
                    continue
                log_candidate(selected, "SELECTED", "pregrasp", "reachable approach executed")
                break
            else:
                raise selection_failure

            source_object_pose_env = session.context.snapshot().object(request.object_name).pose_env
            grasp_motion_started = False
            try:
                # The object and TCP are observed again after the free approach.
                target_tcp_pose_env = grasp_tcp_pose_env(session, selected)
                approach_axis_env = rotate_vector_xyzw(
                    target_tcp_pose_env.orientation_xyzw, selected.candidate.approach_axis_tcp,
                )
                async for command in session.move_linear(
                    arm, target_tcp_pose_env,
                    contact_scene(
                        session.context.snapshot(), arm, request.object_name, check_finger_collision=False,
                    ),
                    approach_axis_env, "grasp",
                ):
                    grasp_motion_started = True
                    yield command
                yield SetGripper(arm, closed=True, label="close")
                yield Hold(steps=request.settle_steps, label="grasped")
                grasp = session.measure_grasp(request.object_name, arm, "verify_grasp")
                async for command in session.move_linear(
                    arm, raised_tcp_pose_env(grasp.tcp_pose_env, session.config.lift_height_m),
                    held_object_scene(
                        session.context.snapshot(), arm, request.object_name, grasp.tcp_pose_object,
                    ),
                    (0.0, 0.0, 1.0), "lift",
                ):
                    yield command
                yield Hold(steps=request.settle_steps, label="lifted")
                lifted = session.measure_grasp(request.object_name, arm, "verify_lift")
                session.verify_grasp_motion(grasp, lifted, "verify_lift")
                lift_error_m = abs(
                    lifted.object_pose_env.position_m[2] - grasp.object_pose_env.position_m[2]
                    - session.config.lift_height_m
                )
                session.verify(arm, "verify_lift", lift_error_m <= session.config.grasp_slip_tolerance_m,
                               FailureCode.GRASP_FAILED,
                               {"check": "object_lift", "lift_error_m": lift_error_m})
            except SegmentError as error:
                if isinstance(error, PlanningError) and error.code == FailureCode.START_STATE_INFEASIBLE:
                    raise
                session.recovery(error, attempt + 1)
                if not grasp_motion_started:
                    # No grasp command was dispatched; no physical recovery is needed.
                    log_candidate(selected, error.code, error.stage, error.reason)
                    if attempt + 1 == session.config.grasp_attempts:
                        raise
                    continue
                # If the object rose before failure, set it back down before opening.
                snapshot = session.context.snapshot()
                rise_m = (
                    snapshot.object(request.object_name).pose_env.position_m[2]
                    - source_object_pose_env.position_m[2]
                )
                if rise_m > session.config.support_height_tolerance_m:
                    async for command in session.move_linear(
                        arm, raised_tcp_pose_env(snapshot.robot(arm).tcp_pose_env, -rise_m),
                        contact_scene(snapshot, arm, request.object_name, check_finger_collision=True),
                        (0.0, 0.0, -1.0), "recover_lower",
                    ):
                        yield command
                yield SetGripper(arm, closed=False, label="recover_open")
                yield Hold(steps=request.settle_steps, label="recover_released")
                snapshot = session.context.snapshot()
                tcp_pose_env = snapshot.robot(arm).tcp_pose_env
                retreat_axis_env = rotate_vector_xyzw(
                    tcp_pose_env.orientation_xyzw, selected.candidate.approach_axis_tcp,
                )
                async for command in session.move_linear(
                    arm, approach_start_pose(tcp_pose_env, selected.candidate.approach_axis_tcp,
                                             session.config.retreat_distance_m),
                    contact_scene(snapshot, arm, request.object_name, check_finger_collision=False),
                    tuple(-value for value in retreat_axis_env), "recover_retreat",
                ):
                    yield command
                if attempt + 1 == session.config.grasp_attempts:
                    raise
                continue
            self.selected = selected
            snapshots: list[SceneSnapshot] = []
            for _ in range(session.config.skill_evaluation_steps):
                yield Hold(steps=1, label="evaluate_pick")
                snapshots.append(session.context.snapshot())
            session.record_evaluation(
                "pick", request.object_name, arm, self.evaluate_success(grasp, tuple(snapshots)),
            )
            return


async def pick(session: SkillSession, request: Pick) -> AsyncIterator[SkillCommand]:
    async for command in PickSkill(session, request, None).run():
        yield command


__all__ = ["PickSkill", "pick"]
