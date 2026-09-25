"""Observe, approach, grasp and lift, replanning after every physical action."""

from collections.abc import AsyncIterator

from .commands import Hold, SetGripper, SkillCommand
from .errors import FailureCode, PlanningError, SegmentError
from .geometry import approach_start_pose, rotate_vector_xyzw
from .grasp_selection import SelectedGrasp, feasible_grasps, grasp_tcp_pose_env, log_candidate, select_arm
from .manipulation_geometry import raised_tcp_pose_env
from .models import Pick, Pose
from .scene import contact_scene, held_object_scene, world_scene
from .session import SkillSession


class PickSkill:
    """Reusable acquisition state machine shared by pick and pick-and-place."""

    def __init__(self, session: SkillSession, request: Pick, target_object_pose_env: Pose | None) -> None:
        self.session = session
        self.request = request
        self.target_object_pose_env = target_object_pose_env
        self.selected: SelectedGrasp

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
            return


async def pick(session: SkillSession, request: Pick) -> AsyncIterator[SkillCommand]:
    async for command in PickSkill(session, request, None).run():
        yield command


__all__ = ["PickSkill", "pick"]
