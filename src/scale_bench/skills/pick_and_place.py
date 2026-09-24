"""Flat, measured-state pick/transport/place/release/retreat program."""

from collections.abc import AsyncIterator

from .commands import Hold, SetGripper, SkillCommand
from .context import JointState
from .errors import FailureCode, PlanningError, SegmentError, StartStateError
from .geometry import approach_start_pose
from .manipulation_geometry import (
    placement_tcp_pose_env,
    raised_tcp_pose_env,
    target_object_orientations_env_xyzw,
    tcp_geometry_cost,
)
from .models import Arm, Pick, PickAndPlace, Pose
from .pick import PickSkill
from .scene import contact_scene, held_object_scene, world_scene
from .session import SkillSession


async def pick_and_place(session: SkillSession, request: PickAndPlace) -> AsyncIterator[SkillCommand]:
    acquisition = PickSkill(
        session, Pick(request.object_name, request.arm, request.grasp_settle_steps),
        request.target_object_pose_env,
    )
    async for command in acquisition.run():
        yield command
    selected = acquisition.selected
    arm, object_name = selected.arm, selected.object_name
    lifted = session.measure_grasp(object_name, arm, "before_transport")
    object_orientations_env_xyzw = target_object_orientations_env_xyzw(
        request.target_object_pose_env, lifted.tcp_pose_object,
        lifted.tcp_pose_env.orientation_xyzw, selected.candidate.approach_axis_tcp,
        session.settings.arm_base_positions_env_m[arm],
    )
    for index, target_object_orientation_env_xyzw in enumerate(object_orientations_env_xyzw):
        target_object_pose_env = Pose(
            request.target_object_pose_env.position_m, target_object_orientation_env_xyzw,
        )
        grasp = session.measure_grasp(object_name, arm, "before_transport")
        above_place_tcp_pose_env = raised_tcp_pose_env(
            placement_tcp_pose_env(target_object_pose_env, grasp.tcp_pose_object),
            session.config.place_approach_distance_m,
        )
        try:
            async for command in session.move_free(
                arm, above_place_tcp_pose_env,
                held_object_scene(session.context.snapshot(), arm, object_name, grasp.tcp_pose_object), "transport",
            ):
                yield command
        except PlanningError as error:
            if (error.code == FailureCode.START_STATE_INFEASIBLE
                    or index + 1 == len(object_orientations_env_xyzw)):
                raise
            session.recovery(error, index + 1)
            continue
        break

    transported = session.measure_grasp(object_name, arm, "after_transport")
    session.verify_grasp_motion(lifted, transported, "after_transport")
    remaining_target_object_poses_env = tuple(
        Pose(request.target_object_pose_env.position_m, object_orientation_env_xyzw)
        for object_orientation_env_xyzw in dict.fromkeys(object_orientations_env_xyzw)
    )
    # The first attempt has no failure. Keep the failed physical segment when
    # later IK queries find no alternative placement configuration.
    placement_failure: SegmentError | None = None
    for attempt in range(session.config.placement_retries + 1):
        place_motion_started = False
        try:
            grasp = session.measure_grasp(object_name, arm, "before_place")
            target_object_pose_env = await _select_placement(
                session, arm, object_name, grasp.tcp_pose_object,
                remaining_target_object_poses_env, selected.candidate.approach_axis_tcp,
            )
            remaining_target_object_poses_env = tuple(
                candidate_object_pose_env for candidate_object_pose_env in remaining_target_object_poses_env
                if candidate_object_pose_env != target_object_pose_env
            )
            async for command in session.move_free(
                arm, placement_tcp_pose_env(target_object_pose_env, grasp.tcp_pose_object),
                contact_scene(session.context.snapshot(), arm, object_name), "place",
            ):
                place_motion_started = True
                yield command
            yield Hold(steps=request.grasp_settle_steps, label="supported")
            session.verify_placement(
                object_name, arm, target_object_pose_env, "verify_support", FailureCode.CONTACT_FAILED,
            )
        except SegmentError as error:
            if error.code == FailureCode.IK_FAILED and placement_failure is not None:
                raise placement_failure from error
            if error.code in {
                FailureCode.START_STATE_INFEASIBLE, FailureCode.GRASP_FAILED, FailureCode.IK_FAILED,
            }:
                raise
            if attempt == session.config.placement_retries or not remaining_target_object_poses_env:
                raise
            placement_failure = error
            session.recovery(error, attempt + 1)
            if not place_motion_started:
                continue
            # Leave the contact region before changing placement orientation.
            grasp = session.measure_grasp(object_name, arm, "recover_placement")
            if (grasp.object_pose_env.position_m[2] - target_object_pose_env.position_m[2]
                    < session.config.place_approach_distance_m):
                async for command in session.move_linear(
                    arm, raised_tcp_pose_env(grasp.tcp_pose_env, session.config.retreat_distance_m),
                    contact_scene(session.context.snapshot(), arm, object_name),
                    (0.0, 0.0, 1.0), "recover_raise",
                ):
                    yield command
            continue
        break

    for attempt in range(session.config.placement_retries + 1):
        yield SetGripper(
            arm, closed=False, label="release" if attempt == 0 else "recover_release",
        )
        yield Hold(steps=request.release_settle_steps, label="released")
        try:
            session.verify_open_gripper(arm)
            session.verify_placement(
                object_name, arm, target_object_pose_env, "verify_release", FailureCode.RELEASE_FAILED,
            )
        except SegmentError as error:
            if attempt == session.config.placement_retries:
                raise
            session.recovery(error, attempt + 1)
            continue
        break

    for attempt in range(session.config.retreat_attempts):
        snapshot = session.context.snapshot()
        retreat_tcp_pose_env = approach_start_pose(
            snapshot.robot(arm).tcp_pose_env,
            selected.candidate.approach_axis_tcp,
            session.config.retreat_distance_m,
        )
        async for command in session.move_free(
            arm, retreat_tcp_pose_env, contact_scene(snapshot, arm, object_name),
            "retreat" if attempt == 0 else "recover_retreat",
        ):
            yield command
        session.verify_placement(
            object_name, arm, target_object_pose_env, "after_retreat", FailureCode.RELEASE_FAILED,
        )
        snapshot = session.context.snapshot()
        safe_joint_state = JointState(
            snapshot.robot(arm).joints.positions.new_tensor(session.settings.safe_joint_positions[arm]),
        )
        try:
            async for command in session.move_free(arm, safe_joint_state, world_scene(snapshot, arm), "clear"):
                yield command
        except StartStateError as error:
            if (error.violations != (f"object:{object_name}",)
                    or attempt + 1 == session.config.retreat_attempts):
                raise
            session.recovery(error, attempt + 1)
            continue
        break


