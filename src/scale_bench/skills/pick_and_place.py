"""Compose acquisition and placement while screening grasps for the destination."""

from collections.abc import AsyncIterator

from .commands import SkillCommand
from .models import Pick, PickAndPlace, Place
from .pick import PickSkill
from .place import place
from .session import SkillSession


async def pick_and_place(session: SkillSession, request: PickAndPlace) -> AsyncIterator[SkillCommand]:
    acquisition = PickSkill(
        session, Pick(request.object_name, request.arm, request.grasp_settle_steps),
        request.target_object_pose_env,
    )
    async for command in acquisition.run():
        yield command
    selected = acquisition.selected
    async for command in place(session, Place(
        object_name=request.object_name,
        arm=selected.arm,
        target_object_pose_env=request.target_object_pose_env,
        approach_axis_tcp=selected.candidate.approach_axis_tcp,
        support_settle_steps=request.grasp_settle_steps,
        release_settle_steps=request.release_settle_steps,
    )):
        yield command


__all__ = ["pick_and_place"]
