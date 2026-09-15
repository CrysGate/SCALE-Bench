"""Pick-only skill program."""

from __future__ import annotations

from collections.abc import AsyncIterator

from .commands import Hold, SetGripper, SkillCommand
from .context import SkillContext
from .models import Pick
from .planner import SkillPlanner


async def pick(
    context: SkillContext,
    planner: SkillPlanner,
    request: Pick,
) -> AsyncIterator[SkillCommand]:
    """Observe, plan, grasp, settle, and lift one object."""

    yield Hold(steps=1, label="observe")
    plan = await planner.plan_pick(request.object_name, request.arm, context)
    yield plan.pre_grasp
    yield plan.grasp
    yield SetGripper(plan.arm, closed=True, label="grasp")
    yield Hold(steps=request.settle_steps, label="grasped")
    grasp = context.measure_grasp(request.object_name, plan.arm)
    lift = await planner.plan_lift(plan, grasp, context)
    yield lift
    yield Hold(steps=request.settle_steps, label="lifted")
    context.measure_grasp(request.object_name, plan.arm)


__all__ = ["pick"]