async def _select_placement(
    session: SkillSession, arm: Arm, object_name: str, tcp_pose_object: Pose,
    target_object_poses_env: tuple[Pose, ...],
    approach_axis_tcp: tuple[float, float, float],
) -> Pose:
    """Check contact IK by geometry cost using the measured grasp relation."""
    snapshot = session.context.snapshot()
    joint_state = snapshot.robot(arm).joints
    for target_object_pose_env in sorted(
        target_object_poses_env,
        key=lambda object_pose_env: tcp_geometry_cost(
            placement_tcp_pose_env(object_pose_env, tcp_pose_object),
            object_pose_env.position_m, approach_axis_tcp,
            session.settings.arm_base_positions_env_m[arm],
        ),
    ):
        place_tcp_pose_env = placement_tcp_pose_env(target_object_pose_env, tcp_pose_object)
        try:
            await session.planner.solve_ik(
                arm=arm, start=joint_state, target=place_tcp_pose_env,
                scene=contact_scene(snapshot, arm, object_name), stage="select_placement",
            )
        except PlanningError as error:
            if error.code != FailureCode.IK_FAILED:
                raise
            continue
        return target_object_pose_env
    raise PlanningError(
        arm, "select_placement", FailureCode.IK_FAILED,
        "no remaining placement orientation has a reachable contact configuration",
    )


__all__ = ["pick_and_place"]
